
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ANALYZER_TIMEOUT_SECONDS = 15


def run_analyzer(command, analyzer_name):
    """Execute a static analysis tool and validate its JSON output."""

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=ANALYZER_TIMEOUT_SECONDS
        )

    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{analyzer_name} analysis timed out."
        ) from exc

    except OSError as exc:
        raise RuntimeError(
            f"Unable to execute {analyzer_name}: {exc}"
        ) from exc

    # Exit codes 0 and 1 are valid:
    # 0 = no findings
    # 1 = findings detected
    if result.returncode not in (0, 1):
        raise RuntimeError(
            f"{analyzer_name} failed with exit code "
            f"{result.returncode}: {result.stderr.strip()}"
        )

    try:
        report = json.loads(result.stdout)

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{analyzer_name} returned invalid JSON."
        ) from exc

    return report


def run_ruff(code):
    """Check Python code quality using Ruff."""

    with tempfile.TemporaryDirectory() as temp_dir:

        file_path = Path(temp_dir) / "review_code.py"

        file_path.write_text(
            code,
            encoding="utf-8"
        )

        report = run_analyzer(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                str(file_path),
                "--output-format",
                "json"
            ],
            "Ruff"
        )

        if not isinstance(report, list):
            raise RuntimeError(
                "Ruff returned an invalid report format."
            )

        return report


def run_bandit(code):
    """Check Python code security using Bandit."""

    with tempfile.TemporaryDirectory() as temp_dir:

        file_path = Path(temp_dir) / "review_code.py"

        file_path.write_text(
            code,
            encoding="utf-8"
        )

        report = run_analyzer(
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

        if not isinstance(report, dict):
            raise RuntimeError(
                "Bandit returned an invalid report format."
            )

        issues = report.get("results")

        if not isinstance(issues, list):
            raise RuntimeError(
                "Bandit report does not contain a valid results list."
            )

        return issues


def analyze_python_code(code):
    """Run Ruff and Bandit on Python code."""

    return {
        "ruff_issues": run_ruff(code),
        "bandit_issues": run_bandit(code)
    }
