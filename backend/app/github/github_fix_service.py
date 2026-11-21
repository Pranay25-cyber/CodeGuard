
import logging
from pathlib import PurePosixPath

from github import GithubException
from github.InputGitTreeElement import InputGitTreeElement

from app.github.github_service import get_github_client


logger = logging.getLogger(__name__)


def validate_repository_file_path(filename: str) -> str:
    """Validate a repository-relative file path."""

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

    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.name
        or "." in path.parts
    ):
        raise ValueError("Invalid file path")

    return str(path)


def publish_fix_to_original_pr(
    repository_full_name: str,
    original_pr_number: int,
    filename: str,
    fixed_code: str,
    changes_summary: str,
    expected_head_sha: str,
):
    """
    Publish an approved AI fix directly to the original PR source branch.

    No new branch or pull request is created.

    The Git reference is updated without force, using the approved
    original commit as the parent. If the branch has moved, GitHub
    rejects the update instead of overwriting newer commits.
    """

    if (
        not isinstance(repository_full_name, str)
        or repository_full_name.count("/") != 1
        or any(
            not part.strip()
            for part in repository_full_name.split("/")
        )
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

    if (
        not isinstance(expected_head_sha, str)
        or not expected_head_sha.strip()
    ):
        raise ValueError("Approved original commit SHA is required")

    filename = validate_repository_file_path(filename)

    github = get_github_client()

    try:
        repository = github.get_repo(repository_full_name)
        original_pr = repository.get_pull(original_pr_number)

        if original_pr.state != "open":
            raise ValueError("Original Pull Request is not open")

        if original_pr.head.repo is None:
            raise ValueError("Pull Request source repository is unavailable")

        # This implementation supports same-repository PRs.
        # Fork PRs need a separate installation/permission strategy.
        if (
            original_pr.head.repo.full_name.lower()
            != repository.full_name.lower()
        ):
            raise ValueError(
                "This Pull Request comes from a fork. "
                "Direct publishing is not supported for this PR."
            )

        source_branch = original_pr.head.ref
        current_head_sha = original_pr.head.sha

        if not source_branch or not current_head_sha:
            raise ValueError("PR source branch or commit SHA is missing")

        # Verify the exact commit used to generate and test the proposal.
        if current_head_sha != expected_head_sha:
            raise ValueError(
                "The original Pull Request has changed since this fix "
                "was generated. Generate and validate a fresh fix."
            )

        # Confirm that the source branch itself still points to the
        # approved commit.
        branch_ref = repository.get_git_ref(
            f"heads/{source_branch}"
        )

        if branch_ref.object.sha != expected_head_sha:
            raise ValueError(
                "The source branch has changed. Publishing was blocked."
            )

        parent_commit = repository.get_git_commit(expected_head_sha)

        # Ensure the target file exists in the approved original commit.
        source_tree = repository.get_git_tree(
            parent_commit.tree.sha,
            recursive=True
        )

        matching_file = next(
            (
                item
                for item in source_tree.tree
                if item.path == filename
            ),
            None
        )

        if matching_file is None or matching_file.type != "blob":
            raise ValueError(
                "The approved file does not exist at the original commit."
            )

        if matching_file.mode not in ("100644", "100755"):
            raise ValueError(
                "The target file has an unsupported Git file mode."
            )

        # Create a Git blob containing the approved corrected code.
        new_blob = repository.create_git_blob(
            fixed_code,
            "utf-8"
        )

        # Create a new tree based on the original commit's tree.
        # Only the approved file is changed.
        new_tree = repository.create_git_tree(
            [
                InputGitTreeElement(
                    path=filename,
                    mode=matching_file.mode,
                    type="blob",
                    sha=new_blob.sha
                )
            ],
            base_tree=parent_commit.tree
        )

        commit_message = (
            f"AI fix: {changes_summary.strip()[:100]}"
        )

        # Create a commit whose parent is the exact approved commit.
        new_commit = repository.create_git_commit(
            commit_message,
            new_tree,
            [parent_commit]
        )

        # Atomic, non-force update. If another commit has moved the
        # branch since our check, GitHub rejects this update.
        branch_ref.edit(
            sha=new_commit.sha,
            force=False
        )

        # Verify the PR now points to our commit.
        refreshed_pr = repository.get_pull(original_pr_number)

        if refreshed_pr.state != "open":
            raise ValueError(
                "The original Pull Request was closed during publishing."
            )

        if refreshed_pr.head.sha != new_commit.sha:
            raise ValueError(
                "The fix commit was created, but the PR head no longer "
                "points to it. Check the source branch before retrying."
            )

        return {
            "status": "success",
            "message": (
                "Approved AI fix committed to the original "
                "Pull Request source branch."
            ),
            "repository": repository.full_name,
            "original_pr_number": original_pr_number,
            "source_branch": source_branch,
            "filename": filename,
            "previous_commit_sha": expected_head_sha,
            "new_commit_sha": new_commit.sha,
            "commit_url": new_commit.html_url,
            "pull_request_url": refreshed_pr.html_url,
            "new_pull_request_created": False,
            "new_branch_created": False
        }

    except GithubException as error:
        logger.exception(
            "GitHub rejected the approved fix for PR #%s",
            original_pr_number
        )

        if error.status == 409:
            raise ValueError(
                "The source branch changed during publishing. "
                "Generate a fresh fix before trying again."
            ) from error

        if error.status == 403:
            raise PermissionError(
                "The GitHub App does not have permission to write "
                "to this repository."
            ) from error

        raise

    finally:
        github.close()
