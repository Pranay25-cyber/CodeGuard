from app.services.fix_workflow_service import run_fix_workflow


# Original code containing a deliberate bug
buggy_code = """
def divide(a, b):
    return a / b
"""


# Simulated findings from Claude AI Code Review
review_result = {
    "summary": "Division by zero is not handled.",
    "overall_status": "issues_found",
    "issues": [
        {
            "line_number": 2,
            "issue_type": "runtime_error",
            "severity": "high",
            "description": "Division by zero can cause ZeroDivisionError.",
            "suggestion": "Check whether b is zero before division."
        }
    ]
}


# Tests that the corrected code must pass
test_code = """
from fixed_code import divide
import pytest


def test_normal_division():
    assert divide(10, 2) == 5


def test_division_by_zero():
    with pytest.raises(ValueError):
        divide(10, 0)

def test_negative_division():
    assert divide(-10, 2) == -5
"""


# Execute the complete AI fix workflow
result = run_fix_workflow(
    code=buggy_code,
    filename="division.py",
    review_result=review_result,
    test_code=test_code
)


print("\\nCOMPLETE AI FIX WORKFLOW")
print("=========================")

print("Overall status:", result["status"])
print("Message:", result.get("message"))

if result.get("changes_summary"):
    print("Changes:", result["changes_summary"])

if result.get("validation"):
    print("Validation:", result["validation"]["status"])

if result.get("automated_tests"):
    print("\nDOCKER TEST OUTPUT:")
    print(result["automated_tests"].get("test_output"))

    print("\nDOCKER ERROR OUTPUT:")
    print(result["automated_tests"].get("error_output"))

    print("\nDOCKER RETURN CODE:")
    print(result["automated_tests"].get("return_code"))