
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, selectinload
from fastapi import APIRouter, Depends, HTTPException, Request, Query

from app.database.connection import get_db
from app.database.models import Review, PullRequest, Repository
from app.schemas.review_schema import (
    ReviewResponse,
    PullRequestReviewResponse,
)

router = APIRouter(
    prefix="/reviews",
    tags=["Code Reviews"],
)


def get_logged_in_user_id(request: Request) -> int:
    user_id = request.session.get("user_id")

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Please log in to access reviews",
        )

    return user_id


# 1. Retrieve reviews belonging to the logged-in user
@router.get("/", response_model=list[ReviewResponse])
def get_all_reviews(
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = get_logged_in_user_id(request)

    reviews = (
        db.query(Review)
        .join(Review.pull_request)
        .join(PullRequest.repository)
        .filter(Repository.user_id == user_id)
        .options(
            selectinload(Review.files),
            selectinload(Review.issues),
        )
        .order_by(Review.created_at.desc())
        .all()
    )

    return reviews


# 2. Retrieve one review belonging to the logged-in user
@router.get("/{review_id}", response_model=ReviewResponse)
def get_review_by_id(
    review_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = get_logged_in_user_id(request)

    review = (
        db.query(Review)
        .join(Review.pull_request)
        .join(PullRequest.repository)
        .filter(
            Review.id == review_id,
            Repository.user_id == user_id,
        )
        .options(
            selectinload(Review.files),
            selectinload(Review.issues),
        )
        .first()
    )

    if review is None:
        raise HTTPException(
            status_code=404,
            detail="Review not found",
        )

    return review


# 3. Retrieve reviews for a PR belonging to the logged-in user
@router.get(
    "/pull-request/{pr_number}",
    response_model=list[PullRequestReviewResponse],
)
def get_reviews_by_pull_request(
    pr_number: int,
    request: Request,
    repository_full_name: str = Query(...),
    db: Session = Depends(get_db),
):
    user_id = get_logged_in_user_id(request)

    pull_request = (
        db.query(PullRequest)
        .join(PullRequest.repository)
        .filter(
            PullRequest.github_pr_number == pr_number,
            Repository.user_id == user_id,
            Repository.full_name == repository_full_name,
        )
        .options(
            selectinload(PullRequest.reviews).selectinload(Review.files),
            selectinload(PullRequest.reviews).selectinload(Review.issues),
        )
        .first()
    )

    if pull_request is None:
        raise HTTPException(
            status_code=404,
            detail="Pull Request not found",
        )

    return [pull_request]