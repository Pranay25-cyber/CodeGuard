from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.ai_review_service import review_python_code


def mock_claude_response(text):
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text=text
            )
        ],
        stop_reason="end_turn",
        id="mock-response"
    )


def test_valid_claude_response():
    response_json = """
    {
        "summary": "One issue found.",
        "overall_status": "issues_found",
        "issues": [
            {
                "title": "Division by zero",
                "severity": "high",
                "issue_type": "bug",
                "line_number": 2,
                "description": "The code may divide by zero.",
                "suggestion": "Check the denominator before division."
            }
        ]
    }
    """

    with patch(
        "app.services.ai_review_service.client.messages.create",
        return_value=mock_claude_response(response_json)
    ):
        result = review_python_code(
            code="def divide(a, b):\n    return a / b",
            filename="calculator.py"
        )

    assert result["overall_status"] == "issues_found"
    assert len(result["issues"]) == 1
    assert result["issues"][0]["severity"] == "high"


def test_empty_claude_response():
    with patch(
        "app.services.ai_review_service.client.messages.create",
        return_value=mock_claude_response("")
    ):
        with pytest.raises(ValueError, match="empty response"):
            review_python_code(
                code="print('Hello')",
                filename="hello.py"
            )


def test_invalid_json_response():
    with patch(
        "app.services.ai_review_service.client.messages.create",
        return_value=mock_claude_response("This is not valid JSON")
    ):
        with pytest.raises(ValueError, match="JSON object"):
            review_python_code(
                code="print('Hello')",
                filename="hello.py"
            )


def test_missing_issues_list():
    response_json = """
    {
        "summary": "Review completed.",
        "overall_status": "passed"
    }
    """

    with patch(
        "app.services.ai_review_service.client.messages.create",
        return_value=mock_claude_response(response_json)
    ):
        with pytest.raises(ValueError, match="issues list"):
            review_python_code(
                code="print('Hello')",
                filename="hello.py"
            )


def test_claude_request_uses_configured_model():
    response_json = """
    {
        "summary": "No issues found.",
        "overall_status": "passed",
        "issues": []
    }
    """

    with patch(
        "app.services.ai_review_service.client.messages.create",
        return_value=mock_claude_response(response_json)
    ) as mock_create:
        review_python_code(
            code="print('Hello')",
            filename="hello.py"
        )

    mock_create.assert_called_once()

    request = mock_create.call_args.kwargs

    assert request["max_tokens"] == 4096
    assert request["model"]
    assert "system" in request
    assert "messages" in request