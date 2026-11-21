
import pytest

from app.services.ai_review_service import validate_review_response


VALID_REVIEW = {
    "summary": "One issue found in the code.",
    "overall_status": "issues_found",
    "issues": [
        {
            "title": "Possible division by zero",
            "severity": "high",
            "issue_type": "bug",
            "line_number": 2,
            "description": "The divisor may be zero.",
            "suggestion": "Check the divisor before division."
        }
    ]
}

VALID_CODE = """def divide(a, b):
    return a / b
"""


def test_valid_review_response_is_accepted():
    result = validate_review_response(VALID_REVIEW, VALID_CODE)

    assert result["overall_status"] == "issues_found"
    assert len(result["issues"]) == 1


def test_invalid_severity_is_rejected():
    review = {
        **VALID_REVIEW,
        "issues": [
            {
                **VALID_REVIEW["issues"][0],
                "severity": "urgent"
            }
        ]
    }

    with pytest.raises(ValueError, match="invalid severity"):
        validate_review_response(review, VALID_CODE)


def test_invalid_issue_type_is_rejected():
    review = {
        **VALID_REVIEW,
        "issues": [
            {
                **VALID_REVIEW["issues"][0],
                "issue_type": "performance"
            }
        ]
    }

    with pytest.raises(ValueError, match="invalid issue type"):
        validate_review_response(review, VALID_CODE)


def test_zero_line_number_is_rejected():
    review = {
        **VALID_REVIEW,
        "issues": [
            {
                **VALID_REVIEW["issues"][0],
                "line_number": 0
            }
        ]
    }

    with pytest.raises(ValueError, match="invalid line number"):
        validate_review_response(review, VALID_CODE)


def test_line_number_beyond_source_is_rejected():
    review = {
        **VALID_REVIEW,
        "issues": [
            {
                **VALID_REVIEW["issues"][0],
                "line_number": 100
            }
        ]
    }

    with pytest.raises(ValueError, match="invalid line number"):
        validate_review_response(review, VALID_CODE)


def test_boolean_line_number_is_rejected():
    review = {
        **VALID_REVIEW,
        "issues": [
            {
                **VALID_REVIEW["issues"][0],
                "line_number": True
            }
        ]
    }

    with pytest.raises(ValueError, match="invalid line number"):
        validate_review_response(review, VALID_CODE)


def test_missing_issue_field_is_rejected():
    issue = VALID_REVIEW["issues"][0].copy()
    del issue["suggestion"]

    review = {
        **VALID_REVIEW,
        "issues": [issue]
    }

    with pytest.raises(ValueError, match="missing 'suggestion'"):
        validate_review_response(review, VALID_CODE)


def test_inconsistent_overall_status_is_rejected():
    review = {
        **VALID_REVIEW,
        "overall_status": "passed"
    }

    with pytest.raises(ValueError, match="does not match"):
        validate_review_response(review, VALID_CODE)


def test_empty_issues_with_passed_status_is_accepted():
    review = {
        "summary": "No issues found.",
        "overall_status": "passed",
        "issues": []
    }

    result = validate_review_response(review, VALID_CODE)

    assert result["overall_status"] == "passed"
    assert result["issues"] == []
