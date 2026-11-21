
from unittest.mock import MagicMock, patch

import pytest

from app.github.github_fix_service import create_fix_pull_request


@patch("app.github.github_fix_service.get_github_client")
def test_closed_pull_request_is_rejected(mock_get_github_client):
    github = MagicMock()
    mock_get_github_client.return_value = github

    repository = MagicMock()
    github.get_repo.return_value = repository

    original_pr = MagicMock()
    original_pr.state = "closed"
    repository.get_pull.return_value = original_pr

    with pytest.raises(ValueError, match="not open"):
        create_fix_pull_request(
            repository_full_name="owner/repo",
            original_pr_number=1,
            filename="src/main.py",
            fixed_code="print('fixed')",
            changes_summary="Fixed code issue",
        )

    repository.create_git_ref.assert_not_called()
    github.close.assert_called_once()

@patch("app.github.github_fix_service.get_github_client")
def test_cross_repository_pull_request_is_rejected(mock_get_github_client):
    github = MagicMock()
    mock_get_github_client.return_value = github

    repository = MagicMock()
    repository.full_name = "owner/repo"
    github.get_repo.return_value = repository

    original_pr = MagicMock()
    original_pr.state = "open"
    original_pr.head.repo.full_name = "another-owner/another-repo"
    original_pr.head.ref = "feature-branch"
    original_pr.head.sha = "abc123"

    repository.get_pull.return_value = original_pr

    with pytest.raises(ValueError, match="Cross-repository"):
        create_fix_pull_request(
            repository_full_name="owner/repo",
            original_pr_number=1,
            filename="src/main.py",
            fixed_code="print('fixed')",
            changes_summary="Fixed code issue",
        )

    repository.create_git_ref.assert_not_called()
    github.close.assert_called_once()

@patch("app.github.github_fix_service.get_github_client")
def test_ai_branch_is_deleted_when_publishing_fails(mock_get_github_client):
    github = MagicMock()
    mock_get_github_client.return_value = github

    repository = MagicMock()
    repository.full_name = "owner/repo"
    github.get_repo.return_value = repository

    original_pr = MagicMock()
    original_pr.state = "open"
    original_pr.head.repo.full_name = "owner/repo"
    original_pr.head.ref = "feature-branch"
    original_pr.head.sha = "abc123"

    repository.get_pull.side_effect = [
        original_pr,
        Exception("GitHub API failure"),
    ]

    repository.get_contents.return_value = MagicMock(
        sha="file123",
        size=10,
    )

    repository.update_file.side_effect = Exception(
        "Unable to update file"
    )

    with pytest.raises(Exception, match="Unable to update file"):
        create_fix_pull_request(
            repository_full_name="owner/repo",
            original_pr_number=1,
            filename="src/main.py",
            fixed_code="print('fixed')",
            changes_summary="Fixed code issue",
        )

    repository.get_git_ref.assert_called_once()
    repository.get_git_ref.return_value.delete.assert_called_once()
    github.close.assert_called_once()

@patch("app.github.github_fix_service.get_github_client")
def test_successful_ai_fix_pull_request_creation(mock_get_github_client):
    github = MagicMock()
    mock_get_github_client.return_value = github

    repository = MagicMock()
    repository.full_name = "owner/repo"
    github.get_repo.return_value = repository

    original_pr = MagicMock()
    original_pr.state = "open"
    original_pr.head.repo.full_name = "owner/repo"
    original_pr.head.ref = "feature-branch"
    original_pr.head.sha = "abc123"

    repository.get_pull.return_value = original_pr

    existing_file = MagicMock()
    existing_file.sha = "file123"
    repository.get_contents.return_value = existing_file

    fix_pr = MagicMock()
    fix_pr.number = 25
    fix_pr.html_url = "https://github.com/owner/repo/pull/25"
    repository.create_pull.return_value = fix_pr

    result = create_fix_pull_request(
        repository_full_name="owner/repo",
        original_pr_number=1,
        filename="src/main.py",
        fixed_code="print('fixed')",
        changes_summary="Fixed code issue",
    )

    assert result["status"] == "success"
    assert result["fix_pr_number"] == 25
    assert result["fix_pr_url"] == "https://github.com/owner/repo/pull/25"

    repository.create_git_ref.assert_called_once()
    repository.update_file.assert_called_once()
    repository.create_pull.assert_called_once()

    assert repository.create_pull.call_args.kwargs["base"] == "feature-branch"

    github.close.assert_called_once()
