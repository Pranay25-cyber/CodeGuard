
from types import SimpleNamespace

import httpx
import pytest

from github import GithubException

from anthropic import (
    AuthenticationError,
    PermissionDeniedError,
)

import app.services.webhook_review_service as webhook_service


# --------------------------------------------------
# Fake GitHub objects for unit tests
# --------------------------------------------------

COMMIT_SHA = "a" * 40


class FakePullRequest:
    def __init__(self, commit_sha=COMMIT_SHA, comments=None):
        self.head = SimpleNamespace(sha=commit_sha)
        self.comments = comments or []

    def get_review_comments(self):
        return iter(self.comments)


class FakeRepository:
    def __init__(self, pull_request):
        self.pull_request = pull_request

    def get_pull(self, pr_number):
        return self.pull_request


class FakeGithub:
    def __init__(self, pull_request):
        self.repository = FakeRepository(pull_request)
        self.closed = False

    def get_repo(self, repository_full_name):
        return self.repository

    def close(self):
        self.closed = True


# --------------------------------------------------
# Test data
# --------------------------------------------------

CANDIDATE = {
    "file_path": "division.py",
    "line_number": 2,
    "severity": "high",
    "issue_type": "bug",
    "title": "Possible division by zero",
    "description": "The denominator may be zero.",
    "suggestion": "Check the denominator before division.",
    "source_line": "return a / b",
}


# --------------------------------------------------
# 1. GitHub retryable error tests
# --------------------------------------------------

def test_github_rate_limit_error_is_retryable():
    error = GithubException(
        status=429,
        data={"message": "API rate limit exceeded"},
    )

    assert webhook_service.is_retryable_error(error) is True


def test_github_server_error_is_retryable():
    error = GithubException(
        status=500,
        data={"message": "Internal server error"},
    )

    assert webhook_service.is_retryable_error(error) is True


# --------------------------------------------------
# 2. GitHub non-retryable error tests
# --------------------------------------------------

def test_github_bad_request_is_not_retryable():
    error = GithubException(
        status=400,
        data={"message": "Bad request"},
    )

    assert webhook_service.is_retryable_error(error) is False


# --------------------------------------------------
# 3. Anthropic authentication error test
# --------------------------------------------------

def test_authentication_error_is_not_retryable():
    request = httpx.Request(
        "POST",
        "https://api.anthropic.com/v1/messages",
    )

    response = httpx.Response(
        401,
        request=request,
    )

    error = AuthenticationError(
        message="Invalid API key",
        response=response,
        body={"message": "Invalid API key"},
    )

    assert webhook_service.is_retryable_error(error) is False


# --------------------------------------------------
# 4. Anthropic permission error test
# --------------------------------------------------

def test_permission_error_is_not_retryable():
    request = httpx.Request(
        "POST",
        "https://api.anthropic.com/v1/messages",
    )

    response = httpx.Response(
        403,
        request=request,
    )

    error = PermissionDeniedError(
        message="Permission denied",
        response=response,
        body={"message": "Permission denied"},
    )

    assert webhook_service.is_retryable_error(error) is False


# --------------------------------------------------
# 5. Unexpected error test
# --------------------------------------------------

def test_unexpected_error_is_not_retryable():
    error = ValueError("Unexpected error")

    assert webhook_service.is_retryable_error(error) is False


# --------------------------------------------------
# 6. GitHub comment publishing tests
# --------------------------------------------------

def test_publish_github_comment_success(monkeypatch):
    pull_request = FakePullRequest()
    fake_github = FakeGithub(pull_request)

    monkeypatch.setattr(
        webhook_service,
        "get_installation_github_client",
        lambda installation_id: fake_github,
    )

    posted_comments = []

    def fake_post_comment(**kwargs):
        posted_comments.append(kwargs)

        pull_request.comments.append(
            SimpleNamespace(body=kwargs["comment_body"])
        )

        return {"status": "success"}

    monkeypatch.setattr(
        webhook_service,
        "post_github_review_comment",
        fake_post_comment,
    )

    result = webhook_service.publish_github_review_comments(
        repository_full_name="owner/repository",
        pr_number=1,
        installation_id=123,
        commit_sha=COMMIT_SHA,
        candidates=[CANDIDATE],
    )

    assert result["status"] == "success"
    assert result["posted"] == 1
    assert result["skipped_duplicates"] == 0
    assert len(posted_comments) == 1
    assert posted_comments[0]["file_path"] == "division.py"
    assert posted_comments[0]["line_number"] == 2
    assert "Possible division by zero" in posted_comments[0]["comment_body"]
    assert "<!-- ai-code-review-agent:" in posted_comments[0]["comment_body"]
    assert fake_github.closed is True


def test_existing_github_comment_is_not_posted_again(monkeypatch):
    marker = webhook_service.build_comment_marker(
        COMMIT_SHA,
        CANDIDATE,
    )

    pull_request = FakePullRequest(
        comments=[
            SimpleNamespace(body=f"Existing comment\n{marker}")
        ]
    )

    fake_github = FakeGithub(pull_request)

    monkeypatch.setattr(
        webhook_service,
        "get_installation_github_client",
        lambda installation_id: fake_github,
    )

    def unexpected_post(**kwargs):
        pytest.fail("Duplicate comment should not be posted")

    monkeypatch.setattr(
        webhook_service,
        "post_github_review_comment",
        unexpected_post,
    )

    result = webhook_service.publish_github_review_comments(
        repository_full_name="owner/repository",
        pr_number=1,
        installation_id=123,
        commit_sha=COMMIT_SHA,
        candidates=[CANDIDATE],
    )

    assert result["posted"] == 0
    assert result["skipped_duplicates"] == 1


def test_outdated_commit_is_rejected(monkeypatch):
    pull_request = FakePullRequest(
        commit_sha="b" * 40
    )

    fake_github = FakeGithub(pull_request)

    monkeypatch.setattr(
        webhook_service,
        "get_installation_github_client",
        lambda installation_id: fake_github,
    )

    with pytest.raises(ValueError, match="newer commit"):
        webhook_service.publish_github_review_comments(
            repository_full_name="owner/repository",
            pr_number=1,
            installation_id=123,
            commit_sha=COMMIT_SHA,
            candidates=[CANDIDATE],
        )

    assert fake_github.closed is True


def test_empty_candidates_do_not_call_github(monkeypatch):
    def unexpected_client(installation_id):
        pytest.fail("GitHub client should not be created")

    monkeypatch.setattr(
        webhook_service,
        "get_installation_github_client",
        unexpected_client,
    )

    result = webhook_service.publish_github_review_comments(
        repository_full_name="owner/repository",
        pr_number=1,
        installation_id=123,
        commit_sha=COMMIT_SHA,
        candidates=[],
    )

    assert result["total_candidates"] == 0
    assert result["posted"] == 0


# --------------------------------------------------
# 7. Partial failure and retry protection
# --------------------------------------------------

def test_partial_failure_retry_does_not_duplicate_first_comment(
    monkeypatch,
):
    first_candidate = CANDIDATE.copy()

    second_candidate = {
        **CANDIDATE,
        "line_number": 5,
        "title": "Missing input validation",
        "description": "Input is not validated.",
    }

    pull_request = FakePullRequest()
    fake_github = FakeGithub(pull_request)

    monkeypatch.setattr(
        webhook_service,
        "get_installation_github_client",
        lambda installation_id: fake_github,
    )

    calls = []
    fail_second_comment_once = True

    def fake_post_comment(**kwargs):
        nonlocal fail_second_comment_once

        file_path = kwargs["file_path"]
        line_number = kwargs["line_number"]

        calls.append((file_path, line_number))

        if line_number == 5 and fail_second_comment_once:
            fail_second_comment_once = False

            raise GithubException(
                status=500,
                data={"message": "Temporary GitHub server error"},
            )

        pull_request.comments.append(
            SimpleNamespace(body=kwargs["comment_body"])
        )

        return {"status": "success"}

    monkeypatch.setattr(
        webhook_service,
        "post_github_review_comment",
        fake_post_comment,
    )

    candidates = [
        first_candidate,
        second_candidate,
    ]

    # First attempt: first comment succeeds, second fails.
    with pytest.raises(GithubException):
        webhook_service.publish_github_review_comments(
            repository_full_name="owner/repository",
            pr_number=1,
            installation_id=123,
            commit_sha=COMMIT_SHA,
            candidates=candidates,
        )

    assert calls.count(("division.py", 2)) == 1
    assert calls.count(("division.py", 5)) == 1

    # Retry: first comment must be skipped, second can succeed.
    result = webhook_service.publish_github_review_comments(
        repository_full_name="owner/repository",
        pr_number=1,
        installation_id=123,
        commit_sha=COMMIT_SHA,
        candidates=candidates,
    )

    assert result["posted"] == 1
    assert result["skipped_duplicates"] == 1

    # The first comment was never posted a second time.
    assert calls.count(("division.py", 2)) == 1

    # The second comment was retried successfully.
    assert calls.count(("division.py", 5)) == 2
