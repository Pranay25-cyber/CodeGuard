
from app.services.issue_verification_service import (
    match_issues_to_added_lines
)

issues = [
    {
        "line_number": 2,
        "severity": "medium",
        "issue_type": "logic",
        "title": "Inconsistent return type",
        "description": "Returns different types",
        "suggestion": "Raise ValueError"
    }
]

verification = [
    {
        "line_number": 2,
        "verified": True,
        "source_line": 'return "Cannot divide by zero"'
    }
]

diff = {
    "filename": "division.py",
    "patch_available": True,
    "added_line_positions": [
        {
            "line_number": 2,
            "diff_position": 3,
            "content": 'return "Cannot divide by zero"'
        }
    ]
}

result = match_issues_to_added_lines(
    issues,
    verification,
    diff
)

print(result)
