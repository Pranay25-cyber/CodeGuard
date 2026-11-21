
from app.services.issue_verification_service import (
    verify_issue_line,
    verify_review_issues,
    match_issues_to_added_lines,
)


SOURCE_CODE = """def divide(a, b):
    return a / b

print("Hello")
"""


def test_valid_source_line():
    issue = {"line_number": 2}

    result = verify_issue_line(issue, SOURCE_CODE)

    assert result["verified"] is True
    assert result["source_line"] == "return a / b"


def test_invalid_source_line():
    issue = {"line_number": 100}

    result = verify_issue_line(issue, SOURCE_CODE)

    assert result["verified"] is False


def test_null_line_number():
    issue = {"line_number": None}

    result = verify_issue_line(issue, SOURCE_CODE)

    assert result["verified"] is False


def test_empty_source_line():
    issue = {"line_number": 3}

    result = verify_issue_line(issue, SOURCE_CODE)

    assert result["verified"] is False


def test_boolean_line_number():
    issue = {"line_number": True}

    result = verify_issue_line(issue, SOURCE_CODE)

    assert result["verified"] is False


def test_verify_multiple_issues():
    issues = [
        {
            "title": "Division issue",
            "line_number": 2
        },
        {
            "title": "Invalid line",
            "line_number": 100
        }
    ]

    results = verify_review_issues(issues, SOURCE_CODE)

    assert len(results) == 2
    assert results[0]["verified"] is True
    assert results[1]["verified"] is False

def test_verification_result_contains_issue_title():
    issues = [
        {
            "title": "Division by zero",
            "line_number": 2
        }
    ]

    results = verify_review_issues(issues, SOURCE_CODE)

    assert results[0]["title"] == "Division by zero"


def test_verification_preserves_original_ai_issue():
    issue = {
        "title": "Division by zero",
        "severity": "high",
        "issue_type": "bug",
        "line_number": 2,
        "description": "The denominator may be zero.",
        "suggestion": "Check the denominator."
    }

    original_issue = issue.copy()

    verify_review_issues([issue], SOURCE_CODE)

    assert issue == original_issue

def test_match_verified_issue_to_added_line():
    issues = [
        {
            "title": "Inconsistent return type",
            "line_number": 2,
            "severity": "medium",
            "issue_type": "logic",
            "description": "Returns different types.",
            "suggestion": "Raise ValueError.",
        }
    ]

    verification_results = [
        {
            "title": "Inconsistent return type",
            "line_number": 2,
            "verified": True,
            "source_line": 'return "Cannot divide by zero"',
        }
    ]

    file_diff = {
        "filename": "division.py",
        "patch_available": True,
        "added_line_positions": [
            {
                "line_number": 2,
                "diff_position": 3,
                "content": 'return "Cannot divide by zero"',
            }
        ],
    }

    candidates = match_issues_to_added_lines(
        issues,
        verification_results,
        file_diff,
    )

    assert len(candidates) == 1
    assert candidates[0]["file_path"] == "division.py"
    assert candidates[0]["line_number"] == 2
    assert candidates[0]["severity"] == "medium"


def test_do_not_match_issue_on_unchanged_line():
    issues = [{"title": "Possible issue", "line_number": 2}]

    verification_results = [
        {
            "line_number": 2,
            "verified": True,
            "source_line": "return a / b",
        }
    ]

    file_diff = {
        "filename": "division.py",
        "patch_available": True,
        "added_line_positions": [],
    }

    candidates = match_issues_to_added_lines(
        issues,
        verification_results,
        file_diff,
    )

    assert candidates == []


def test_do_not_match_unverified_issue():
    issues = [{"title": "Possible issue", "line_number": 2}]

    verification_results = [
        {
            "line_number": 2,
            "verified": False,
            "reason": "Invalid source line",
        }
    ]

    file_diff = {
        "filename": "division.py",
        "patch_available": True,
        "added_line_positions": [
            {
                "line_number": 2,
                "diff_position": 3,
                "content": "return a / b",
            }
        ],
    }

    candidates = match_issues_to_added_lines(
        issues,
        verification_results,
        file_diff,
    )

    assert candidates == []
