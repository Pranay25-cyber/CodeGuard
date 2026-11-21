
import pytest

from app.services.ai_review_service import validate_review_response


SOURCE_CODE = """def divide(a, b):
    return a / b
"""


def make_review(line_number):
    return {
        "summary": "One issue found.",
        "overall_status": "issues_found",
        "issues": [
            {
                "title": "Possible division by zero",
                "severity": "high",
                "issue_type": "bug",
                "line_number": line_number,
                "description": "The denominator may be zero.",
                "suggestion": "Check the denominator before division."
            }
        ]
    }


def test_valid_issue_line_number():
    result = validate_review_response(
        make_review(2),
        SOURCE_CODE
    )

    assert result["issues"][0]["line_number"] == 2


def test_line_number_must_be_within_source_code():
    with pytest.raises(ValueError, match="invalid line number"):
        validate_review_response(
            make_review(10),
            SOURCE_CODE
        )


def test_null_line_number_is_allowed():
    result = validate_review_response(
        make_review(None),
        SOURCE_CODE
    )

    assert result["issues"][0]["line_number"] is None
