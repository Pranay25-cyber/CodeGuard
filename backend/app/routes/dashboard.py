from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.database.connection import get_db
from app.database.models import (
    Repository,
    PullRequest,
    Review,
    ReviewIssue,
    FixProposal,
    WebhookEvent,
)
from app.github.github_service import get_pull_request_counts

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
)


@router.get("/summary")
def get_dashboard_summary(db: Session = Depends(get_db)):
    """Return read-only dashboard statistics and recent activity."""

    repository_count = db.query(func.count(Repository.id)).scalar() or 0
    review_count = db.query(func.count(Review.id)).scalar() or 0
    issue_count = db.query(func.count(ReviewIssue.id)).scalar() or 0
    fix_count = db.query(func.count(FixProposal.id)).scalar() or 0

    # Retrieve repositories that have a GitHub App installation.
    # Copy scalar values before worker threads use them; SQLAlchemy
    # sessions and ORM objects are not shared across worker threads.
    repositories_for_live_counts = (
        db.query(
            Repository.full_name,
            Repository.installation_id,
        )
        .filter(Repository.installation_id.isnot(None))
        .all()
    )

    repository_items = [
        (full_name, installation_id)
        for full_name, installation_id in repositories_for_live_counts
    ]

    def fetch_repository_counts(item):
        full_name, installation_id = item
        try:
            counts = get_pull_request_counts(
                repository_full_name=full_name,
                installation_id=installation_id,
            )
            return {
                "open_count": int(counts["open_count"]),
                "closed_count": int(counts["closed_count"]),
                "error": None,
            }
        except Exception as error:
            print(
                "Dashboard Pull Request count failed for "
                f"{full_name}: {error!r}"
            )
            return {
                "open_count": 0,
                "closed_count": 0,
                "error": full_name,
            }

    if repository_items:
        with ThreadPoolExecutor(
            max_workers=min(8, len(repository_items))
        ) as executor:
            repository_pr_counts = list(
                executor.map(fetch_repository_counts, repository_items)
            )
    else:
        repository_pr_counts = []

    open_pull_request_count = sum(
        item["open_count"] for item in repository_pr_counts
    )
    closed_pull_request_count = sum(
        item["closed_count"] for item in repository_pr_counts
    )
    pull_request_count = (
        open_pull_request_count + closed_pull_request_count
    )
    pull_request_count_errors = [
        item["error"]
        for item in repository_pr_counts
        if item["error"] is not None
    ]

    # Count issues by their source: AI, Ruff, Bandit, etc.
    issue_sources = (
        db.query(ReviewIssue.source, func.count(ReviewIssue.id))
        .group_by(ReviewIssue.source)
        .all()
    )

    # Count fix proposals by status.
    fix_statuses = (
        db.query(FixProposal.status, func.count(FixProposal.id))
        .group_by(FixProposal.status)
        .all()
    )

    # Count webhook events by processing status.
    webhook_statuses = (
        db.query(WebhookEvent.status, func.count(WebhookEvent.id))
        .group_by(WebhookEvent.status)
        .all()
    )

    # Retrieve recent reviews with their pull request and repository.
    recent_reviews = (
        db.query(Review)
        .options(
            joinedload(Review.pull_request).joinedload(PullRequest.repository),
            joinedload(Review.issues),
        )
        .order_by(Review.created_at.desc())
        .limit(8)
        .all()
    )

    recent_review_data = []

    for review in recent_reviews:
        pull_request = review.pull_request
        repository = pull_request.repository

        recent_review_data.append({
            "id": review.id,
            "repository": repository.full_name,
            "repository_url": repository.html_url,
            "pull_request_number": pull_request.github_pr_number,
            "pull_request_title": pull_request.title,
            "commit_sha": review.commit_sha,
            "summary": review.summary,
            "status": review.overall_status,
            "created_at": review.created_at,
            "issue_count": len(review.issues),
            "issues": [
                {
                    "id": issue.id,
                    "file_path": issue.file_path,
                    "line_number": issue.line_number,
                    "issue_type": issue.issue_type,
                    "severity": issue.severity,
                    "description": issue.description,
                    "source": issue.source,
                }
                for issue in review.issues
            ],
        })

    # Retrieve recent pull requests from the local review database.
    recent_pull_requests = (
        db.query(PullRequest)
        .options(joinedload(PullRequest.repository))
        .order_by(PullRequest.created_at.desc())
        .limit(8)
        .all()
    )

    recent_pr_data = [
        {
            "id": pr.id,
            "number": pr.github_pr_number,
            "title": pr.title,
            "description": pr.description,
            "status": pr.status,
            "head_sha": pr.head_sha,
            "repository": pr.repository.full_name,
            "created_at": pr.created_at,
        }
        for pr in recent_pull_requests
    ]

    # Expose proposal metadata only. Never return source code here.
    recent_fixes = (
        db.query(FixProposal)
        .order_by(FixProposal.created_at.desc())
        .limit(8)
        .all()
    )

    recent_fix_data = [
        {
            "id": fix.id,
            "repository": fix.repository_full_name,
            "pull_request_number": fix.original_pr_number,
            "filename": fix.filename,
            "summary": fix.changes_summary,
            "status": fix.status,
            "created_at": fix.created_at,
            "published_at": fix.published_at,
        }
        for fix in recent_fixes
    ]

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "statistics": {
            "repositories": repository_count,
            "pull_requests": pull_request_count,
            "open_pull_requests": open_pull_request_count,
            "closed_pull_requests": closed_pull_request_count,
            "pull_request_count_errors": pull_request_count_errors,
            "reviews": review_count,
            "issues": issue_count,
            "fix_proposals": fix_count,
        },
        "issue_sources": {
            str(source or "unknown"): count
            for source, count in issue_sources
        },
        "fix_statuses": {
            str(status): count
            for status, count in fix_statuses
        },
        "webhook_statuses": {
            str(status): count
            for status, count in webhook_statuses
        },
        "recent_reviews": recent_review_data,
        "recent_pull_requests": recent_pr_data,
        "recent_fixes": recent_fix_data,
    }
