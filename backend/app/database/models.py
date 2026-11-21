
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    String,
    Integer,
    Text,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    JSON,
    Boolean,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


# 0. Application users authenticated through GitHub OAuth
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    github_id: Mapped[int] = mapped_column(
        Integer,
        unique=True,
        nullable=False,
        index=True,
    )

    github_login: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    ) 
    repositories: Mapped[list["Repository"]] = relationship(
        back_populates="owner"
    )

    github_installations: Mapped[list["GitHubInstallation"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
    )

    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    avatar_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    


# 1. GitHub App installations connected by users
class GitHubInstallation(Base):
    __tablename__ = "github_installations"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    installation_id: Mapped[int] = mapped_column(
        Integer,
        unique=True,
        nullable=False,
        index=True,
    )

    account_login: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    account_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner: Mapped["User"] = relationship(
        back_populates="github_installations",
    )


# 2. GitHub repositories
class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    github_repo_id: Mapped[int] = mapped_column(
        Integer,
        unique=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    full_name: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )

    html_url: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    installation_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    owner: Mapped["User | None"] = relationship(
        back_populates="repositories",
    )

    pull_requests: Mapped[list["PullRequest"]] = relationship(
        back_populates="repository",
    )


# 3. GitHub pull requests
class PullRequest(Base):
    __tablename__ = "pull_requests"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id"),
        nullable=False,
    )

    github_pr_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        default="open",
    )

    head_sha: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    repository: Mapped["Repository"] = relationship(
        back_populates="pull_requests",
    )

    reviews: Mapped[list["Review"]] = relationship(
        back_populates="pull_request",
    )

    __table_args__ = (
        UniqueConstraint(
            "repository_id",
            "github_pr_number",
            name="uq_repository_pr_number",
        ),
    )


# 4. AI code reviews
class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    pull_request_id: Mapped[int] = mapped_column(
        ForeignKey("pull_requests.id"),
        nullable=False,
    )

    commit_sha: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    overall_status: Mapped[str] = mapped_column(
        String(50),
        default="completed",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    pull_request: Mapped["PullRequest"] = relationship(
        back_populates="reviews",
    )

    issues: Mapped[list["ReviewIssue"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan",
    )

    files: Mapped[list["ReviewFile"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "pull_request_id",
            "commit_sha",
            name="uq_review_pr_commit",
        ),
    )


# 5. Individual review findings
class ReviewIssue(Base):
    __tablename__ = "review_issues"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    review_id: Mapped[int] = mapped_column(
        ForeignKey("reviews.id"),
        nullable=False,
    )

    file_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    line_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    issue_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    severity: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    suggestion: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    source: Mapped[str] = mapped_column(
        String(50),
        default="ai",
    )

    review: Mapped["Review"] = relationship(
        back_populates="issues",
    )


# 6. GitHub webhook delivery tracking
class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    delivery_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    action: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    repository_full_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    pr_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="received",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "delivery_id",
            name="uq_webhook_delivery_id",
        ),
    )


# 7. Files analyzed during a code review
class ReviewFile(Base):
    __tablename__ = "review_files"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    review_id: Mapped[int] = mapped_column(
        ForeignKey("reviews.id"),
        nullable=False,
    )

    file_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    file_status: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    additions_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    deletions_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    changes_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    added_lines: Mapped[list] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )

    deleted_lines: Mapped[list] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )

    patch_available: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    review: Mapped["Review"] = relationship(
        back_populates="files",
    )

    __table_args__ = (
        UniqueConstraint(
            "review_id",
            "file_path",
            name="uq_review_file_path",
        ),
    )


# 8. AI-generated fix proposals
class FixProposal(Base):
    __tablename__ = "fix_proposals"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    repository_full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    original_pr_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )

    original_commit_sha: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    filename: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    original_code: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    fixed_code: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    changes_summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    validation_result: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )

    test_result: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="pending_approval",
        index=True,
    )

    github_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
