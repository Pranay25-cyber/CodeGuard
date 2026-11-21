
from unittest.mock import patch

from app.services.fix_workflow_service import run_fix_workflow


def get_review_result():
    return {
        "issues": [
            {
                "description": "Division by zero is not handled",
                "severity": "high"
            }
        ]
    }


def setup_successful_mocks(
    mock_ai,
    mock_validation,
    mock_tests,
    mock_github
):
    mock_ai.return_value = {
        "fixed_code": "def divide(a, b):\n    return a / b",
        "changes_summary": "Generated a test fix"
    }

    mock_validation.return_value = {
        "status": "passed",
        "message": "Validation successful"
    }

    mock_tests.return_value = {
        "status": "passed",
        "return_code": 0,
        "test_output": "3 passed",
        "error_output": ""
    }

    mock_github.return_value = {
        "status": "success",
        "fix_branch": "ai-fix/test-branch",
        "fix_pr_number": 99,
        "fix_pr_url": "https://github.com/example/repo/pull/99"
    }


def test_validation_failure_does_not_publish_to_github():

    with patch(
        "app.services.fix_workflow_service.generate_code_fix"
    ) as mock_ai, patch(
        "app.services.fix_workflow_service.validate_fixed_code"
    ) as mock_validation, patch(
        "app.services.fix_workflow_service.run_automated_tests"
    ) as mock_tests, patch(
        "app.services.fix_workflow_service.create_fix_pull_request"
    ) as mock_github:

        mock_ai.return_value = {
            "fixed_code": "def divide(a, b):\n    return a / b",
            "changes_summary": "Generated a test fix"
        }

        mock_validation.return_value = {
            "status": "failed",
            "message": "Syntax validation failed"
        }

        result = run_fix_workflow(
            code="def divide(a, b):\n    return a / b",
            filename="division.py",
            review_result=get_review_result(),
            test_code="def test_dummy():\n    assert True",
            publish_to_github=True,
            repository_full_name="Pranay25-cyber/newpragnaschool",
            original_pr_number=1,
            developer_approved=True
        )

        assert result["status"] == "validation_failed"

        mock_tests.assert_not_called()
        mock_github.assert_not_called()


def test_docker_failure_does_not_publish_to_github():

    with patch(
        "app.services.fix_workflow_service.generate_code_fix"
    ) as mock_ai, patch(
        "app.services.fix_workflow_service.validate_fixed_code"
    ) as mock_validation, patch(
        "app.services.fix_workflow_service.run_automated_tests"
    ) as mock_tests, patch(
        "app.services.fix_workflow_service.create_fix_pull_request"
    ) as mock_github:

        mock_ai.return_value = {
            "fixed_code": "def divide(a, b):\n    return a / b",
            "changes_summary": "Generated a test fix"
        }

        mock_validation.return_value = {
            "status": "passed",
            "message": "Validation successful"
        }

        mock_tests.return_value = {
            "status": "failed",
            "return_code": 1,
            "test_output": "1 failed, 2 passed",
            "error_output": "Test failure"
        }

        result = run_fix_workflow(
            code="def divide(a, b):\n    return a / b",
            filename="division.py",
            review_result=get_review_result(),
            test_code="def test_dummy():\n    assert True",
            publish_to_github=True,
            repository_full_name="Pranay25-cyber/newpragnaschool",
            original_pr_number=1,
            developer_approved=True
        )

        assert result["status"] == "tests_failed"
        mock_github.assert_not_called()


def test_publishing_disabled_does_not_call_github():

    with patch(
        "app.services.fix_workflow_service.generate_code_fix"
    ) as mock_ai, patch(
        "app.services.fix_workflow_service.validate_fixed_code"
    ) as mock_validation, patch(
        "app.services.fix_workflow_service.run_automated_tests"
    ) as mock_tests, patch(
        "app.services.fix_workflow_service.create_fix_pull_request"
    ) as mock_github:

        setup_successful_mocks(
            mock_ai,
            mock_validation,
            mock_tests,
            mock_github
        )

        result = run_fix_workflow(
            code="def divide(a, b):\n    return a / b",
            filename="division.py",
            review_result=get_review_result(),
            test_code="def test_dummy():\n    assert True"
        )

        assert result["status"] == "passed"
        assert result["github"] is None

        mock_github.assert_not_called()


def test_github_publish_requires_developer_approval():

    with patch(
        "app.services.fix_workflow_service.generate_code_fix"
    ) as mock_ai, patch(
        "app.services.fix_workflow_service.validate_fixed_code"
    ) as mock_validation, patch(
        "app.services.fix_workflow_service.run_automated_tests"
    ) as mock_tests, patch(
        "app.services.fix_workflow_service.create_fix_pull_request"
    ) as mock_github:

        setup_successful_mocks(
            mock_ai,
            mock_validation,
            mock_tests,
            mock_github
        )

        result = run_fix_workflow(
            code="def divide(a, b):\n    return a / b",
            filename="division.py",
            review_result=get_review_result(),
            test_code="def test_dummy():\n    assert True",
            publish_to_github=True,
            repository_full_name="Pranay25-cyber/newpragnaschool",
            original_pr_number=1
        )

        assert result["status"] == "approval_required"
        assert result["developer_approval"]["required"] is True
        assert result["developer_approval"]["approved"] is False

        mock_github.assert_not_called()


def test_github_publish_is_blocked_when_developer_rejects():

    with patch(
        "app.services.fix_workflow_service.generate_code_fix"
    ) as mock_ai, patch(
        "app.services.fix_workflow_service.validate_fixed_code"
    ) as mock_validation, patch(
        "app.services.fix_workflow_service.run_automated_tests"
    ) as mock_tests, patch(
        "app.services.fix_workflow_service.create_fix_pull_request"
    ) as mock_github:

        setup_successful_mocks(
            mock_ai,
            mock_validation,
            mock_tests,
            mock_github
        )

        result = run_fix_workflow(
            code="def divide(a, b):\n    return a / b",
            filename="division.py",
            review_result=get_review_result(),
            test_code="def test_dummy():\n    assert True",
            publish_to_github=True,
            repository_full_name="Pranay25-cyber/newpragnaschool",
            original_pr_number=1,
            developer_approved=False
        )

        assert result["status"] == "approval_required"
        assert result["developer_approval"]["approved"] is False

        mock_github.assert_not_called()


def test_successful_validation_and_approved_fix_attempts_github_publish():

    with patch(
        "app.services.fix_workflow_service.generate_code_fix"
    ) as mock_ai, patch(
        "app.services.fix_workflow_service.validate_fixed_code"
    ) as mock_validation, patch(
        "app.services.fix_workflow_service.run_automated_tests"
    ) as mock_tests, patch(
        "app.services.fix_workflow_service.create_fix_pull_request"
    ) as mock_github:

        setup_successful_mocks(
            mock_ai,
            mock_validation,
            mock_tests,
            mock_github
        )

        result = run_fix_workflow(
            code="def divide(a, b):\n    return a / b",
            filename="division.py",
            review_result=get_review_result(),
            test_code="def test_dummy():\n    assert True",
            publish_to_github=True,
            repository_full_name="Pranay25-cyber/newpragnaschool",
            original_pr_number=1,
            developer_approved=True
        )

        assert mock_github.call_count == 1
        assert result["status"] == "passed"
        assert result["developer_approval"]["approved"] is True
        assert result["github"]["status"] == "success"


def test_invalid_review_result_does_not_publish_to_github():

    with patch(
        "app.services.fix_workflow_service.create_fix_pull_request"
    ) as mock_github:

        result = run_fix_workflow(
            code="def divide(a, b):\n    return a / b",
            filename="division.py",
            review_result={"issues": "invalid"},
            test_code="def test_dummy():\n    assert True",
            publish_to_github=True,
            developer_approved=True
        )

        assert result["status"] == "invalid_review_result"
        mock_github.assert_not_called()
