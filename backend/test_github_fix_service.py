
import pytest

from app.github.github_fix_service import validate_repository_file_path


def test_valid_python_file_path():
    result = validate_repository_file_path("src/division.py")
    assert result == "src/division.py"

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.github import github_service


def test_post_github_review_comment_success(monkeypatch):
    # Mock GitHub objects
    github = MagicMock()
    repository = MagicMock()
    pull_request = MagicMock()
    commit = MagicMock()

    review_comment = SimpleNamespace(
        id=12345,
        path="division.py",
        line=2,
        html_url="https://github.com/example/repo/pull/1#discussion_r12345"
    )

    # Configure mock responses
    github.get_repo.return_value = repository
    repository.get_pull.return_value = pull_request
    repository.get_commit.return_value = commit

    pull_request.head.sha = "test_commit_sha"
    pull_request.create_review_comment.return_value = review_comment

    # Replace real GitHub client with mock
    monkeypatch.setattr(
        github_service,
        "get_installation_github_client",
        lambda installation_id: github
    )

    # Execute function
    result = github_service.post_github_review_comment(
        repository_full_name="example/repo",
        pr_number=1,
        installation_id=100,
        commit_sha="test_commit_sha",
        file_path="division.py",
        line_number=2,
        comment_body="AI Review: Raise ValueError instead of returning a string."
    )

    # Verify result
    assert result["status"] == "success"
    assert result["comment_id"] == 12345
    assert result["file_path"] == "division.py"
    assert result["line_number"] == 2

    # Verify GitHub API arguments
    pull_request.create_review_comment.assert_called_once_with(
        body="AI Review: Raise ValueError instead of returning a string.",
        commit=commit,
        path="division.py",
        line=2,
        side="RIGHT"
    )

    github.close.assert_called_once()


def test_post_github_review_comment_rejects_old_commit(monkeypatch):
    github = MagicMock()
    repository = MagicMock()
    pull_request = MagicMock()

    github.get_repo.return_value = repository
    repository.get_pull.return_value = pull_request

    pull_request.head.sha = "new_commit_sha"

    monkeypatch.setattr(
        github_service,
        "get_installation_github_client",
        lambda installation_id: github
    )

    with pytest.raises(ValueError, match="newer commit"):
        github_service.post_github_review_comment(
            repository_full_name="example/repo",
            pr_number=1,
            installation_id=100,
            commit_sha="old_commit_sha",
            file_path="division.py",
            line_number=2,
            comment_body="Test review comment"
        )

    # No comment should be posted for an old commit
    pull_request.create_review_comment.assert_not_called()

    github.close.assert_called_once()
