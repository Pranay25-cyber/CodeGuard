
import hmac
import logging
import os
import secrets

import httpx

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

GITHUB_CLIENT_ID = os.getenv("GITHUB_OAUTH_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_OAUTH_CLIENT_SECRET")

GITHUB_CALLBACK_URL = os.getenv(
    "GITHUB_OAUTH_CALLBACK_URL",
    "http://localhost:8000/auth/github/callback"
)

FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "http://localhost:5173"
)


@router.get("/github/login")
def github_login(request: Request):
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="GitHub OAuth credentials are not configured."
        )

    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    

    github_url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={GITHUB_CALLBACK_URL}"
        "&scope=read:user%20user:email"
        f"&state={state}"
    )

    return RedirectResponse(github_url)


@router.get("/github/callback")
async def github_callback(
    request: Request,
    code: str,
    state: str,
    db: Session = Depends(get_db)
):
    expected_state = request.session.pop("oauth_state", None)
    
    if not expected_state or not hmac.compare_digest(expected_state, state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": GITHUB_CLIENT_ID,
                    "client_secret": GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": GITHUB_CALLBACK_URL,
                },
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()

            access_token = token_response.json().get("access_token")

            if not access_token:
                raise HTTPException(
                    status_code=400,
                    detail="GitHub did not return an access token."
                )

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }

            profile_response = await client.get(
                "https://api.github.com/user",
                headers=headers,
            )
            profile_response.raise_for_status()
            profile = profile_response.json()

            email = profile.get("email")

            if not email:
                email_response = await client.get(
                    "https://api.github.com/user/emails",
                    headers=headers,
                )

                if email_response.is_success:
                    emails = email_response.json()
                    email = next(
                        (
                            item["email"]
                            for item in emails
                            if item.get("primary") and item.get("verified")
                        ),
                        None,
                    )

        user = db.query(User).filter(
            User.github_id == profile["id"]
        ).first()

        if user:
            user.github_login = profile["login"]
            user.name = profile.get("name")
            user.email = email
            user.avatar_url = profile.get("avatar_url")
        else:
            user = User(
                github_id=profile["id"],
                github_login=profile["login"],
                name=profile.get("name"),
                email=email,
                avatar_url=profile.get("avatar_url"),
            )
            db.add(user)

        db.commit()
        db.refresh(user)

        request.session.clear()
        request.session["user_id"] = user.id

        return RedirectResponse(
            url=FRONTEND_URL,
            status_code=302,
        )

    except HTTPException:
        raise
    except httpx.HTTPError:
        db.rollback()
        logger.exception("GitHub OAuth request failed.")
        raise HTTPException(
            status_code=502,
            detail="Unable to communicate with GitHub."
        )
    except Exception:
        db.rollback()
        logger.exception("GitHub OAuth callback failed.")
        raise HTTPException(
            status_code=500,
            detail="GitHub login failed."
        )


@router.get("/me")
def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = request.session.get("user_id")

    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Invalid user session.")

    return {
        "id": user.id,
        "github_id": user.github_id,
        "github_login": user.github_login,
        "name": user.name,
        "email": user.email,
        "avatar_url": user.avatar_url,
    }


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"message": "Successfully logged out."}
