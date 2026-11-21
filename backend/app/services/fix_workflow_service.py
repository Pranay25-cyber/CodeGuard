import logging

from app.services.ai_fix_service import generate_code_fix
from app.services.fix_validation_service import validate_fixed_code


logger = logging.getLogger(__name__)

# One initial generation plus at most three correction retries.
MAX_CORRECTION_RETRIES = 3


def run_fix_workflow(
    code: str,
    filename: str,
    review_result: dict,
    repository_files: dict[str, str],
    timeout: int = 30,
    publish_to_github: bool = False,
    repository_full_name: str = None,
    original_pr_number: int = None,
    developer_approved: bool = False,
    expected_head_sha: str = None,
):
    """
    Generate, statically validate, and prepare an AI fix proposal.

    Automated repository tests are optional and are not executed.
    This function never publishes code to GitHub.
    """
    del timeout  # Retained for compatibility with existing callers.

    if not isinstance(review_result, dict):
        return {
            "status": "invalid_review_result",
            "message": "Review result must be a dictionary.",
        }

    issues = review_result.get("issues", [])
    if not isinstance(issues, list):
        return {
            "status": "invalid_review_result",
            "message": "Review issues must be provided as a list.",
        }
    if not issues:
        return {
            "status": "no_fix_needed",
            "message": "No issues were identified by the AI reviewer.",
        }

    if not isinstance(filename, str) or not filename.strip():
        return {
            "status": "invalid_filename",
            "message": "A valid filename is required.",
        }
    if not isinstance(code, str) or not code.strip():
        return {
            "status": "invalid_source_code",
            "message": "Original source code cannot be empty.",
        }
    if not isinstance(repository_files, dict):
        return {
            "status": "invalid_repository_files",
            "message": "Repository snapshot must be a dictionary.",
        }

    for path, content in repository_files.items():
        if not isinstance(path, str) or not isinstance(content, str):
            return {
                "status": "invalid_repository_files",
                "message": "Repository file paths and contents must be strings.",
            }

    if repository_files and filename not in repository_files:
        return {
            "status": "selected_file_missing",
            "message": "The selected file is missing from the repository snapshot.",
        }

    original_code = code
    current_code = code
    validation_result = None
    changes_summary = "AI-generated code correction."
    total_generations = MAX_CORRECTION_RETRIES + 1

    for generation_number in range(1, total_generations + 1):
        is_retry = generation_number > 1

        try:
            fix_result = generate_code_fix(
                code=current_code,
                filename=filename,
                review_result=review_result,
                test_code="",
                validation_errors=validation_result if is_retry else None,
                original_code=original_code,
            )
        except Exception as error:
            logger.exception(
                "AI code fix generation failed for %s (attempt %s)",
                filename,
                generation_number,
            )
            return {
                "status": "fix_generation_failed",
                "filename": filename,
                "message": "Claude could not generate the corrected code.",
                "error": str(error),
                "correction_attempt": generation_number,
            }

        if not isinstance(fix_result, dict):
            return {
                "status": "fix_generation_failed",
                "filename": filename,
                "message": "AI returned an invalid response.",
            }

        fixed_code = fix_result.get("fixed_code")
        if not isinstance(fixed_code, str) or not fixed_code.strip():
            return {
                "status": "fix_generation_failed",
                "filename": filename,
                "message": "AI did not generate valid corrected code.",
            }

        summary = fix_result.get("changes_summary")
        if isinstance(summary, str) and summary.strip():
            changes_summary = summary

        current_code = fixed_code

        try:
            validation_result = validate_fixed_code(current_code)
        except Exception as error:
            logger.exception("Static validation raised an error for %s", filename)
            return {
                "status": "validation_error",
                "filename": filename,
                "changes_summary": changes_summary,
                "message": "An error occurred during static validation.",
                "error": str(error),
                "fixed_code": current_code,
                "correction_attempt": generation_number,
                "automated_tests": {
                    "status": "skipped",
                    "message": "Automated tests are not required.",
                },
            }

        if (
            isinstance(validation_result, dict)
            and validation_result.get("status") == "passed"
        ):
            logger.info(
                "AI fix passed static validation for %s on generation %s.",
                filename,
                generation_number,
            )
            break

        logger.warning(
            "Static validation failed for %s on generation %s of %s.",
            filename,
            generation_number,
            total_generations,
        )

        if generation_number < total_generations:
            logger.info(
                "Sending static-validation errors to Claude for correction: %s",
                filename,
            )

    if (
        not isinstance(validation_result, dict)
        or validation_result.get("status") != "passed"
    ):
        return {
            "status": "validation_failed",
            "filename": filename,
            "changes_summary": changes_summary,
            "message": (
                "Generated code still failed static validation after "
                f"{total_generations} generations. No approval proposal was created."
            ),
            "validation": validation_result,
            "correction_attempts": MAX_CORRECTION_RETRIES,
            "automated_tests": {
                "status": "skipped",
                "message": "Automated tests are not required.",
            },
            "fixed_code": current_code,
        }

    test_result = {
        "status": "skipped",
        "message": (
            "Repository tests are optional. "
            "The AI fix workflow does not require existing test files."
        ),
        "test_output": "",
        "error_output": "",
        "return_code": None,
    }

    result = {
        "status": "passed",
        "filename": filename,
        "repository": repository_full_name,
        "original_pr_number": original_pr_number,
        "original_commit_sha": expected_head_sha,
        "changes_summary": changes_summary,
        "validation": validation_result,
        "automated_tests": test_result,
        "discovered_test_files": [],
        "developer_approval": {
            "required": True,
            "approved": False,
            "status": "pending",
        },
        "github": {
            "status": "not_published",
            "message": (
                "The corrected code is ready for developer approval. "
                "GitHub publishing has not happened yet."
            ),
        },
        "fixed_code": current_code,
        "message": (
            "AI-generated fix passed static validation. "
            "Automated tests were skipped because they are optional. "
            "Awaiting developer approval."
        ),
        "correction_generations": generation_number,
        "correction_retries": generation_number - 1,
    }

    if publish_to_github or developer_approved:
        logger.warning(
            "Direct GitHub publishing was requested through the fix-generation "
            "workflow. Publishing was blocked."
        )
        result["message"] = (
            "The fix passed static validation, but publishing must happen "
            "through the developer approval endpoint."
        )

    return result
