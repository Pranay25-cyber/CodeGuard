"""GitHub-backed Python editor endpoints for the authenticated user."""
import base64
import hashlib
import logging
from urllib.parse import quote

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Repository
from app.services.static_analyzer import analyze_python_code
from app.services.ai_review_service import review_python_code
from app.routes.github_installations import (
    get_installation_headers,
    get_user_installation,
    require_login,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/code-editor", tags=["Code Editor"])
GITHUB_API = "https://api.github.com"


class SavePythonFileRequest(BaseModel):
    repository_full_name: str = Field(min_length=3, max_length=255)
    branch: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=500)
    content: str
    create_only: bool = False
    commit_message: str = Field(default="Update Python file using CodeGuard", min_length=1, max_length=200)


class ReviewPythonFileRequest(BaseModel):
    repository_full_name: str = Field(min_length=3, max_length=255)
    branch: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1)


def _validate_python_path(path: str) -> str:
    path = path.strip()
    if not path.lower().endswith(".py"):
        raise HTTPException(status_code=422, detail="Only Python files ending in .py can be reviewed.")
    if path.startswith("/") or "\\" in path or ".." in path.split("/") or any(not part for part in path.split("/")):
        raise HTTPException(status_code=422, detail="Please provide a safe relative Python file path.")
    return path


def _owned_repository(db: Session, user_id: int, full_name: str) -> tuple[Repository, dict]:
    repository = (
        db.query(Repository)
        .filter(
            Repository.full_name == full_name,
            Repository.user_id == user_id,
        )
        .first()
    )
    if not repository or not repository.installation_id:
        raise HTTPException(status_code=404, detail="Repository is not connected to your account.")

    installation = get_user_installation(db, user_id, repository.installation_id)
    if not installation:
        raise HTTPException(status_code=403, detail="You do not have access to this GitHub installation.")
    return repository, get_installation_headers(installation.installation_id)


def _github_get(url: str, headers: dict, params: dict | None = None) -> dict:
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="GitHub resource not found.")
        response.raise_for_status()
        return response.json()
    except HTTPException:
        raise
    except requests.RequestException as exc:
        logger.exception("GitHub editor GET request failed")
        raise HTTPException(status_code=502, detail="Unable to retrieve data from GitHub.") from exc


def _validate_branch(branch: str, headers: dict, full_name: str) -> None:
    encoded = quote(branch, safe="")
    _github_get(f"{GITHUB_API}/repos/{full_name}/branches/{encoded}", headers)


@router.get("/branches")
def list_branches(repository_full_name: str, request: Request, db: Session = Depends(get_db)):
    user_id = require_login(request)
    _, headers = _owned_repository(db, user_id, repository_full_name)
    data = _github_get(
        f"{GITHUB_API}/repos/{repository_full_name}/branches",
        headers,
        {"per_page": 100},
    )
    return {"branches": [{"name": item["name"], "protected": item.get("protected", False)} for item in data]}


class CreateBranchRequest(BaseModel):
    repository_full_name: str = Field(min_length=3, max_length=255)
    branch_name: str = Field(min_length=1, max_length=255)


@router.post("/branches")
def create_branch(payload: CreateBranchRequest, request: Request, db: Session = Depends(get_db)):
    """Create a branch from the repository's default branch for the authenticated user."""
    user_id = require_login(request)
    _, headers = _owned_repository(db, user_id, payload.repository_full_name)
    branch_name = payload.branch_name.strip()
    if not branch_name or branch_name.startswith("/") or branch_name.endswith("/") or ".." in branch_name or "\\" in branch_name or " " in branch_name:
        raise HTTPException(status_code=422, detail="Enter a valid Git branch name (for example feature/my-change).")

    existing_branches = _github_get(
        f"{GITHUB_API}/repos/{payload.repository_full_name}/branches",
        headers,
        {"per_page": 100},
    )
    if any(item.get("name") == branch_name for item in existing_branches):
        raise HTTPException(
            status_code=409,
            detail=f"Branch '{branch_name}' already exists in repository '{payload.repository_full_name}'.",
        )

    repo_data = _github_get(f"{GITHUB_API}/repos/{payload.repository_full_name}", headers)
    default_branch = repo_data.get("default_branch") or "main"
    source_branch = _github_get(
        f"{GITHUB_API}/repos/{payload.repository_full_name}/branches/{quote(default_branch, safe='')}", headers
    )
    source_sha = source_branch.get("commit", {}).get("sha")
    if not source_sha:
        raise HTTPException(status_code=502, detail="GitHub did not return the default branch commit SHA.")

    try:
        response = requests.post(
            f"{GITHUB_API}/repos/{payload.repository_full_name}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch_name}", "sha": source_sha},
            timeout=30,
        )
        if response.status_code == 422:
            detail = response.json().get("message", "The branch may already exist or the name is invalid.")
            raise HTTPException(status_code=422, detail=f"GitHub could not create the branch: {detail}")
        if response.status_code not in (200, 201):
            logger.error("GitHub branch creation failed: %s %s", response.status_code, response.text[:500])
            raise HTTPException(status_code=502, detail="GitHub could not create the branch. Check repository permissions.")
        return {"status": "created", "name": branch_name, "source_branch": default_branch, "sha": response.json().get("object", {}).get("sha")}
    except HTTPException:
        raise
    except requests.RequestException as exc:
        logger.exception("GitHub branch creation request failed")
        raise HTTPException(status_code=502, detail="Unable to create the branch on GitHub.") from exc


@router.get("/files")
def list_python_files(repository_full_name: str, branch: str, request: Request, db: Session = Depends(get_db)):
    user_id = require_login(request)
    _, headers = _owned_repository(db, user_id, repository_full_name)
    _validate_branch(branch, headers, repository_full_name)
    ref = quote(branch, safe="")
    tree = _github_get(
        f"{GITHUB_API}/repos/{repository_full_name}/git/trees/{ref}",
        headers,
        {"recursive": "1"},
    )
    files = [
        {"path": item["path"], "size": item.get("size", 0)}
        for item in tree.get("tree", [])
        if item.get("type") == "blob" and item.get("path", "").lower().endswith(".py")
    ]
    return {"files": files, "truncated": tree.get("truncated", False)}


@router.get("/file")
def read_python_file(repository_full_name: str, branch: str, path: str, request: Request, db: Session = Depends(get_db)):
    user_id = require_login(request)
    _, headers = _owned_repository(db, user_id, repository_full_name)
    if not path.lower().endswith(".py") or path.startswith("/") or ".." in path.split("/"):
        raise HTTPException(status_code=400, detail="Only safe .py file paths are supported.")
    _validate_branch(branch, headers, repository_full_name)
    encoded_path = quote(path, safe="/")
    data = _github_get(
        f"{GITHUB_API}/repos/{repository_full_name}/contents/{encoded_path}",
        headers,
        {"ref": branch},
    )
    if data.get("type") != "file" or not data.get("content"):
        raise HTTPException(status_code=422, detail="GitHub did not return a readable file.")
    try:
        content = base64.b64decode(data["content"]).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail="The selected file is not valid UTF-8 text.") from exc
    return {"path": path, "branch": branch, "content": content, "sha": data.get("sha")}


@router.post("/save")
def save_python_file(payload: SavePythonFileRequest, request: Request, db: Session = Depends(get_db)):
    user_id = require_login(request)
    _, headers = _owned_repository(db, user_id, payload.repository_full_name)

    path = payload.path.strip()
    if not path.lower().endswith(".py"):
        raise HTTPException(status_code=422, detail="Only Python files ending in .py can be saved.")
    if path.startswith("/") or "\\" in path or ".." in path.split("/") or any(not part for part in path.split("/")):
        raise HTTPException(status_code=422, detail="Please provide a safe relative file path.")
    if not payload.content.strip():
        raise HTTPException(status_code=422, detail="Python file content cannot be empty or whitespace-only.")

    _validate_branch(payload.branch, headers, payload.repository_full_name)
    encoded_path = quote(path, safe="/")
    contents_url = f"{GITHUB_API}/repos/{payload.repository_full_name}/contents/{encoded_path}"

    # GitHub's Contents API returns the Git blob SHA. Calculate the same SHA
    # from the submitted bytes so identical content is a no-op (no new commit).
    existing_sha = None
    try:
        existing = requests.get(
            contents_url,
            headers=headers,
            params={"ref": payload.branch},
            timeout=30,
        )
        if existing.status_code == 200:
            existing_data = existing.json()
            existing_sha = existing_data.get("sha")
            if payload.create_only:
                raise HTTPException(
                    status_code=409,
                    detail=f"File '{path}' already exists in repository '{payload.repository_full_name}' on branch '{payload.branch}'. Choose another filename or use Edit.",
                )

            submitted_bytes = payload.content.encode("utf-8")
            git_blob_header = f"blob {len(submitted_bytes)}\0".encode("ascii")
            submitted_blob_sha = hashlib.sha1(git_blob_header + submitted_bytes).hexdigest()
            if existing_sha and submitted_blob_sha == existing_sha:
                return {
                    "status": "unchanged",
                    "action": "unchanged",
                    "message": "No changes detected. File is already up to date; no commit was created.",
                    "path": path,
                    "branch": payload.branch,
                    "commit_sha": None,
                    "commit_url": None,
                    "file_url": existing_data.get("html_url"),
                }
        elif existing.status_code != 404:
            logger.error("GitHub existing-file check failed: %s %s", existing.status_code, existing.text[:500])
            raise HTTPException(status_code=502, detail="Unable to check the existing GitHub file.")

        body = {
            "message": payload.commit_message.strip(),
            "content": base64.b64encode(payload.content.encode("utf-8")).decode("ascii"),
            "branch": payload.branch,
        }
        if existing_sha:
            body["sha"] = existing_sha

        response = requests.put(contents_url, headers=headers, json=body, timeout=30)
        if response.status_code not in (200, 201):
            logger.error("GitHub save failed: %s %s", response.status_code, response.text[:500])
            if response.status_code in (409, 422):
                raise HTTPException(status_code=409, detail="The file changed on GitHub while you were saving. Refresh the file and try again.")
            raise HTTPException(status_code=502, detail="GitHub could not commit this file. Check branch permissions and try again.")

        result = response.json()
        commit = result.get("commit", {})
        return {
            "status": "saved",
            "action": "updated" if existing_sha else "created",
            "path": path,
            "branch": payload.branch,
            "commit_sha": commit.get("sha"),
            "commit_url": commit.get("html_url"),
            "file_url": result.get("content", {}).get("html_url"),
        }
    except HTTPException:
        raise
    except requests.RequestException as exc:
        logger.exception("GitHub file save request failed")
        raise HTTPException(status_code=502, detail="Unable to save the file to GitHub.") from exc


@router.post("/review")
def review_python_file(payload: ReviewPythonFileRequest, request: Request, db: Session = Depends(get_db)):
    """Review unsaved or GitHub-loaded Python source without committing changes."""
    user_id = require_login(request)
    _, headers = _owned_repository(db, user_id, payload.repository_full_name)
    _validate_branch(payload.branch, headers, payload.repository_full_name)

    path = _validate_python_path(payload.path)
    if not payload.content.strip():
        raise HTTPException(status_code=422, detail="Python file content cannot be empty or whitespace-only.")

    try:
        static_analysis = analyze_python_code(payload.content)
        ai_review = review_python_code(
            code=payload.content,
            filename=path,
            static_analysis=static_analysis,
        )

        source_lines = payload.content.splitlines()
        findings = []
        for issue in ai_review.get("issues", []):
            line_number = issue.get("line_number")
            original_code = None
            if isinstance(line_number, int) and not isinstance(line_number, bool) and 1 <= line_number <= len(source_lines):
                original_code = source_lines[line_number - 1]

            findings.append({
                "title": issue.get("title", "Potential code issue"),
                "issue_type": issue.get("issue_type", "quality"),
                "line_number": line_number,
                "description": issue.get("description", ""),
                "suggestion": issue.get("suggestion", ""),
                "original_code": original_code,
                "replacement_code": issue.get("replacement_code"),
            })

        return {
            "status": "success",
            "filename": path,
            "summary": ai_review.get("summary", "Review completed."),
            "overall_status": ai_review.get("overall_status", "passed"),
            "total_issues": len(findings),
            "findings": findings,
            "static_analysis": static_analysis,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Code Editor AI review failed for %s", path)
        raise HTTPException(status_code=502, detail="AI review could not be completed. Check the backend logs and AI configuration.") from exc


class DeletePythonFileRequest(BaseModel):
    commit_message: str = Field(default="Delete Python file using CodeGuard", min_length=1, max_length=200)


@router.delete("/file")
def delete_python_file(
    repository_full_name: str,
    branch: str,
    path: str,
    request: Request,
    payload: DeletePythonFileRequest,
    db: Session = Depends(get_db),
):
    """Delete a Python file from the selected GitHub branch in a real commit."""
    user_id = require_login(request)
    _, headers = _owned_repository(db, user_id, repository_full_name)

    path = path.strip()
    if not path.lower().endswith(".py"):
        raise HTTPException(status_code=422, detail="Only Python files ending in .py can be deleted.")
    if path.startswith("/") or "\\" in path or ".." in path.split("/") or any(not part for part in path.split("/")):
        raise HTTPException(status_code=422, detail="Please provide a safe relative file path.")
    _validate_branch(branch, headers, repository_full_name)

    encoded_path = quote(path, safe="/")
    contents_url = f"{GITHUB_API}/repos/{repository_full_name}/contents/{encoded_path}"
    existing = _github_get(contents_url, headers, {"ref": branch})
    file_sha = existing.get("sha")
    if existing.get("type") != "file" or not file_sha:
        raise HTTPException(status_code=404, detail="The selected GitHub file was not found.")

    try:
        response = requests.delete(
            contents_url,
            headers=headers,
            json={
                "message": payload.commit_message.strip(),
                "sha": file_sha,
                "branch": branch,
            },
            timeout=30,
        )
        if response.status_code not in (200, 201):
            logger.error("GitHub file deletion failed: %s %s", response.status_code, response.text[:500])
            if response.status_code == 404:
                raise HTTPException(status_code=404, detail="The file no longer exists on this branch. Refresh the file list.")
            if response.status_code == 409:
                raise HTTPException(status_code=409, detail="The file changed on GitHub. Refresh it and try again.")
            raise HTTPException(status_code=502, detail="GitHub could not delete the file. Check branch permissions and try again.")
        result = response.json()
        commit = result.get("commit", {})
        return {
            "status": "deleted",
            "path": path,
            "branch": branch,
            "commit_sha": commit.get("sha"),
            "commit_url": commit.get("html_url"),
        }
    except HTTPException:
        raise
    except requests.RequestException as exc:
        logger.exception("GitHub file deletion request failed")
        raise HTTPException(status_code=502, detail="Unable to delete the file from GitHub.") from exc


class CreatePullRequestRequest(BaseModel):
    repository_full_name: str = Field(min_length=3, max_length=255)
    head_branch: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(default="", max_length=50000)


@router.get("/pull-requests/existing")
def get_existing_pull_request(
    repository_full_name: str,
    head_branch: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Return an existing open PR for this repository branch into main, if any."""
    user_id = require_login(request)
    _, headers = _owned_repository(db, user_id, repository_full_name)
    _validate_branch(head_branch, headers, repository_full_name)
    owner = repository_full_name.split("/", 1)[0]
    data = _github_get(
        f"{GITHUB_API}/repos/{repository_full_name}/pulls",
        headers,
        {"state": "open", "head": f"{owner}:{head_branch}", "base": "main", "per_page": 100},
    )
    if not data:
        return {"exists": False, "pull_request": None}
    item = data[0]
    return {
        "exists": True,
        "pull_request": {
            "number": item.get("number"),
            "title": item.get("title"),
            "state": item.get("state"),
            "html_url": item.get("html_url"),
            "head_branch": item.get("head", {}).get("ref"),
            "base_branch": item.get("base", {}).get("ref"),
        },
    }


@router.get("/pull-requests/list")
def list_pull_requests(
    repository_full_name: str,
    request: Request,
    state: str = "open",
    head_branch: str | None = None,
    db: Session = Depends(get_db),
):
    """List live GitHub pull requests for one of the authenticated user's repositories."""
    user_id = require_login(request)
    _, headers = _owned_repository(db, user_id, repository_full_name)

    requested_state = state.strip().lower()
    if requested_state not in {"open", "closed", "all"}:
        raise HTTPException(status_code=422, detail="State must be open, closed, or all.")

    params = {"state": requested_state, "per_page": 100, "sort": "updated", "direction": "desc"}
    if head_branch and head_branch.strip():
        params["head"] = f"{repository_full_name.split('/', 1)[0]}:{head_branch.strip()}"

    data = _github_get(
        f"{GITHUB_API}/repos/{repository_full_name}/pulls",
        headers,
        params,
    )
    return {
        "repository": repository_full_name,
        "state": requested_state,
        "pull_requests": [
            {
                "number": item.get("number"),
                "title": item.get("title"),
                "body": item.get("body") or "",
                "state": item.get("state"),
                "html_url": item.get("html_url"),
                "head_branch": item.get("head", {}).get("ref"),
                "base_branch": item.get("base", {}).get("ref"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "user": item.get("user", {}).get("login"),
                "draft": item.get("draft", False),
            }
            for item in data
        ],
    }


@router.patch("/pull-requests/{pull_request_number}/close")
def close_pull_request(
    pull_request_number: int,
    repository_full_name: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Close an open pull request on GitHub and return its updated state."""
    user_id = require_login(request)
    _, headers = _owned_repository(db, user_id, repository_full_name)

    if pull_request_number <= 0:
        raise HTTPException(status_code=422, detail="Invalid Pull Request number.")

    pull_url = f"{GITHUB_API}/repos/{repository_full_name}/pulls/{pull_request_number}"
    current = _github_get(pull_url, headers)
    if current.get("state") != "open":
        raise HTTPException(status_code=409, detail="This Pull Request is already closed.")

    try:
        response = requests.patch(
            pull_url,
            headers=headers,
            json={"state": "closed"},
            timeout=30,
        )
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Pull Request not found in this repository.")
        if response.status_code not in (200,):
            logger.error("GitHub PR close failed: %s %s", response.status_code, response.text[:500])
            if response.status_code == 403:
                raise HTTPException(
                    status_code=403,
                    detail="GitHub denied closing this Pull Request. Grant your GitHub App Pull requests: Read and write permission, then update its installation.",
                )
            raise HTTPException(status_code=502, detail="GitHub could not close this Pull Request.")
        result = response.json()
        return {
            "status": "closed",
            "number": result.get("number"),
            "title": result.get("title"),
            "state": result.get("state"),
            "html_url": result.get("html_url"),
            "head_branch": result.get("head", {}).get("ref"),
            "base_branch": result.get("base", {}).get("ref"),
            "message": f"Pull Request #{pull_request_number} was closed on GitHub.",
        }
    except HTTPException:
        raise
    except requests.RequestException as exc:
        logger.exception("GitHub Pull Request close request failed")
        raise HTTPException(status_code=502, detail="Unable to close the Pull Request on GitHub.") from exc


@router.post("/pull-requests")
def create_pull_request(payload: CreatePullRequestRequest, request: Request, db: Session = Depends(get_db)):
    """Create a GitHub PR from the selected branch into the repository's main branch."""
    user_id = require_login(request)
    _, headers = _owned_repository(db, user_id, payload.repository_full_name)

    head_branch = payload.head_branch.strip()
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Pull Request title cannot be empty.")
    if head_branch == "main":
        raise HTTPException(status_code=422, detail="Choose a source branch other than main.")

    # Confirm the source branch exists before asking GitHub to create the PR.
    _validate_branch(head_branch, headers, payload.repository_full_name)

    owner = payload.repository_full_name.split("/", 1)[0]
    existing_prs = _github_get(
        f"{GITHUB_API}/repos/{payload.repository_full_name}/pulls",
        headers,
        {"state": "open", "head": f"{owner}:{head_branch}", "base": "main", "per_page": 100},
    )
    if existing_prs:
        item = existing_prs[0]
        return {
            "status": "existing",
            "number": item.get("number"),
            "title": item.get("title"),
            "state": item.get("state"),
            "html_url": item.get("html_url"),
            "head_branch": item.get("head", {}).get("ref"),
            "base_branch": item.get("base", {}).get("ref"),
        }

    # Do not create an empty PR. Compare the actual GitHub branches rather
    # than relying on whether a file is currently open in the CodeGuard editor.
    compare_url = (
        f"{GITHUB_API}/repos/{payload.repository_full_name}/compare/"
        f"main...{quote(head_branch, safe='/')}"
    )
    try:
        compare_response = requests.get(compare_url, headers=headers, timeout=30)
        if compare_response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail="GitHub could not compare this branch with main. Check that both branches exist.",
            )
        compare_response.raise_for_status()
        comparison = compare_response.json()
    except HTTPException:
        raise
    except requests.RequestException as exc:
        logger.exception("GitHub branch comparison failed before PR creation")
        raise HTTPException(
            status_code=502,
            detail="Unable to compare the selected branch with main. No Pull Request was created.",
        ) from exc

    ahead_by = comparison.get("ahead_by", 0)
    changed_files = comparison.get("files") or []
    if not isinstance(ahead_by, int) or ahead_by <= 0 or not changed_files:
        raise HTTPException(
            status_code=409,
            detail=(
                f"No changes found between '{head_branch}' and 'main'. "
                "Add and commit changes to the source branch before creating a Pull Request."
            ),
        )

    url = f"{GITHUB_API}/repos/{payload.repository_full_name}/pulls"
    try:
        response = requests.post(
            url,
            headers=headers,
            json={
                "title": title,
                "body": payload.body.strip(),
                "head": head_branch,
                "base": "main",
            },
            timeout=30,
        )
        if response.status_code == 422:
            detail = response.json().get("errors") or response.json().get("message")
            raise HTTPException(status_code=422, detail=f"GitHub could not create this Pull Request: {detail}")
        if response.status_code not in (200, 201):
            logger.error("GitHub PR creation failed: %s %s", response.status_code, response.text[:500])
            raise HTTPException(status_code=502, detail="GitHub could not create the Pull Request. Check branch permissions and whether the branches have changes.")
        result = response.json()
        return {
            "status": "created",
            "number": result.get("number"),
            "title": result.get("title"),
            "state": result.get("state"),
            "html_url": result.get("html_url"),
            "head_branch": result.get("head", {}).get("ref"),
            "base_branch": result.get("base", {}).get("ref"),
        }
    except HTTPException:
        raise
    except requests.RequestException as exc:
        logger.exception("GitHub Pull Request creation request failed")
        raise HTTPException(status_code=502, detail="Unable to create the Pull Request on GitHub.") from exc
