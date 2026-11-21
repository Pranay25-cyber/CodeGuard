
import pytest
from unittest.mock import patch, MagicMock

from app.services.ai_fix_service import generate_code_fix


@pytest.fixture
def valid_review():
    return {
        "issues": [
            {
                "title": "Unused import",
                "description": "Remove the unused import.",
                "severity": "low",
                "issue_type": "quality",
                "line_number": 1,
                "suggestion": "Remove the unused import."
            }
        ]
    }


@pytest.fixture
def valid_ai_response():
    return {
        "status": "success",
        "filename": "example.py",
        "changes_summary": "Removed unused import.",
        "fixed_code": "def add(a, b):\n    return a + b\n"
    }


def mock_claude_response(response_data):
    response = MagicMock()
    response.stop_reason = "end_turn"

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = __import__("json").dumps(response_data)

    response.content = [text_block]

    return response


@patch("app.services.ai_fix_service.client.messages.create")
def test_generate_valid_code_fix(
    mock_create,
    valid_review,
    valid_ai_response
):
    mock_create.return_value = mock_claude_response(
        valid_ai_response
    )

    result = generate_code_fix(
        code="import os\ndef add(a, b):\n    return a + b\n",
        filename="example.py",
        review_result=valid_review
    )

    assert result["status"] == "success"
    assert result["filename"] == "example.py"
    assert "def add" in result["fixed_code"]


@patch("app.services.ai_fix_service.client.messages.create")
def test_reject_empty_code(mock_create, valid_review):
    with pytest.raises(ValueError):
        generate_code_fix(
            code="",
            filename="example.py",
            review_result=valid_review
        )

    mock_create.assert_not_called()


@patch("app.services.ai_fix_service.client.messages.create")
def test_reject_empty_review(mock_create):
    with pytest.raises(ValueError):
        generate_code_fix(
            code="print('hello')",
            filename="example.py",
            review_result={"issues": []}
        )

    mock_create.assert_not_called()


@patch("app.services.ai_fix_service.client.messages.create")
def test_reject_invalid_json(
    mock_create,
    valid_review
):
    response = MagicMock()
    response.stop_reason = "end_turn"

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "This is not valid JSON"

    response.content = [text_block]
    mock_create.return_value = response

    with pytest.raises(ValueError, match="invalid JSON"):
        generate_code_fix(
            code="print('hello')",
            filename="example.py",
            review_result=valid_review
        )


@patch("app.services.ai_fix_service.client.messages.create")
def test_reject_truncated_response(
    mock_create,
    valid_review
):
    response = MagicMock()
    response.stop_reason = "max_tokens"
    response.content = []

    mock_create.return_value = response

    with pytest.raises(ValueError, match="truncated"):
        generate_code_fix(
            code="print('hello')",
            filename="example.py",
            review_result=valid_review
        )


@patch("app.services.ai_fix_service.client.messages.create")
def test_reject_unchanged_code(
    mock_create,
    valid_review
):
    response_data = {
        "status": "success",
        "filename": "example.py",
        "changes_summary": "No changes.",
        "fixed_code": "print('hello')"
    }

    mock_create.return_value = mock_claude_response(
        response_data
    )

    with pytest.raises(ValueError, match="unchanged code"):
        generate_code_fix(
            code="print('hello')",
            filename="example.py",
            review_result=valid_review
        )


@patch("app.services.ai_fix_service.client.messages.create")
def test_reject_wrong_filename(
    mock_create,
    valid_review,
    valid_ai_response
):
    valid_ai_response["filename"] = "wrong.py"

    mock_create.return_value = mock_claude_response(
        valid_ai_response
    )

    with pytest.raises(ValueError, match="unexpected filename"):
        generate_code_fix(
            code="print('hello')",
            filename="example.py",
            review_result=valid_review
        )
