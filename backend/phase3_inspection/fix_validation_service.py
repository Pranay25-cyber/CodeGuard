
import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path


VALIDATION_TIMEOUT_SECONDS = 30


def validate_python_syntax(code: str):
    """Check whether generated Python code has valid syntax."""

    if not isinstance(code, str) or not code.strip():
        return {
            "passed": False,
            "message": "Python code cannot be empty."
        }

    try:
        ast.parse(code)

        return {
            "passed": True,
            "message": "Python syntax is valid."
        }

    except SyntaxError as error:
        return {
            "passed": False,
            "message": str(error)
        }


def run_analyzer(command, analyzer_name):
    """Execute an analyzer and validate its JSON output."""

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=VALIDATION_TIMEOUT_SECONDS
        )

    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "issues": [],
            "errors": f"{analyzer_name} analysis timed out."
        }

    except OSError as error:
        return {
            "passed": False,
            "issues": [],
            "errors": f"Unable to execute {analyzer_name}: {error}"
        }

    if result.returncode not in (0, 1):
        return {
            "passed": False,
            "issues": [],
            "errors": (
                f"{analyzer_name} failed with exit code "
                f"{result.returncode}: {result.stderr.strip()}"
            )
        }

    try:
        report = json.loads(result.stdout)

    except json.JSONDecodeError:
        return {
            "passed": False,
            "issues": [],
            "errors": f"{analyzer_name} returned invalid JSON."
        }

    if analyzer_name == "Ruff":
        valid_format = isinstance(report, list)
    else:
        valid_format = (
            isinstance(report, dict)
            and isinstance(report.get("results"), list)
        )

    if not valid_format:
        return {
            "passed": False,
            "issues": [],
            "errors": f"{analyzer_name} returned an invalid report format."
        }

    if analyzer_name == "Ruff":
        issues = report
    else:
        issues = report["results"]

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "errors": result.stderr.strip()
    }


def run_ruff(code: str):
    """Check generated Python code using Ruff."""

    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = Path(temp_dir) / "fixed_code.py"
        file_path.write_text(code, encoding="utf-8")

        return run_analyzer(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--output-format",
                "json",
                str(file_path)
            ],
            "Ruff"
        )


def run_bandit(code: str):
    """Check generated Python code using Bandit."""

    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = Path(temp_dir) / "fixed_code.py"
        file_path.write_text(code, encoding="utf-8")

        return run_analyzer(
            [
                sys.executable,
                "-m",
                "bandit",
                "-f",
                "json",
                str(file_path)
            ],
            "Bandit"
        )


def validate_fixed_code(code: str):
    """Run syntax, Ruff and Bandit validation."""

    syntax_result = validate_python_syntax(code)

    if not syntax_result["passed"]:
        return {
            "status": "failed",
            "syntax": syntax_result,
            "ruff": None,
            "bandit": None
        }

    ruff_result = run_ruff(code)
    bandit_result = run_bandit(code)

    all_passed = (
        ruff_result["passed"]
        and bandit_result["passed"]
    )

    return {
        "status": "passed" if all_passed else "failed",
        "syntax": syntax_result,
        "ruff": ruff_result,
        "bandit": bandit_result
    }
