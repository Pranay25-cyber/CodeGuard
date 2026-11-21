from app.services.ai_fix_service import generate_code_fix


# Deliberately buggy Python code
buggy_code = """
def divide(a, b):
    return a / b
"""


# Simulated AI review finding
review_result = {
    "summary": "The function has a division-by-zero risk.",
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


result = generate_code_fix(
    code=buggy_code,
    filename="division.py",
    review_result=review_result
)

print("\nAI FIX RESULT")
print("--------------------")
print("Status:", result["status"])
print("Summary:", result["changes_summary"])
print("\nCorrected Code:")
print(result["fixed_code"])