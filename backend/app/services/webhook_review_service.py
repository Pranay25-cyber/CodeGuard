
import time
import logging
import hashlib

from anthropic import (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    InternalServerError,
    AuthenticationError,
    PermissionDeniedError,
)

from github import GithubException

from app.database.connection import SessionLocal
from app.database.models import WebhookEvent

from app.github.github_service import (
    get_webhook_pull_request_details,
    get_webhook_pull_request_file_content,
    get_installation_github_client,
    post_github_review_comment,
)

from app.services.issue_verification_service import (
    verify_review_issues,
    match_issues_to_added_lines,
)

from app.services.static_analyzer import analyze_python_code
from app.services.ai_review_service import review_python_code
from app.services.review_storage_service import save_review_results
from app.services.diff_analyzer import analyze_changed_files


logger = logging.getLogger(__name__)

MAX_REVIEW_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2


# --------------------------------------------------
# 1. GitHub comment identity and formatting
# --------------------------------------------------

def build_comment_marker(commit_sha: str, candidate: dict) -> str:
    """
    Build a stable marker for one finding on one commit.

    The marker allows us to detect comments already posted
    when a webhook is delivered again or a retry occurs.
    """

    identity = "|".join([
        commit_sha,
        str(candidate.get("file_path", "")),
        str(candidate.get("line_number", "")),
        str(candidate.get("issue_type", "general")).strip().lower(),
        str(candidate.get("title", "")).strip().casefold(),
    ])

    fingerprint = hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()

    return f"<!-- ai-code-review-agent:{fingerprint} -->"


def format_github_comment(candidate: dict, marker: str) -> str:
    """Format an AI finding as a GitHub inline review comment."""

    severity = str(
        candidate.get("severity") or "medium"
    ).upper()

    title = candidate.get("title") or "Potential code issue"
    description = candidate.get("description") or (
        "The AI reviewer identified a potential issue."
    )
    suggestion = candidate.get("suggestion")

    body = (
        f"### AI Code Review — {severity}\n\n"
        f"**{title}**\n\n"
        f"{description}"
    )

    if suggestion:
        body += f"\n\n**Suggested fix:**\n{suggestion}"

    body += f"\n\n{marker}"

    return body


# --------------------------------------------------
# 2. Publish GitHub inline review comments
# --------------------------------------------------

def publish_github_review_comments(
    repository_full_name: str,
    pr_number: int,
    installation_id: int,
    commit_sha: str,
    candidates: list,
):
    """
    Publish verified AI findings as GitHub inline comments.

    Existing comments with the same marker are skipped.
    This supports normal webhook redelivery and recovery
    after a partial publishing failure.
    """

    if not candidates:
        return {
            "status": "success",
            "total_candidates": 0,
            "posted": 0,
            "skipped_duplicates": 0,
            "skipped_invalid": 0,
        }

    # --------------------------------------------------
    # Confirm that the PR still points to this commit.
    # Also retrieve existing review comments.
    # --------------------------------------------------

    github = get_installation_github_client(installation_id)

    try:
        repository = github.get_repo(repository_full_name)
        pull_request = repository.get_pull(pr_number)

        latest_commit_sha = pull_request.head.sha

        if latest_commit_sha != commit_sha:
            raise ValueError(
                "The pull request has a newer commit. "
                "Comments for the older commit will not be published."
            )

        existing_comment_bodies = [
            comment.body or ""
            for comment in pull_request.get_review_comments()
        ]

    finally:
        github.close()

    posted = 0
    skipped_duplicates = 0
    skipped_invalid = 0

    # Keep markers updated during this publishing run.
    # This also prevents duplicate candidates in the same batch.
    known_comment_bodies = list(existing_comment_bodies)

    # --------------------------------------------------
    # Publish each candidate
    # --------------------------------------------------

    for candidate in candidates:

        if not isinstance(candidate, dict):
            skipped_invalid += 1
            continue

        file_path = candidate.get("file_path")
        line_number = candidate.get("line_number")

        if (
            not isinstance(file_path, str)
            or not file_path.strip()
            or not isinstance(line_number, int)
            or isinstance(line_number, bool)
            or line_number < 1
        ):
            skipped_invalid += 1
            continue

        marker = build_comment_marker(
            commit_sha,
            candidate
        )

        # Check whether this finding was already published.
        if any(
            marker in body
            for body in known_comment_bodies
        ):
            skipped_duplicates += 1

            logger.info(
                "Skipping existing GitHub comment: %s line %s",
                file_path,
                line_number,
            )
            continue

        comment_body = format_github_comment(
            candidate,
            marker
        )

        # The existing GitHub service function checks the
        # latest commit again before creating the comment.
        result = post_github_review_comment(
            repository_full_name=repository_full_name,
            pr_number=pr_number,
            installation_id=installation_id,
            commit_sha=commit_sha,
            file_path=file_path,
            line_number=line_number,
            comment_body=comment_body,
        )

        if not isinstance(result, dict) or result.get("status") != "success":
            raise RuntimeError(
                "GitHub review comment publishing did not succeed."
            )

        posted += 1
        known_comment_bodies.append(comment_body)

        logger.info(
            "GitHub inline comment posted: %s line %s",
            file_path,
            line_number,
        )

    return {
        "status": "success",
        "total_candidates": len(candidates),
        "posted": posted,
        "skipped_duplicates": skipped_duplicates,
        "skipped_invalid": skipped_invalid,
    }


# --------------------------------------------------
# 3. Process Pull Request Review
# --------------------------------------------------

def process_pull_request_review(
    repository_full_name: str,
    pr_number: int,
    installation_id: int
):
    """Review a GitHub PR, save results, and publish comments."""

    db = SessionLocal()

    try:
        logger.info(
            "Starting automatic review: %s PR #%s",
            repository_full_name,
            pr_number
        )

        pr_data = get_webhook_pull_request_details(
            repository_full_name=repository_full_name,
            pr_number=pr_number,
            installation_id=installation_id
        )

        if pr_data["state"] != "open":
            logger.info(
                "Skipping review because PR #%s is not open.",
                pr_number
            )
            return None

        # Analyze changed files and GitHub diff information.
        diff_analysis = analyze_changed_files(
            pr_data["changed_files"]
        )

        logger.info(
            "Diff analysis completed: %s files, %s additions, %s deletions.",
            diff_analysis["total_files"],
            diff_analysis["total_additions"],
            diff_analysis["total_deletions"]
        )

        review_results = []
        github_comment_candidates = []

        # Review each changed Python file.
        for file in pr_data["changed_files"]:

            filename = file["filename"]

            if not filename.endswith(".py"):
                continue

            if file["status"] == "removed":
                continue

            logger.info("Reviewing file: %s", filename)

            code = get_webhook_pull_request_file_content(
                repository_full_name=repository_full_name,
                pr_number=pr_number,
                file_path=filename,
                installation_id=installation_id
            )

            static_analysis = analyze_python_code(code)

            ai_review = review_python_code(
                code=code,
                filename=filename,
                static_analysis=static_analysis
            )

            verification_results = verify_review_issues(
                issues=ai_review["issues"],
                code=code
            )

            file_diff = next(
                (
                    item
                    for item in diff_analysis["files"]
                    if item["filename"] == filename
                ),
                None
            )

            file_comment_candidates = match_issues_to_added_lines(
                issues=ai_review["issues"],
                verification_results=verification_results,
                file_diff=file_diff
            )

            github_comment_candidates.extend(
                file_comment_candidates
            )

            logger.info(
                "Prepared %s GitHub comment candidates for %s.",
                len(file_comment_candidates),
                filename
            )

            review_results.append({
                "filename": filename,
                "diff_analysis": file_diff,
                "static_analysis": static_analysis,
                "ai_review": ai_review,
                "verification_results": verification_results,
                "github_comment_candidates": file_comment_candidates
            })

        # --------------------------------------------------
        # Save review results in PostgreSQL first.
        # --------------------------------------------------

        database_result = save_review_results(
            db=db,
            github_repo_id=pr_data["repository_id"],
            repository_name=pr_data["repository_name"],
            repository_full_name=pr_data["repository_full_name"],
            repository_url=pr_data["repository_url"],
            pr_number=pr_data["pull_request_number"],
            pr_title=pr_data["title"],
            pr_description=pr_data["description"],
            pr_status=pr_data["state"],
            commit_sha=pr_data["head_sha"],
            review_results=review_results,
            diff_analysis=diff_analysis,
            installation_id=installation_id
        )

        if database_result is None:
            return None

        database_result["github_comment_candidates"] = (
            github_comment_candidates
        )

        # --------------------------------------------------
        # Publish comments only after database persistence.
        # --------------------------------------------------
        #
        # Do not skip publishing just because database_result
        # says duplicate=True. A previous attempt may have
        # saved the review but failed while posting comments.
        # The marker check safely skips comments already posted.
        # --------------------------------------------------

        comment_result = publish_github_review_comments(
            repository_full_name=repository_full_name,
            pr_number=pr_number,
            installation_id=installation_id,
            commit_sha=pr_data["head_sha"],
            candidates=github_comment_candidates,
        )

        database_result["github_comments"] = comment_result

        logger.info(
            "Review completed for PR #%s. "
            "Candidates: %s, posted: %s, duplicates skipped: %s.",
            pr_number,
            comment_result["total_candidates"],
            comment_result["posted"],
            comment_result["skipped_duplicates"],
        )

        return database_result

    except Exception:
        db.rollback()

        logger.exception(
            "Automatic Pull Request review failed for %s PR #%s.",
            repository_full_name,
            pr_number
        )

        raise

    finally:
        db.close()


# --------------------------------------------------
# 4. Update Webhook Event Status
# --------------------------------------------------

def update_webhook_event_status(
    event_id: int,
    status: str
):
    """Update the status of a GitHub webhook event."""

    db = SessionLocal()

    try:
        event = (
            db.query(WebhookEvent)
            .filter(WebhookEvent.id == event_id)
            .first()
        )

        if event is None:
            raise ValueError(
                f"Webhook event {event_id} was not found"
            )

        event.status = status
        db.commit()

        logger.info(
            "Webhook event %s status updated to %s.",
            event_id,
            status
        )

    except Exception:
        db.rollback()

        logger.exception(
            "Failed to update webhook event %s status.",
            event_id
        )

        raise

    finally:
        db.close()


# --------------------------------------------------
# 5. Identify Retryable Errors
# --------------------------------------------------

def is_retryable_error(error: Exception) -> bool:
    """Identify temporary errors that may succeed on retry."""

    if isinstance(
        error,
        (
            APIConnectionError,
            APITimeoutError,
            RateLimitError,
            InternalServerError,
        )
    ):
        return True

    if isinstance(error, GithubException):

        status_code = getattr(error, "status", None)

        if status_code == 429:
            return True

        if isinstance(status_code, int) and status_code >= 500:
            return True

        return False

    return False


# --------------------------------------------------
# 6. Process Review With Retry
# --------------------------------------------------

def process_tracked_pull_request_review(
    event_id: int,
    repository_full_name: str,
    pr_number: int,
    installation_id: int
):
    """Process a PR review with retries and status tracking."""

    update_webhook_event_status(
        event_id,
        "processing"
    )

    try:

        for attempt in range(1, MAX_REVIEW_ATTEMPTS + 1):

            try:
                logger.info(
                    "Review attempt %s/%s for event %s.",
                    attempt,
                    MAX_REVIEW_ATTEMPTS,
                    event_id
                )

                result = process_pull_request_review(
                    repository_full_name=repository_full_name,
                    pr_number=pr_number,
                    installation_id=installation_id
                )

                update_webhook_event_status(
                    event_id,
                    "completed"
                )

                logger.info(
                    "Webhook event %s completed successfully.",
                    event_id
                )

                return result

            except Exception as error:

                logger.warning(
                    "Review attempt %s failed for event %s: %s",
                    attempt,
                    event_id,
                    repr(error)
                )

                if isinstance(
                    error,
                    (
                        AuthenticationError,
                        PermissionDeniedError,
                    )
                ):
                    raise

                if not is_retryable_error(error):
                    raise

                if attempt == MAX_REVIEW_ATTEMPTS:
                    logger.error(
                        "Maximum retry attempts reached for event %s.",
                        event_id
                    )
                    raise

                delay = RETRY_DELAY_SECONDS * (2 ** (attempt - 1))

                logger.warning(
                    "Temporary error. Retrying event %s in %s seconds.",
                    event_id,
                    delay
                )

                time.sleep(delay)

    except Exception:
        try:
            update_webhook_event_status(
                event_id,
                "failed"
            )

        except Exception:
            logger.exception(
                "Unable to update webhook event %s to failed status.",
                event_id
            )

        logger.exception(
            "Tracked review failed for event %s.",
            event_id
        )

        raise
