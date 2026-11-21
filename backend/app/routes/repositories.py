
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Repository, GitHubInstallation
from app.schemas.repository_schema import (
    RepositoryCreate,
    RepositoryResponse,
)

router = APIRouter(
    prefix="/repositories",
    tags=["Repositories"],
)


def get_logged_in_user_id(request: Request) -> int:
    """Get the authenticated user's ID from the session."""
    user_id = request.session.get("user_id")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please log in first",
        )

    return int(user_id)


def get_user_installation(
    db: Session,
    user_id: int,
) -> GitHubInstallation:
    """Get the GitHub App installation belonging to this user."""
    installation = (
        db.query(GitHubInstallation)
        .filter(GitHubInstallation.user_id == user_id)
        .order_by(GitHubInstallation.id.desc())
        .first()
    )

    if not installation:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Connect your GitHub App before registering repositories",
        )

    return installation


# Register a GitHub repository
@router.post(
    "/",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_repository(
    repository: RepositoryCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = get_logged_in_user_id(request)
    installation = get_user_installation(db, user_id)

    # Check whether this repository is already registered.
    # Repository currently has global uniqueness constraints,
    # so do not allow one user to take another user's record.
    existing_repository = (
        db.query(Repository)
        .filter(
            (Repository.github_repo_id == repository.github_repo_id)
            | (Repository.full_name == repository.full_name)
        )
        .first()
    )

    if existing_repository:
        if existing_repository.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This repository is already registered under another account",
            )

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository already registered",
        )

    new_repository = Repository(
        github_repo_id=repository.github_repo_id,
        name=repository.name,
        full_name=repository.full_name,
        html_url=repository.html_url,
        user_id=user_id,
        installation_id=installation.installation_id,
    )

    try:
        db.add(new_repository)
        db.commit()
        db.refresh(new_repository)
        return new_repository

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save repository",
        )


# Get only the logged-in user's registered repositories
@router.get(
    "/",
    response_model=list[RepositoryResponse],
)
def get_repositories(
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = get_logged_in_user_id(request)

    return (
        db.query(Repository)
        .filter(Repository.user_id == user_id)
        .all()
    )


# Get one repository belonging to the logged-in user
@router.get(
    "/{repository_id}",
    response_model=RepositoryResponse,
)
def get_repository(
    repository_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = get_logged_in_user_id(request)

    repository = (
        db.query(Repository)
        .filter(
            Repository.id == repository_id,
            Repository.user_id == user_id,
        )
        .first()
    )

    if not repository:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    return repository
