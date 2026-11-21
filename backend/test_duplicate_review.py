from unittest.mock import MagicMock

from app.database.models import Review
from app.services.review_storage_service import save_review_results


def test_duplicate_review_is_not_created():
    db = MagicMock()

    repository = MagicMock()
    repository.id = 1

    pull_request = MagicMock()
    pull_request.id = 10

    existing_review = MagicMock()
    existing_review.id = 25
    existing_review.overall_status = "issues_found"

    db.query.return_value.filter.return_value.first.side_effect = [
        repository,
        pull_request,
        existing_review
    ]

    result = save_review_results(
        db=db,
        github_repo_id=123,
        repository_name="demo",
        repository_full_name="user/demo",
        repository_url="https://github.com/user/demo",
        pr_number=1,
        pr_title="Test PR",
        pr_description=None,
        pr_status="open",
        commit_sha="abc123",
        review_results=[]
    )

    assert result["duplicate"] is True
    assert result["review_id"] == 25
    db.add.assert_not_called()
    db.commit.assert_called_once()