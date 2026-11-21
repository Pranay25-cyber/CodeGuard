import logging
import os
import secrets

import requests
from github.GithubException import GithubException

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import GitHubInstallation, Repository, User
from app.github.github_service import get_github_integration


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/github-installations",
    tags=["GitHub Installations"],
)

GITHUB_API_BASE_URL = "https://api.github.com"


def require_login(request: Request) -> int:
    """Ensure the user has authenticated through GitHub OAuth."""
    user_id = request.session.get("user_id")

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Please sign in with GitHub first.",
        )

    try:
        return int(user_id)
    except (TypeError, ValueError):
        request.session.clear()
        raise HTTPException(
            status_code=401,
            detail="Your login session is invalid. Please sign in again.",
        )


def get_frontend_url() -> str:
    """Return the configured frontend URL without a trailing slash."""
    return os.getenv(
        "FRONTEND_URL",
        "http://localhost:5173",
    ).rstrip("/")


def get_user_installation(
    db: Session,
    user_id: int,
    installation_id: int | None = None,
) -> GitHubInstallation | None:
    """Return an installation only when it belongs to this user."""
    query = db.query(GitHubInstallation).filter(
        GitHubInstallation.user_id == user_id
    )

    if installation_id is not None:
        query = query.filter(
            GitHubInstallation.installation_id == installation_id
        )

    return query.order_by(
        GitHubInstallation.id.desc()
    ).first()


def get_installation_access_token(installation_id: int) -> str:
    """Generate an installation access token using the SaaS GitHub App."""
    if installation_id < 1:
        raise HTTPException(
            status_code=400,
            detail="Invalid GitHub installation ID.",
        )

    try:
        integration = get_github_integration()
        token_response = integration.get_access_token(installation_id)
        access_token = token_response.token

        if not access_token:
            raise HTTPException(
                status_code=502,
                detail="GitHub did not return an installation access token.",
            )

        return access_token

    except HTTPException:
        raise

    except GithubException as exc:
        logger.exception(
            "GitHub rejected installation token generation. HTTP status: %s",
            exc.status,
        )
        raise HTTPException(
            status_code=502,
            detail=(
                "GitHub rejected authentication for this installation "
                f"(HTTP {exc.status})."
            ),
        )

    except Exception:
        logger.exception(
            "Failed to generate GitHub installation access token."
        )
        raise HTTPException(
            status_code=502,
            detail="Unable to authenticate with the GitHub App installation.",
        )


def get_installation_headers(installation_id: int) -> dict:
    """Return headers for GitHub installation-token API requests."""
    access_token = get_installation_access_token(installation_id)

    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_github_installation_account(
    installation_id: int,
) -> tuple[str, str | None]:
    """
    Verify an installation using GitHub App authentication (JWT).

    Important:
    GET /installation is an App-authenticated endpoint. It must not be
    called with an installation access token. PyGithub's
    GithubIntegration.get_app_installation() uses the App integration.
    """
    if installation_id < 1:
        raise HTTPException(
            status_code=400,
            detail="Invalid GitHub installation ID.",
        )

    try:
        integration = get_github_integration()
        installation = integration.get_app_installation(installation_id)
        account = installation.account

        account_login = getattr(account, "login", None)
        account_type = getattr(account, "type", None)

        if not account_login:
            raise HTTPException(
                status_code=502,
                detail="GitHub did not return installation account details.",
            )

        return account_login, account_type

    except HTTPException:
        raise

    except GithubException as exc:
        logger.exception(
            "GitHub App installation verification failed. "
            "Installation ID: %s, HTTP status: %s",
            installation_id,
            exc.status,
        )
        raise HTTPException(
            status_code=502,
            detail=(
                "GitHub installation verification failed "
                f"(HTTP {exc.status}). Check the App ID and private key."
            ),
        )

    except Exception:
        logger.exception(
            "Unexpected error while verifying GitHub App installation. "
            "Installation ID: %s",
            installation_id,
        )
        raise HTTPException(
            status_code=502,
            detail=(
                "Unable to verify this GitHub App installation. "
                "Check the backend terminal for the detailed error."
            ),
        )


@router.get("/status")
def installation_status(
    request: Request,
    db: Session = Depends(get_db),
):
    """Check the logged-in user's persisted GitHub installation."""
    user_id = require_login(request)

    installation = get_user_installation(
        db,
        user_id,
    )

    if not installation:
        request.session.pop("installation_id", None)
        return {
            "connected": False,
            "installation_id": None,
        }

    installation_id = installation.installation_id

    try:
        headers = get_installation_headers(installation_id)

        response = requests.get(
            f"{GITHUB_API_BASE_URL}/installation/repositories",
            headers=headers,
            params={"per_page": 1},
            timeout=30,
        )

        if response.status_code == 200:
            request.session["installation_id"] = installation_id
            return {
                "connected": True,
                "installation_id": installation_id,
                "account_login": installation.account_login,
                "account_type": installation.account_type,
            }

        logger.warning(
            "GitHub installation is no longer accessible. "
            "User ID: %s, Installation ID: %s, Status: %s, Response: %s",
            user_id,
            installation_id,
            response.status_code,
            response.text[:500],
        )

        request.session.pop("installation_id", None)
        return {
            "connected": False,
            "installation_id": None,
        }

    except HTTPException:
        raise

    except requests.RequestException:
        logger.exception(
            "Unable to verify stored GitHub installation."
        )
        raise HTTPException(
            status_code=502,
            detail="Unable to verify GitHub installation status.",
        )


@router.get("/connect")
def connect_github_app(request: Request):
    """Redirect the authenticated user to install/configure the GitHub App."""
    require_login(request)

    app_slug = os.getenv("GITHUB_APP_SLUG")

    if not app_slug:
        raise HTTPException(
            status_code=500,
            detail="GITHUB_APP_SLUG is missing in backend .env.",
        )

    state = secrets.token_urlsafe(32)
    request.session["github_install_state"] = state

    install_url = (
        f"https://github.com/apps/{app_slug}/installations/new"
        f"?state={state}"
    )

    return RedirectResponse(
        url=install_url,
        status_code=302,
    )


@router.get("/callback")
def github_installation_callback(
    request: Request,
    installation_id: int,
    setup_action: str,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    """Verify a GitHub installation and persist its user ownership."""
    user_id = require_login(request)

    if installation_id < 1:
        raise HTTPException(
            status_code=400,
            detail="Invalid GitHub installation ID.",
        )

    if setup_action not in {"install", "update"}:
        raise HTTPException(
            status_code=400,
            detail="GitHub App installation was not completed.",
        )

    # Validate the state generated by /connect. An update callback without
    # state is accepted only when this installation is already linked to
    # the currently authenticated user.
    expected_state = request.session.get("github_install_state")

    if expected_state:
        if (
            not state
            or not secrets.compare_digest(expected_state, state)
        ):
            raise HTTPException(
                status_code=400,
                detail="Invalid GitHub installation state. Please try again.",
            )

        request.session.pop("github_install_state", None)

    else:
        if setup_action != "update" or state is not None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Installation state could not be verified. "
                    "Please connect GitHub through the application."
                ),
            )

        existing_installation = (
            db.query(GitHubInstallation)
            .filter(
                GitHubInstallation.installation_id == installation_id
            )
            .first()
        )

        if (
            not existing_installation
            or existing_installation.user_id != user_id
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    "This installation is not connected to your account. "
                    "Please start the connection from the application."
                ),
            )

    try:
        # Use GitHub App authentication (JWT) to retrieve installation
        # metadata. Do not use an installation access token for this call.
        account_login, account_type = get_github_installation_account(
            installation_id
        )

        existing_installation = (
            db.query(GitHubInstallation)
            .filter(
                GitHubInstallation.installation_id == installation_id
            )
            .first()
        )

        if existing_installation:
            if existing_installation.user_id != user_id:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This GitHub installation is already linked "
                        "to another application user."
                    ),
                )

            existing_installation.account_login = account_login
            existing_installation.account_type = account_type

        else:
            db.add(
                GitHubInstallation(
                    user_id=user_id,
                    installation_id=installation_id,
                    account_login=account_login,
                    account_type=account_type,
                )
            )

        db.commit()

        # Keep this for compatibility with existing frontend code.
        request.session["installation_id"] = installation_id

        logger.info(
            "GitHub installation connected. "
            "User ID: %s, Installation ID: %s, Account: %s",
            user_id,
            installation_id,
            account_login,
        )

    except HTTPException:
        db.rollback()
        raise

    except GithubException as exc:
        db.rollback()
        logger.exception(
            "GitHub installation verification failed. HTTP status: %s",
            exc.status,
        )
        raise HTTPException(
            status_code=502,
            detail=(
                "GitHub installation verification failed "
                f"(HTTP {exc.status})."
            ),
        )

    except Exception:
        db.rollback()
        logger.exception(
            "Unable to save or verify GitHub installation ownership."
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to save GitHub installation.",
        )

    return RedirectResponse(
        url=f"{get_frontend_url()}/?github_installation=connected",
        status_code=303,
    )


class CreateGitHubRepositoryRequest(BaseModel):
    """Validated input for creating a repository in the connected personal account."""

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=350)
    private: bool = True


@router.post("/repositories/create", status_code=201)
def create_github_repository(
    payload: CreateGitHubRepositoryRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a GitHub repository for the signed-in user's personal account.

    The GitHub App installation token must have Repository creation: write
    (or Administration: write). A repository is synchronized into CodeGuard
    only when the installation can access it.
    """
    user_id = require_login(request)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Your login session is invalid. Please sign in again.")

    installation = get_user_installation(db, user_id)
    if not installation:
        raise HTTPException(status_code=409, detail="Connect your GitHub App installation first.")

    # This endpoint intentionally creates personal repositories only.
    if (installation.account_type or "").casefold() != "user":
        raise HTTPException(
            status_code=409,
            detail="Your connected GitHub App installation belongs to an organization. Connect the installation for your personal GitHub account to create a personal repository.",
        )
    if (installation.account_login or "").casefold() != (user.github_login or "").casefold():
        raise HTTPException(
            status_code=403,
            detail="Your connected GitHub App installation does not belong to the GitHub account used to sign in.",
        )

    repository_name = payload.name.strip()
    if not repository_name:
        raise HTTPException(status_code=422, detail="Repository name cannot be empty.")

    headers = get_installation_headers(installation.installation_id)
    create_response = None
    try:
        create_response = requests.post(
            f"{GITHUB_API_BASE_URL}/user/repos",
            headers=headers,
            json={
                "name": repository_name,
                "description": (payload.description or "").strip() or None,
                "private": payload.private,
                # An initial README creates the default branch, so the
                # repository can be selected immediately in the Code Editor.
                "auto_init": True,
            },
            timeout=30,
        )

        if create_response.status_code == 422:
            raise HTTPException(
                status_code=409,
                detail="A repository with this name already exists in your GitHub account, or the name is invalid.",
            )
        if create_response.status_code in (401, 403):
            logger.error(
                "GitHub repository creation denied. HTTP %s: %s",
                create_response.status_code, create_response.text[:500],
            )
            raise HTTPException(
                status_code=403,
                detail=(
                    "GitHub denied repository creation. Check that the GitHub App has "
                    "Repository creation: Read and write permission, then update/reinstall "
                    "the App installation so the permission is granted."
                ),
            )
        create_response.raise_for_status()
        repo = create_response.json()

        # Verify that this GitHub App installation can see the new repository.
        # Selected-repository installations may need the owner to update access.
        list_url = f"{GITHUB_API_BASE_URL}/installation/repositories"
        list_params = {"per_page": 100, "page": 1}
        installation_can_access_repo = False
        while list_url:
            list_response = requests.get(
                list_url,
                headers=headers,
                params=list_params,
                timeout=30,
            )
            list_response.raise_for_status()
            if any(
                int(item.get("id", 0)) == int(repo["id"])
                for item in list_response.json().get("repositories", [])
            ):
                installation_can_access_repo = True
                break
            list_url = list_response.links.get("next", {}).get("url")
            list_params = None

        if not installation_can_access_repo:
            return {
                "created": True,
                "installation_access_required": True,
                "repository": {
                    "id": repo["id"],
                    "name": repo["name"],
                    "full_name": repo["full_name"],
                    "html_url": repo["html_url"],
                    "private": repo["private"],
                    "default_branch": repo.get("default_branch"),
                },
                "installation_settings_url": f"https://github.com/settings/installations/{installation.installation_id}",
                "message": "Repository created on GitHub. Update the GitHub App repository access to include it, then refresh CodeGuard.",
            }

        existing = (
            db.query(Repository)
            .filter(Repository.github_repo_id == int(repo["id"]))
            .first()
        )
        if existing and existing.user_id not in (None, user_id):
            raise HTTPException(
                status_code=409,
                detail="This GitHub repository is already linked to another CodeGuard account.",
            )
        if existing is None:
            existing = Repository(
                github_repo_id=int(repo["id"]),
                name=repo["name"],
                full_name=repo["full_name"],
                html_url=repo["html_url"],
                user_id=user_id,
                installation_id=installation.installation_id,
            )
            db.add(existing)
        else:
            existing.name = repo["name"]
            existing.full_name = repo["full_name"]
            existing.html_url = repo["html_url"]
            existing.user_id = user_id
            existing.installation_id = installation.installation_id
        db.commit()
        db.refresh(existing)

        return {
            "created": True,
            "installation_access_required": False,
            "repository": {
                "id": repo["id"],
                "name": repo["name"],
                "full_name": repo["full_name"],
                "html_url": repo["html_url"],
                "private": repo["private"],
                "default_branch": repo.get("default_branch"),
            },
            "message": "Repository created and connected to CodeGuard.",
        }

    except HTTPException:
        db.rollback()
        raise
    except requests.RequestException as exc:
        db.rollback()
        logger.exception("GitHub repository creation or access verification failed.")
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code == 404:
            raise HTTPException(status_code=403, detail="The GitHub App installation cannot access the requested account or repository.")
        raise HTTPException(status_code=502, detail="GitHub could not complete the repository creation request. Check the backend logs and try again.")
    except Exception:
        db.rollback()
        logger.exception("Unexpected error while creating a GitHub repository.")
        raise HTTPException(status_code=500, detail="Repository was created or checked, but CodeGuard could not finish synchronizing it. Refresh repositories and check GitHub before retrying.")


@router.get("/repositories")
def list_installation_repositories(
    request: Request,
    search: str = "",
    db: Session = Depends(get_db),
):
    """Retrieve repositories from the logged-in user's installation."""
    user_id = require_login(request)

    installation = get_user_installation(
        db,
        user_id,
    )

    if not installation:
        raise HTTPException(
            status_code=409,
            detail="Connect your GitHub App installation first.",
        )

    installation_id = installation.installation_id

    try:
        headers = get_installation_headers(installation_id)

        repositories = []
        url = f"{GITHUB_API_BASE_URL}/installation/repositories"
        params = {
            "per_page": 100,
            "page": 1,
        }
        search_text = search.strip().casefold()

        while url:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()

            for repo in data.get("repositories", []):
                item = {
                    "id": repo["id"],
                    "name": repo["name"],
                    "full_name": repo["full_name"],
                    "html_url": repo["html_url"],
                    "private": repo["private"],
                    "default_branch": repo["default_branch"],
                }

                # Synchronize every repository returned by this verified
                # installation into the database. Do this before applying
                # the optional search filter so a search does not limit sync.
                db_repository = (
                    db.query(Repository)
                    .filter(Repository.github_repo_id == item["id"])
                    .first()
                )

                if db_repository is None:
                    db_repository = (
                        db.query(Repository)
                        .filter(Repository.full_name == item["full_name"])
                        .first()
                    )

                if db_repository is None:
                    db_repository = Repository(
                        github_repo_id=item["id"],
                        name=item["name"],
                        full_name=item["full_name"],
                        html_url=item["html_url"],
                        user_id=user_id,
                        installation_id=installation_id,
                    )
                    db.add(db_repository)
                elif db_repository.user_id in (None, user_id):
                    # Claim unassigned rows, or refresh rows already owned
                    # by this user. Never transfer another user's row.
                    db_repository.github_repo_id = item["id"]
                    db_repository.name = item["name"]
                    db_repository.full_name = item["full_name"]
                    db_repository.html_url = item["html_url"]
                    db_repository.user_id = user_id
                    db_repository.installation_id = installation_id
                else:
                    logger.warning(
                        "Repository %s is already assigned to another "
                        "application user; ownership was not changed.",
                        item["full_name"],
                    )

                if (
                    not search_text
                    or search_text in item["full_name"].casefold()
                ):
                    repositories.append(item)

            url = response.links.get("next", {}).get("url")
            params = None

        # Save the repository synchronization in one transaction.
        db.commit()

        return {
            "total": len(repositories),
            "repositories": repositories,
        }

    except HTTPException:
        raise

    except requests.RequestException:
        logger.exception(
            "GitHub repository listing failed. Installation ID: %s",
            installation_id,
        )
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve repositories from GitHub.",
        )

    except (KeyError, ValueError):
        db.rollback()
        logger.exception(
            "Unexpected GitHub repository response."
        )
        raise HTTPException(
            status_code=502,
            detail="GitHub returned an unexpected repository response.",
        )

    except Exception:
        db.rollback()
        logger.exception(
            "GitHub repository synchronization failed. "
            "Installation ID: %s, User ID: %s",
            installation_id,
            user_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to synchronize GitHub repositories.",
        )
