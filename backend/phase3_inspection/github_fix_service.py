
from datetime import datetime, timezone
from pathlib import PurePosixPath
from uuid import uuid4

from github import GithubException

from app.github.github_service import get_github_client


def validate_repository_file_path(filename: str) -> str:
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("Filename cannot be empty")

    filename = filename.strip()

    if (
        "\x00" in filename
        or "\\" in filename
        or ":" in filename
        or filename.startswith("/")
        or filename.endswith("/")
        or any(ord(char) < 32 for char in filename)
    ):
        raise ValueError("Invalid file path")

    path = PurePosixPath(filename)

    if path.is_absolute() or ".." in path.parts or not path.name:
        raise ValueError("Invalid file path")

    return str(path)


def create_fix_pull_request(
    repository_full_name: str,
    original_pr_number: int,
    filename: str,
    fixed_code: str,
    changes_summary: str,
):
    if (
        not isinstance(repository_full_name, str)
        or repository_full_name.count("/") != 1
        or any(not part.strip() for part in repository_full_name.split("/"))
        or repository_full_name != repository_full_name.strip()
    ):
        raise ValueError("Invalid GitHub repository name")

    if (
        isinstance(original_pr_number, bool)
        or not isinstance(original_pr_number, int)
        or original_pr_number <= 0
    ):
        raise ValueError("Invalid Pull Request number")

    if not isinstance(fixed_code, str) or not fixed_code.strip():
        raise ValueError("Fixed code cannot be empty")

    if not isinstance(changes_summary, str) or not changes_summary.strip():
        raise ValueError("Changes summary cannot be empty")

    filename = validate_repository_file_path(filename)

    github = get_github_client()

    branch_created = False
    fix_pr_created = False
    fix_branch_name = None

    try:
        repository = github.get_repo(repository_full_name)

        original_pr = repository.get_pull(original_pr_number)

        if original_pr.state != "open":
            raise ValueError("Original Pull Request is not open")

        if original_pr.head.repo is None:
            raise ValueError("Pull Request source repository is unavailable")

        if (
            original_pr.head.repo.full_name.lower()
            != repository.full_name.lower()
        ):
            raise ValueError("Cross-repository Pull Requests are not supported")

        source_branch = original_pr.head.ref
        source_sha = original_pr.head.sha

        if not source_branch or not source_sha:
            raise ValueError("Pull Request source branch or SHA is missing")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        fix_branch_name = (
            f"ai-fix/pr-{original_pr_number}-{timestamp}-{uuid4().hex[:8]}"
        )

        repository.create_git_ref(
            ref=f"refs/heads/{fix_branch_name}",
            sha=source_sha,
        )

        branch_created = True

        commit_message = (
            f"AI fix: {changes_summary[:100]}"
        )

        try:
            existing_file = repository.get_contents(
                filename,
                ref=fix_branch_name,
            )

            if isinstance(existing_file, list):
                raise ValueError("The specified path is a directory")

            repository.update_file(
                path=filename,
                message=commit_message,
                content=fixed_code,
                sha=existing_file.sha,
                branch=fix_branch_name,
            )

        except GithubException as error:
            if error.status != 404:
                raise

            repository.create_file(
                path=filename,
                message=commit_message,
                content=fixed_code,
                branch=fix_branch_name,
            )

        # Confirm the original PR has not changed during fix generation.
        refreshed_pr = repository.get_pull(original_pr_number)

        if refreshed_pr.state != "open":
            raise ValueError("Original Pull Request was closed during processing")

        if refreshed_pr.head.sha != source_sha:
            raise ValueError(
                "Original Pull Request changed during processing. "
                "The AI fix was not published."
            )

        fix_pr = repository.create_pull(
            title=f"AI Fix for PR #{original_pr_number}",
            body=(
                "## Automated AI Code Fix\n\n"
                f"Original Pull Request: #{original_pr_number}\n\n"
                f"**Changes:** {changes_summary}\n\n"
                "This Pull Request contains an automatically generated "
                "fix for developer review.\n"
            ),
            head=fix_branch_name,
            base=source_branch,
        )

        fix_pr_created = True

        return {
            "status": "success",
            "message": "AI fix Pull Request created successfully",
            "original_pr_number": original_pr_number,
            "fix_branch": fix_branch_name,
            "fix_pr_number": fix_pr.number,
            "fix_pr_url": fix_pr.html_url,
        }

    except Exception:
        if branch_created and not fix_pr_created:
            try:
                repository.get_git_ref(
                    f"heads/{fix_branch_name}"
                ).delete()

            except Exception as cleanup_error:
                print(
                    "Warning: Could not clean up AI fix branch:",
                    cleanup_error,
                )

        raise

    finally:
        try:
            github.close()
        except Exception as close_error:
            print("Warning: Could not close GitHub client:", close_error)
