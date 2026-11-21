
from asyncio.log import logger
import os
from pathlib import Path

from dotenv import load_dotenv
from github import Auth, Github, GithubIntegration
import base64
from pathlib import PurePosixPath
from urllib.parse import urlparse, parse_qs

import requests

# 1. Load environment variables

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


# 2. Create GitHub App integration

def get_github_integration():

    app_id = os.getenv("GITHUB_APP_ID")
    private_key_path = os.getenv("GITHUB_PRIVATE_KEY_PATH")

    if not app_id:
        raise ValueError("GITHUB_APP_ID is missing in .env")

    if not private_key_path:
        raise ValueError("GITHUB_PRIVATE_KEY_PATH is missing in .env")

    key_path = BASE_DIR / private_key_path

    if not key_path.is_file():
        raise FileNotFoundError(
            f"GitHub private key file not found: {key_path}"
        )

    private_key = key_path.read_text(encoding="utf-8")

    return GithubIntegration(int(app_id), private_key)


# 3. Verify GitHub App authentication

def verify_github_app():

    integration = get_github_integration()
    app = integration.get_app()

    return {
        "status": "success",
        "message": "GitHub App authentication successful",
        "app_name": app.name
    }


# 4. Generate installation access token

def get_installation_token():

    installation_id = os.getenv("GITHUB_INSTALLATION_ID")

    if not installation_id:
        raise ValueError(
            "GITHUB_INSTALLATION_ID is missing in .env"
        )

    integration = get_github_integration()

    access_token = integration.get_access_token(
        int(installation_id)
    )

    return access_token.token


# 5. Get authenticated GitHub client

def get_github_client():

    token = get_installation_token()
    auth = Auth.Token(token)

    return Github(auth=auth)


# 6. Retrieve repository details

def get_repository_details():

    github = get_github_client()

    try:
        repository = github.get_repo(
            "Pranay25-cyber/newpragnaschool"
        )

        return {
            "status": "success",
            "repository": repository.full_name,
            "repository_id": repository.id,
            "name": repository.name,
            "full_name": repository.full_name,
            "html_url": repository.html_url,
            "description": repository.description,
            "default_branch": repository.default_branch,
            "private": repository.private
        }

    finally:
        github.close()


def get_repository_snapshot(
    repository_full_name: str,
    commit_sha: str,
    max_files: int = 200,
    max_file_size: int = 500_000,
    max_total_size: int = 10_000_000,
):
    """
    Retrieve safe Python source, test, and configuration files
    from a repository at an exact Git commit.
    """

    if not repository_full_name or "/" not in repository_full_name:
        raise ValueError("Repository must use owner/repository format")

    if not commit_sha:
        raise ValueError("Commit SHA is required")

    if not 1 <= max_files <= 500:
        raise ValueError("max_files must be between 1 and 500")

    if max_file_size < 1 or max_total_size < 1:
        raise ValueError("File size limits must be positive")

    ignored_directories = {
        ".git",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "site-packages",
        "dist",
        "build",
    }

    allowed_config_files = {
        "pyproject.toml",
        "pytest.ini",
        "tox.ini",
        "setup.cfg",
        "setup.py",
        "requirements.txt",
        "pipfile",
    }

    github = get_github_client()

    try:
        repository = github.get_repo(repository_full_name)

        tree = repository.get_git_tree(
            commit_sha,
            recursive=True,
        )

        snapshot_files = {}
        total_size = 0
        skipped_files = 0

        for item in tree.tree:

            if item.type != "blob":
                continue

            # Do not retrieve symbolic links.
            if item.mode == "120000":
                skipped_files += 1
                continue

            path = item.path
            file_path = PurePosixPath(path)
            parts = file_path.parts

            # Reject unsafe paths.
            if (
                file_path.is_absolute()
                or ".." in parts
                or "\\" in path
                or "\x00" in path
            ):
                skipped_files += 1
                continue

            # Ignore generated and dependency directories.
            if any(part.lower() in ignored_directories for part in parts):
                skipped_files += 1
                continue

            filename = parts[-1]
            lower_filename = filename.lower()

            # Never retrieve environment files or likely secrets.
            if (
                lower_filename.startswith(".env")
                or lower_filename.endswith(
                    (".pem", ".key", ".p12", ".pfx", ".crt")
                )
                or any(
                    word in lower_filename
                    for word in ("secret", "credential", "token")
                )
            ):
                skipped_files += 1
                continue

            is_python_file = lower_filename.endswith(".py")

            is_config_file = (
                lower_filename in allowed_config_files
                or (
                    lower_filename.startswith("requirements")
                    and lower_filename.endswith(".txt")
                )
            )

            if not (is_python_file or is_config_file):
                continue

            if item.size is None or item.size > max_file_size:
                skipped_files += 1
                continue

            if len(snapshot_files) >= max_files:
                break

            if total_size + item.size > max_total_size:
                skipped_files += 1
                continue

            blob = repository.get_git_blob(item.sha)

            content = base64.b64decode(blob.content)

            # Skip binary or non-UTF-8 files.
            if b"\x00" in content:
                skipped_files += 1
                continue

            try:
                decoded_content = content.decode("utf-8")
            except UnicodeDecodeError:
                skipped_files += 1
                continue

            snapshot_files[path] = decoded_content
            total_size += len(content)

        python_files = {
            path: content
            for path, content in snapshot_files.items()
            if path.lower().endswith(".py")
        }

        test_files = {
            path: content
            for path, content in python_files.items()
            if (
                PurePosixPath(path).name.startswith("test_")
                or PurePosixPath(path).name.endswith("_test.py")
                or "tests" in PurePosixPath(path).parts[:-1]
            )
        }

        config_files = {
            path: content
            for path, content in snapshot_files.items()
            if path not in python_files
        }

        return {
            "commit_sha": commit_sha,
            "repository": repository.full_name,
            "total": len(snapshot_files),
            "total_size": total_size,
            "skipped_files": skipped_files,
            "tree_truncated": tree.truncated,
            "files": snapshot_files,
            "python_files": python_files,
            "test_files": test_files,
            "config_files": config_files,
        }

    finally:
        github.close()

# 6A. Retrieve recent Pull Requests for a selected repository

def get_recent_pull_requests(
    repository_full_name: str,
    limit: int = 20,
):
    if not repository_full_name or "/" not in repository_full_name:
        raise ValueError("A valid owner/repository name is required")

    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100")

    github = get_github_client()

    try:
        repository = github.get_repo(repository_full_name)

        logger.info(
            "GitHub repository accessed: %s",
            repository.full_name
        )

        pull_requests = repository.get_pulls(
            state="open",
            sort="updated",
            direction="desc"
        )

        results = []

        for index, pr in enumerate(pull_requests):
            if index >= limit:
                break

            results.append({
                "number": pr.number,
                "title": pr.title,
                "state": pr.state,
                "author": pr.user.login,
                "source_branch": pr.head.ref,
                "target_branch": pr.base.ref,
                "created_at": pr.created_at.isoformat(),
                "updated_at": pr.updated_at.isoformat(),
                "html_url": pr.html_url,
                "head_sha": pr.head.sha
            })

        logger.info(
            "Retrieved %s open pull requests from %s",
            len(results),
            repository.full_name
        )
        return {
            "status": "success",
            "repository": repository.full_name,
            "total": len(results),
            "pull_requests": results
        }

    except Exception:
        logger.exception(
            "Failed to retrieve pull requests for %s",
            repository_full_name
        )
        raise

    finally:
        github.close()

# 7. Retrieve Pull Request details


def get_pull_request_details(
    pr_number: int,
    repository_full_name: str = "Pranay25-cyber/newpragnaschool",
):
    github = get_github_client()

    try:
        repository = github.get_repo(repository_full_name)
        pull_request = repository.get_pull(pr_number)

        changed_files = []

        for file in pull_request.get_files():
            changed_files.append({
                "filename": file.filename,
                "status": file.status,
                "additions": file.additions,
                "deletions": file.deletions,
                "changes": file.changes,
                "patch": file.patch
            })

        return {
            "status": "success",
            "repository": repository.full_name,
            "repository_id": repository.id,
            "repository_name": repository.name,
            "repository_full_name": repository.full_name,
            "repository_url": repository.html_url,
            "pull_request_number": pull_request.number,
            "title": pull_request.title,
            "description": pull_request.body,
            "author": pull_request.user.login,
            "state": pull_request.state,
            "source_branch": pull_request.head.ref,
            "target_branch": pull_request.base.ref,
            "head_sha": pull_request.head.sha,
            "changed_files": changed_files
        }

    finally:
        github.close()



# 8. Retrieve complete file content at a specific PR commit


def get_pull_request_file_content(
    pr_number: int,
    file_path: str,
    commit_sha: str | None = None,
    repository_full_name: str = "Pranay25-cyber/newpragnaschool",
):
    github = get_github_client()

    try:
        repository = github.get_repo(repository_full_name)
        pull_request = repository.get_pull(pr_number)

        # Fetch the file from the exact PR commit when supplied.
        ref = commit_sha or pull_request.head.sha

        file_content = repository.get_contents(
            file_path,
            ref=ref
        )

        if isinstance(file_content, list):
            raise ValueError("The requested path is a directory")

        return file_content.decoded_content.decode("utf-8")

    finally:
        github.close()



def get_repository_python_test_files(
    repository_full_name: str,
    commit_sha: str,
    max_files: int = 100,
    max_file_size: int = 500_000,
):
    """
    Retrieve Python test files from a repository at an exact commit.
    """

    if not repository_full_name or "/" not in repository_full_name:
        raise ValueError("Repository must use owner/repository format")

    if not commit_sha:
        raise ValueError("Commit SHA is required")

    if (
        isinstance(max_files, bool)
        or not isinstance(max_files, int)
        or max_files < 1
        or max_files > 500
    ):
        raise ValueError("max_files must be between 1 and 500")

    github = get_github_client()

    try:
        repository = github.get_repo(repository_full_name)

        tree = repository.get_git_tree(commit_sha, recursive=True)

        test_files = {}

        for item in tree.tree:
            if item.type != "blob":
                continue

            path = item.path
            parts = path.split("/")

            # Only discover conventional Python test files.
            is_test_file = (
                path.endswith(".py")
                and (
                    parts[-1].startswith("test_")
                    or parts[-1].endswith("_test.py")
                    or "tests" in parts[:-1]
                )
            )

            if not is_test_file:
                continue

            if item.size is None or item.size > max_file_size:
                continue

            if len(test_files) >= max_files:
                break

            content = repository.get_contents(
                path,
                ref=commit_sha,
            )

            if isinstance(content, list):
                continue

            test_files[path] = content.decoded_content.decode("utf-8")

        return {
            "commit_sha": commit_sha,
            "total": len(test_files),
            "test_files": test_files,
        }

    finally:
        github.close()

# 9. Get authenticated GitHub client for a specific installation

def get_installation_github_client(installation_id: int):

    integration = get_github_integration()

    access_token = integration.get_access_token(
        installation_id
    )

    auth = Auth.Token(access_token.token)

    return Github(auth=auth)


# 10. Retrieve Pull Request details dynamically

def get_webhook_pull_request_details(
    repository_full_name: str,
    pr_number: int,
    installation_id: int
):

    github = get_installation_github_client(
        installation_id
    )

    try:
        repository = github.get_repo(
            repository_full_name
        )

        pull_request = repository.get_pull(pr_number)

        changed_files = []

        for file in pull_request.get_files():

            changed_files.append({
                "filename": file.filename,
                "status": file.status,
                "additions": file.additions,
                "deletions": file.deletions,
                "changes": file.changes,
                "patch": file.patch
            })

        return {
            "status": "success",
            "repository": repository.full_name,
            "repository_id": repository.id,
            "repository_name": repository.name,
            "repository_full_name": repository.full_name,
            "repository_url": repository.html_url,
            "pull_request_number": pull_request.number,
            "title": pull_request.title,
            "description": pull_request.body,
            "author": pull_request.user.login,
            "state": pull_request.state,
            "source_branch": pull_request.head.ref,
            "target_branch": pull_request.base.ref,
            "head_sha": pull_request.head.sha,
            "changed_files": changed_files
        }

    finally:
        github.close()


# 11. Retrieve webhook PR file content at a specific commit

def get_webhook_pull_request_file_content(
    repository_full_name: str,
    pr_number: int,
    file_path: str,
    installation_id: int,
    commit_sha: str | None = None
):

    github = get_installation_github_client(
        installation_id
    )

    try:
        repository = github.get_repo(
            repository_full_name
        )

        pull_request = repository.get_pull(pr_number)

        ref = commit_sha or pull_request.head.sha

        file_content = repository.get_contents(
            file_path,
            ref=ref
        )

        if isinstance(file_content, list):
            raise ValueError("The requested path is a directory")

        return file_content.decoded_content.decode("utf-8")

    finally:
        github.close()


# 12. Post an inline AI review comment on a GitHub Pull Request

def post_github_review_comment(
    repository_full_name: str,
    pr_number: int,
    installation_id: int,
    commit_sha: str,
    file_path: str,
    line_number: int,
    comment_body: str
):

    if not repository_full_name:
        raise ValueError("Repository name is required")

    if (
        not isinstance(pr_number, int)
        or isinstance(pr_number, bool)
        or pr_number < 1
    ):
        raise ValueError("Invalid pull request number")

    if (
        not isinstance(line_number, int)
        or isinstance(line_number, bool)
        or line_number < 1
    ):
        raise ValueError("Invalid line number")

    if not file_path:
        raise ValueError("File path is required")

    if not comment_body or not comment_body.strip():
        raise ValueError("Comment body cannot be empty")

    github = get_installation_github_client(installation_id)

    try:
        repository = github.get_repo(repository_full_name)
        pull_request = repository.get_pull(pr_number)

        latest_commit_sha = pull_request.head.sha

        if commit_sha != latest_commit_sha:
            raise ValueError(
                "The pull request has a newer commit. "
                "Review comments must be generated for the latest commit."
            )

        commit = repository.get_commit(commit_sha)

        review_comment = pull_request.create_review_comment(
            body=comment_body,
            commit=commit,
            path=file_path,
            line=line_number,
            side="RIGHT"
        )

        return {
            "status": "success",
            "message": "GitHub review comment posted successfully",
            "comment_id": review_comment.id,
            "file_path": review_comment.path,
            "line_number": review_comment.line,
            "comment_url": review_comment.html_url
        }

    finally:
        github.close()


# 13. Retrieve accurate Pull Request counts efficiently for an installation

def get_pull_request_counts(
    repository_full_name: str,
    installation_id: int,
):
    """
    Count open and closed pull requests using GitHub pagination metadata.

    Requesting one PR per state lets GitHub's Link header report the last
    page number, avoiding iteration over every pull request.
    """
    if not repository_full_name or "/" not in repository_full_name:
        raise ValueError("A valid owner/repository name is required")

    if (
        isinstance(installation_id, bool)
        or not isinstance(installation_id, int)
        or installation_id < 1
    ):
        raise ValueError("A valid GitHub installation ID is required")

    integration = get_github_integration()
    access_token = integration.get_access_token(installation_id).token

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    def count_state(state: str) -> int:
        response = requests.get(
            f"https://api.github.com/repos/{repository_full_name}/pulls",
            headers=headers,
            params={"state": state, "per_page": 1},
            timeout=10,
        )
        response.raise_for_status()

        # With per_page=1, the last page number is the total count.
        last_link = response.links.get("last")
        if last_link and last_link.get("url"):
            query = parse_qs(urlparse(last_link["url"]).query)
            page_values = query.get("page")
            if page_values:
                return int(page_values[0])

        # No last link means zero or one result on the first page.
        data = response.json()
        return len(data)

    return {
        "repository": repository_full_name,
        "html_url": f"https://github.com/{repository_full_name}",
        "open_count": count_state("open"),
        "closed_count": count_state("closed"),
    }
