
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ReviewFileResponse(BaseModel):
    id: int
    file_path: str
    file_status: str | None
    additions_count: int
    deletions_count: int
    changes_count: int
    added_lines: list
    deleted_lines: list
    patch_available: bool

    model_config = ConfigDict(from_attributes=True)


class ReviewIssueResponse(BaseModel):
    id: int
    file_path: str
    line_number: int | None
    issue_type: str
    severity: str
    description: str
    suggestion: str | None
    source: str

    model_config = ConfigDict(from_attributes=True)


class ReviewResponse(BaseModel):
    id: int
    commit_sha: str
    summary: str | None
    overall_status: str
    created_at: datetime
    files: list[ReviewFileResponse]
    issues: list[ReviewIssueResponse]

    model_config = ConfigDict(from_attributes=True)


class PullRequestReviewResponse(BaseModel):
    id: int
    github_pr_number: int
    title: str
    description: str | None
    status: str
    head_sha: str | None
    reviews: list[ReviewResponse]

    model_config = ConfigDict(from_attributes=True)
