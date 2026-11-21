
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.connection import Base
from app.database.models import (
    Review,
    ReviewFile,
    ReviewIssue
)

from app.services.review_storage_service import save_review_results


@pytest.fixture
def db_session():
    """Create an isolated temporary SQLite database."""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )

    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine
    )

    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()

    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def get_review_data():
    return {
        "github_repo_id": 12345,
        "repository_name": "test-repository",
        "repository_full_name": "test-user/test-repository",
        "repository_url": "https://github.com/test-user/test-repository",
        "pr_number": 1,
        "pr_title": "Test pull request",
        "pr_description": "Testing diff storage",
        "pr_status": "open",
        "commit_sha": "test-commit-123"
    }


def test_save_review_with_diff_data(db_session):

    data = get_review_data()

    review_results = [
        {
            "filename": "example.py",
            "ai_review": {
                "summary": "Code looks good",
                "issues": []
            },
            "diff_analysis": {
                "status": "modified",
                "additions_count": 2,
                "deletions_count": 1,
                "changes_available": 3,
                "added_lines": [
                    "def add(a, b):",
                    "    return a + b"
                ],
                "deleted_lines": [
                    "return a - b"
                ],
                "patch_available": True
            }
        }
    ]

    result = save_review_results(
        db=db_session,
        review_results=review_results,
        **data
    )

    assert result["status"] == "success"
    assert result["total_files_with_diff"] == 1

    saved_file = db_session.query(ReviewFile).one()

    assert saved_file.file_path == "example.py"
    assert saved_file.file_status == "modified"
    assert saved_file.additions_count == 2
    assert saved_file.deletions_count == 1
    assert saved_file.changes_count == 3
    assert saved_file.patch_available is True

    assert saved_file.added_lines == [
        "def add(a, b):",
        "    return a + b"
    ]

    assert saved_file.deleted_lines == [
        "return a - b"
    ]


def test_save_review_with_multiple_files(db_session):

    data = get_review_data()

    review_results = [
        {
            "filename": "first.py",
            "ai_review": {"summary": "First file", "issues": []},
            "diff_analysis": {
                "status": "modified",
                "additions_count": 2,
                "deletions_count": 1,
                "changes_available": 3,
                "added_lines": ["line 1", "line 2"],
                "deleted_lines": ["old line"],
                "patch_available": True
            }
        },
        {
            "filename": "second.py",
            "ai_review": {"summary": "Second file", "issues": []},
            "diff_analysis": {
                "status": "added",
                "additions_count": 3,
                "deletions_count": 0,
                "changes_available": 3,
                "added_lines": ["a", "b", "c"],
                "deleted_lines": [],
                "patch_available": True
            }
        }
    ]

    save_review_results(
        db=db_session,
        review_results=review_results,
        **data
    )

    saved_files = db_session.query(ReviewFile).all()

    assert len(saved_files) == 2


def test_save_review_without_patch(db_session):

    data = get_review_data()

    review_results = [
        {
            "filename": "binary.py",
            "ai_review": {
                "summary": "No review issues",
                "issues": []
            },
            "diff_analysis": {
                "status": "modified",
                "additions_count": 0,
                "deletions_count": 0,
                "changes_available": 5,
                "added_lines": [],
                "deleted_lines": [],
                "patch_available": False
            }
        }
    ]

    save_review_results(
        db=db_session,
        review_results=review_results,
        **data
    )

    saved_file = db_session.query(ReviewFile).one()

    assert saved_file.patch_available is False
    assert saved_file.changes_count == 5
    assert saved_file.added_lines == []
    assert saved_file.deleted_lines == []


def test_duplicate_commit_does_not_create_duplicate_review_files(
    db_session
):

    data = get_review_data()

    review_results = [
        {
            "filename": "example.py",
            "ai_review": {
                "summary": "Initial review",
                "issues": []
            },
            "diff_analysis": {
                "status": "modified",
                "additions_count": 1,
                "deletions_count": 0,
                "changes_available": 1,
                "added_lines": ["new line"],
                "deleted_lines": [],
                "patch_available": True
            }
        }
    ]

    first_result = save_review_results(
        db=db_session,
        review_results=review_results,
        **data
    )

    second_result = save_review_results(
        db=db_session,
        review_results=review_results,
        **data
    )

    assert first_result["status"] == "success"
    assert second_result["duplicate"] is True

    assert db_session.query(Review).count() == 1
    assert db_session.query(ReviewFile).count() == 1
    assert db_session.query(ReviewIssue).count() == 0

def test_save_unified_ai_ruff_and_bandit_findings(db_session):

    data = get_review_data()

    review_results = [
        {
            "filename": "example.py",

            "ai_review": {
                "summary": "Potential logic issue found",
                "issues": [
                    {
                        "title": "Possible logic error",
                        "severity": "high",
                        "issue_type": "bug",
                        "line_number": 3,
                        "description": "Incorrect calculation.",
                        "suggestion": "Correct the calculation."
                    }
                ]
            },

            "static_analysis": {
                "ruff_issues": [
                    {
                        "code": "F401",
                        "message": "Unused import",
                        "location": {
                            "row": 1,
                            "column": 1
                        }
                    }
                ],

                "bandit_issues": [
                    {
                        "test_id": "B105",
                        "issue_text": "Possible hardcoded password",
                        "line_number": 2,
                        "issue_severity": "HIGH"
                    }
                ]
            }
        }
    ]

    result = save_review_results(
        db=db_session,
        review_results=review_results,
        **data
    )

    assert result["status"] == "success"

    saved_issues = db_session.query(ReviewIssue).all()

    # Verify all three findings were saved.
    assert len(saved_issues) == 3

    sources = {issue.source for issue in saved_issues}

    assert sources == {"ai", "ruff", "bandit"}

    # Verify every finding has the correct file and valid details.
    for issue in saved_issues:
        assert issue.file_path == "example.py"
        assert issue.line_number is not None
        assert issue.line_number > 0
        assert issue.description
