import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import FixProposal, Repository, User
from app.routes.auth import get_current_user
from app.github.github_fix_service import publish_fix_to_original_pr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fixes", tags=["AI Fixes"])


def get_user_github_login(user_id: int, db: Session) -> str | None:
    return (
        db.query(User.github_login)
        .filter(User.id == user_id)
        .scalar()
    )


def repository_access_filter(user_id: int, github_login: str | None):
    """Keep ownership checks; support legacy unassigned personal repositories."""
    conditions = [Repository.user_id == user_id]

    if github_login:
        owner = func.split_part(Repository.full_name, "/", 1)
        conditions.append(
            and_(
                Repository.user_id.is_(None),
                func.lower(owner) == github_login.lower(),
            )
        )

    return or_(*conditions)


def get_owned_proposal(
    fix_id: int,
    user_id: int,
    db: Session,
    lock: bool = False,
):
    github_login = get_user_github_login(user_id, db)

    query = (
        db.query(FixProposal)
        .join(
            Repository,
            FixProposal.repository_full_name == Repository.full_name,
        )
        .filter(
            FixProposal.id == fix_id,
            repository_access_filter(user_id, github_login),
        )
    )

    if lock:
        query = query.with_for_update()

    proposal = query.first()
    if proposal is None:
        raise HTTPException(
            status_code=404,
            detail="Fix proposal not found or you do not have access to its repository.",
        )

    return proposal


def proposal_payload(proposal: FixProposal, include_code: bool = False):
    payload = {
        "id": proposal.id,
        "status": proposal.status,
        "repository_full_name": proposal.repository_full_name,
        "original_pr_number": proposal.original_pr_number,
        "original_commit_sha": proposal.original_commit_sha,
        "filename": proposal.filename,
        "changes_summary": proposal.changes_summary,
        "validation": proposal.validation_result,
        "automated_tests": proposal.test_result,
        "github": proposal.github_result,
        "error_message": proposal.error_message,
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
        "approved_at": proposal.approved_at,
        "rejected_at": proposal.rejected_at,
        "published_at": proposal.published_at,
    }

    if include_code:
        payload["original_code"] = proposal.original_code
        payload["fixed_code"] = proposal.fixed_code

    return payload


@router.get("/")
def get_fix_proposals(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = int(current_user["id"])
    github_login = get_user_github_login(user_id, db)

    proposals = (
        db.query(FixProposal)
        .join(
            Repository,
            FixProposal.repository_full_name == Repository.full_name,
        )
        .filter(repository_access_filter(user_id, github_login))
        .order_by(FixProposal.created_at.desc())
        .all()
    )

    return [proposal_payload(proposal) for proposal in proposals]


@router.get("/{fix_id}")
def get_fix_proposal(
    fix_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proposal = get_owned_proposal(
        fix_id=fix_id,
        user_id=int(current_user["id"]),
        db=db,
    )
    return proposal_payload(proposal, include_code=True)


@router.post("/{fix_id}/approve")
def approve_fix_proposal(
    fix_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proposal = get_owned_proposal(
        fix_id=fix_id,
        user_id=int(current_user["id"]),
        db=db,
        lock=True,
    )

    if proposal.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=(
                "Fix proposal cannot be approved from status "
                f"'{proposal.status}'"
            ),
        )

    proposal.status = "publishing"
    proposal.approved_at = datetime.now(timezone.utc)
    proposal.error_message = None
    db.commit()
    db.refresh(proposal)

    try:
        github_result = publish_fix_to_original_pr(
            repository_full_name=proposal.repository_full_name,
            original_pr_number=proposal.original_pr_number,
            filename=proposal.filename,
            fixed_code=proposal.fixed_code,
            changes_summary=proposal.changes_summary,
            expected_head_sha=proposal.original_commit_sha,
        )

    except ValueError as error:
        message = str(error).lower()
        is_stale = any(word in message for word in ("changed", "sha", "commit"))
        proposal.status = "stale" if is_stale else "publish_failed"
        proposal.error_message = (
            "The original Pull Request changed after this fix was generated."
            if is_stale
            else "GitHub rejected the approved fix publication."
        )
        db.commit()
        logger.warning("Fix proposal %s could not be published: %s", fix_id, error)
        raise HTTPException(
            status_code=409 if is_stale else 502,
            detail=proposal.error_message,
        ) from error

    except PermissionError as error:
        proposal.status = "publish_failed"
        proposal.error_message = (
            "The GitHub App does not have permission to update "
            "the original Pull Request branch."
        )
        db.commit()
        logger.warning("GitHub permission denied for proposal %s: %s", fix_id, error)
        raise HTTPException(status_code=403, detail=proposal.error_message) from error

    except Exception as error:
        proposal.status = "publish_failed"
        proposal.error_message = (
            "An unexpected error occurred while publishing the approved fix."
        )
        db.commit()
        logger.exception(
            "Unexpected GitHub publishing error for proposal %s",
            fix_id,
        )
        raise HTTPException(
            status_code=502,
            detail="The approved fix could not be published.",
        ) from error

    proposal.status = "published"
    proposal.github_result = github_result
    proposal.published_at = datetime.now(timezone.utc)
    proposal.error_message = None
    db.commit()
    db.refresh(proposal)

    return proposal_payload(proposal)


@router.post("/{fix_id}/reject")
def reject_fix_proposal(
    fix_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proposal = get_owned_proposal(
        fix_id=fix_id,
        user_id=int(current_user["id"]),
        db=db,
        lock=True,
    )

    if proposal.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=(
                "Fix proposal cannot be rejected from status "
                f"'{proposal.status}'"
            ),
        )

    proposal.status = "rejected"
    proposal.rejected_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(proposal)

    return proposal_payload(proposal)
