
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.database.connection import get_db
from app.database.models import Review, PullRequest
from app.schemas.review_schema import (
    ReviewResponse,
    PullRequestReviewResponse,
)

# Create the router
router = APIRouter(
    prefix="/reviews",
    tags=["Code Reviews"],
)


# 1. Retrieve all saved reviews
@router.get("/", response_model=list[ReviewResponse])
def get_all_reviews(db: Session = Depends(get_db)):

    reviews = (
        db.query(Review)
        .options(
            selectinload(Review.files),
            selectinload(Review.issues),
        )
        .order_by(Review.created_at.desc())
        .all()
    )

    return reviews


# 2. Retrieve one review by ID
@router.get("/{review_id}", response_model=ReviewResponse)
def get_review_by_id(
    review_id: int,
    db: Session = Depends(get_db),
):

    review = (
        db.query(Review)
        .options(
            selectinload(Review.files),
            selectinload(Review.issues),
        )
        .filter(Review.id == review_id)
        .first()
    )

    if review is None:
        raise HTTPException(
            status_code=404,
            detail="Review not found",
        )

    return review


# 3. Retrieve reviews for a Pull Request
@router.get(
    "/pull-request/{pr_number}",
    response_model=list[PullRequestReviewResponse],
)
def get_reviews_by_pull_request(
    pr_number: int,
    db: Session = Depends(get_db),
):

    pull_request = (
        db.query(PullRequest)
        .options(
            selectinload(PullRequest.reviews).selectinload(Review.files),
            selectinload(PullRequest.reviews).selectinload(Review.issues),
        )
        .filter(PullRequest.github_pr_number == pr_number)
        .first()
    )

    if pull_request is None:
        raise HTTPException(
            status_code=404,
            detail="Pull Request not found",
        )

    return [pull_request]
