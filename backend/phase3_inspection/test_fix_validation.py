
import pytest

from app.services.fix_validation_service import (
    validate_python_syntax,
    run_ruff,
    run_bandit,
    validate_fixed_code,
)


def test_valid_python_syntax():
    code = """
def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
"""
    result = validate_python_syntax(code)
    assert result["passed"] is True


def test_invalid_python_syntax():
    code = "def divide(a, b)"
    result = validate_python_syntax(code)
    assert result["passed"] is False


def test_ruff_validation():
    code = "x = 10\n"
    result = run_ruff(code)
    assert isinstance(result, dict)
    assert "passed" in result


def test_bandit_validation():
    code = """
def divide(a, b):
    return a / b
"""
    result = run_bandit(code)
    assert isinstance(result, dict)
    assert "passed" in result


def test_complete_fix_validation():
    code = """
def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
"""
    result = validate_fixed_code(code)

    assert result["status"] == "passed"
    assert result["syntax"]["passed"] is True
    assert result["ruff"]["passed"] is True
    assert result["bandit"]["passed"] is True
