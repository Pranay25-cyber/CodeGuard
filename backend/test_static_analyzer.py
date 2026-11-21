
import subprocess
from unittest.mock import patch

import pytest

from app.services.static_analyzer import (
    run_ruff,
    run_bandit,
    analyze_python_code,
)


def test_ruff_detects_unused_import():
    code = """
import os

def hello():
    return "Hello"
"""

    issues = run_ruff(code)

    assert isinstance(issues, list)
    assert any(
        issue.get("code") == "F401"
        for issue in issues
    )


def test_bandit_detects_hardcoded_password():
    code = """
password = "admin123"
"""

    issues = run_bandit(code)

    assert isinstance(issues, list)
    assert any(
        issue.get("test_id") == "B105"
        for issue in issues
    )


def test_analyze_python_code_returns_expected_structure():
    code = """
def add(a, b):
    return a + b
"""

    result = analyze_python_code(code)

    assert isinstance(result, dict)
    assert "ruff_issues" in result
    assert "bandit_issues" in result

    assert isinstance(result["ruff_issues"], list)
    assert isinstance(result["bandit_issues"], list)


def test_clean_code_has_no_static_analysis_issues():
    code = """
def add(a: int, b: int) -> int:
    return a + b
"""

    result = analyze_python_code(code)

    assert result["ruff_issues"] == []
    assert result["bandit_issues"] == []


def test_ruff_timeout_is_reported():
    with patch(
        "app.services.static_analyzer.subprocess.run",
        side_effect=subprocess.TimeoutExpired(
            cmd="ruff",
            timeout=15
        )
    ):
        with pytest.raises(RuntimeError):
            run_ruff("print('Hello')")


def test_bandit_invalid_json_is_reported():
    mock_result = subprocess.CompletedProcess(
        args=["bandit"],
        returncode=0,
        stdout="Invalid JSON",
        stderr=""
    )

    with patch(
        "app.services.static_analyzer.subprocess.run",
        return_value=mock_result
    ):
        with pytest.raises(RuntimeError):
            run_bandit("print('Hello')")
