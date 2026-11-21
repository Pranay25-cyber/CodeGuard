
from app.services.ai_fix_service import generate_code_fix
from app.services.fix_validation_service import validate_fixed_code
from app.services.automated_test_service import run_automated_tests
from app.github.github_fix_service import create_fix_pull_request


def run_fix_workflow(
    code: str,
    filename: str,
    review_result: dict,
    test_code: str,
    timeout: int = 30,
    publish_to_github: bool = False,
    repository_full_name: str = None,
    original_pr_number: int = None,
    developer_approved: bool = False
):
    """
    Complete AI Code Fix Workflow.

    1. Check AI review findings.
    2. Generate corrected code using Claude.
    3. Validate Python syntax, Ruff and Bandit.
    4. Execute automated tests inside Docker.
    5. Wait for developer approval.
    6. Publish the approved fix to GitHub if requested.

    GitHub publishing is disabled by default.
    Developer approval is required before publishing.
    """

    # --------------------------------------------------
    # STEP 1: CHECK REVIEW FINDINGS
    # --------------------------------------------------

    if not isinstance(review_result, dict):
        return {
            "status": "invalid_review_result",
            "message": "Review result must be a dictionary."
        }

    issues = review_result.get("issues", [])

    if not isinstance(issues, list):
        return {
            "status": "invalid_review_result",
            "message": "Review issues must be provided as a list."
        }

    if not issues:
        return {
            "status": "no_fix_needed",
            "message": "No issues were identified by the AI reviewer."
        }

    # --------------------------------------------------
    # STEP 2: GENERATE AI FIX
    # --------------------------------------------------

    try:
        fix_result = generate_code_fix(
            code=code,
            filename=filename,
            review_result=review_result
        )

    except Exception as error:
        return {
            "status": "fix_generation_failed",
            "message": "Claude could not generate the corrected code.",
            "error": str(error)
        }

    if not isinstance(fix_result, dict):
        return {
            "status": "fix_generation_failed",
            "message": "AI returned an invalid response."
        }

    fixed_code = fix_result.get("fixed_code")

    if not isinstance(fixed_code, str) or not fixed_code.strip():
        return {
            "status": "fix_generation_failed",
            "message": "AI did not generate valid corrected code."
        }

    changes_summary = fix_result.get(
        "changes_summary",
        "AI-generated code correction."
    )

    # --------------------------------------------------
    # STEP 3: STATIC VALIDATION
    # --------------------------------------------------

    try:
        validation_result = validate_fixed_code(fixed_code)

    except Exception as error:
        return {
            "status": "validation_error",
            "filename": filename,
            "changes_summary": changes_summary,
            "message": "An error occurred during static validation.",
            "error": str(error),
            "automated_tests": None,
            "github": None,
            "fixed_code": fixed_code
        }

    if (
        not isinstance(validation_result, dict)
        or validation_result.get("status") != "passed"
    ):
        return {
            "status": "validation_failed",
            "filename": filename,
            "changes_summary": changes_summary,
            "message": "Generated code failed static validation.",
            "validation": validation_result,
            "automated_tests": None,
            "github": None,
            "fixed_code": fixed_code
        }

    # --------------------------------------------------
    # STEP 4: DOCKER AUTOMATED TESTING
    # --------------------------------------------------

    try:
        test_result = run_automated_tests(
            fixed_code=fixed_code,
            test_code=test_code,
            filename=filename,
            timeout=timeout
        )

    except Exception as error:
        return {
            "status": "testing_error",
            "filename": filename,
            "changes_summary": changes_summary,
            "message": "Docker automated testing could not execute.",
            "validation": validation_result,
            "automated_tests": {
                "status": "error",
                "test_output": "",
                "error_output": str(error),
                "return_code": None
            },
            "github": None,
            "fixed_code": fixed_code
        }

    # --------------------------------------------------
    # STEP 5: CHECK AUTOMATED TEST RESULTS
    # --------------------------------------------------

    if (
        not isinstance(test_result, dict)
        or test_result.get("status") != "passed"
    ):
        return {
            "status": "tests_failed",
            "filename": filename,
            "changes_summary": changes_summary,
            "message": "Generated code failed Docker automated tests.",
            "validation": validation_result,
            "automated_tests": test_result,
            "failure_details": {
                "status": (
                    test_result.get("status")
                    if isinstance(test_result, dict)
                    else "invalid_test_result"
                ),
                "return_code": (
                    test_result.get("return_code")
                    if isinstance(test_result, dict)
                    else None
                ),
                "test_output": (
                    test_result.get("test_output")
                    if isinstance(test_result, dict)
                    else ""
                ),
                "error_output": (
                    test_result.get("error_output")
                    if isinstance(test_result, dict)
                    else "Invalid automated test result."
                )
            },
            "github": None,
            "fixed_code": fixed_code
        }

    # --------------------------------------------------
    # STEP 6: PREPARE SUCCESSFUL RESULT
    # --------------------------------------------------

    result = {
        "status": "passed",
        "filename": filename,
        "changes_summary": changes_summary,
        "validation": validation_result,
        "automated_tests": test_result,
        "developer_approval": {
            "required": True,
            "approved": False
        },
        "github": None,
        "fixed_code": fixed_code,
        "message": (
            "AI-generated fix passed all validation checks "
            "and Docker automated tests."
        )
    }

    # --------------------------------------------------
    # STEP 7: CHECK GITHUB PUBLISHING OPTION
    # --------------------------------------------------

    if not publish_to_github:
        result["message"] = (
            "AI-generated fix passed all validation checks. "
            "GitHub publishing was not requested."
        )
        return result

    if not repository_full_name:
        result["status"] = "github_configuration_error"
        result["message"] = "Repository name is required."
        return result

    if (
        isinstance(original_pr_number, bool)
        or not isinstance(original_pr_number, int)
        or original_pr_number <= 0
    ):
        result["status"] = "github_configuration_error"
        result["message"] = (
            "A valid original Pull Request number is required."
        )
        return result

    # --------------------------------------------------
    # STEP 8: REQUIRE DEVELOPER APPROVAL
    # --------------------------------------------------

    if developer_approved is not True:
        result["status"] = "approval_required"
        result["message"] = (
            "The fix passed validation and Docker tests. "
            "Developer approval is required before GitHub publishing."
        )
        return result

    result["developer_approval"]["approved"] = True

    # --------------------------------------------------
    # STEP 9: PUBLISH APPROVED FIX TO GITHUB
    # --------------------------------------------------

    try:
        github_result = create_fix_pull_request(
            repository_full_name=repository_full_name,
            original_pr_number=original_pr_number,
            filename=filename,
            fixed_code=fixed_code,
            changes_summary=changes_summary
        )

        result["github"] = github_result

        result["message"] = (
            "AI-generated fix passed validation and Docker tests. "
            "Developer approved the fix and GitHub publishing was attempted."
        )

        return result

    except Exception as error:
        result["status"] = "github_publish_failed"
        result["message"] = (
            "Code passed validation and testing, "
            "but GitHub publishing failed."
        )
        result["github"] = {
            "status": "failed",
            "error": str(error)
        }

        return result
