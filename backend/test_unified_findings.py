
from app.services.review_storage_service import collect_unified_issues


def test_collect_unified_issues_from_all_three_sources():
    review_results = [
        {
            "filename": "example.py",
            "ai_review": {
                "issues": [
                    {
                        "title": "Possible logic error",
                        "severity": "high",
                        "issue_type": "bug",
                        "line_number": 3,
                        "description": "Incorrect calculation.",
                        "suggestion": "Correct the calculation."
                    }
                ]
            },
            "static_analysis": {
                "ruff_issues": [
                    {
                        "code": "F401",
                        "message": "Unused import",
                        "location": {"row": 1, "column": 1}
                    }
                ],
                "bandit_issues": [
                    {
                        "test_id": "B105",
                        "issue_text": "Possible hardcoded password",
                        "line_number": 2,
                        "issue_severity": "HIGH"
                    }
                ]
            }
        }
    ]

    findings = collect_unified_issues(review_results)

    sources = {item["source"] for item in findings}

    assert sources == {"ai", "ruff", "bandit"}
    assert len(findings) == 3

    for item in findings:
        assert item["file_path"] == "example.py"
        assert item["line_number"] > 0
        assert item["description"]
