import pytest

from app.services.duplicate_detection_service import (
    normalize_description,
    get_issue_fingerprint,
    remove_duplicate_issues
)


def test_normalize_description():
    result = normalize_description(
        "  Unused   Import, Detected! "
    )

    assert result == "unused import detected"


def test_same_issue_has_same_fingerprint():
    issue1 = {
        "file_path": "app.py",
        "line_number": 5,
        "source": "ruff",
        "code": "F401",
        "message": "Unused import detected"
    }

    issue2 = {
        "file_path": "app.py",
        "line_number": 5,
        "source": "ruff",
        "code": "F401",
        "message": "Unused import detected"
    }

    assert get_issue_fingerprint(issue1) == get_issue_fingerprint(issue2)


def test_different_sources_are_not_duplicates():
    ruff_issue = {
        "file_path": "app.py",
        "line_number": 5,
        "source": "ruff",
        "code": "F401",
        "message": "Unused import detected"
    }

    ai_issue = {
        "file_path": "app.py",
        "line_number": 5,
        "source": "ai",
        "description": "Unused import detected"
    }

    assert (
        get_issue_fingerprint(ruff_issue)
        != get_issue_fingerprint(ai_issue)
    )


def test_remove_exact_duplicates():
    issue1 = {
        "file_path": "app.py",
        "line_number": 5,
        "source": "ruff",
        "code": "F401",
        "message": "Unused import detected"
    }

    issue2 = {
        "file_path": "app.py",
        "line_number": 5,
        "source": "ruff",
        "code": "F401",
        "message": "Unused import detected"
    }

    result = remove_duplicate_issues([issue1, issue2])

    assert len(result) == 1


def test_different_lines_are_not_duplicates():
    issue1 = {
        "file_path": "app.py",
        "line_number": 5,
        "source": "ruff",
        "code": "F401",
        "message": "Unused import detected"
    }

    issue2 = {
        "file_path": "app.py",
        "line_number": 8,
        "source": "ruff",
        "code": "F401",
        "message": "Unused import detected"
    }

    result = remove_duplicate_issues([issue1, issue2])

    assert len(result) == 2


def test_original_issues_are_not_modified():
    issue = {
        "file_path": "app.py",
        "line_number": 5,
        "source": "ruff",
        "code": "F401",
        "message": "Unused import detected"
    }

    original = issue.copy()

    remove_duplicate_issues([issue])

    assert issue == original


def test_different_rules_are_not_duplicates():
    issue1 = {
        "file_path": "app.py",
        "line_number": 5,
        "source": "ruff",
        "code": "F401",
        "message": "Unused import detected"
    }

    issue2 = {
        "file_path": "app.py",
        "line_number": 5,
        "source": "ruff",
        "code": "F811",
        "message": "Unused import detected"
    }

    result = remove_duplicate_issues([issue1, issue2])

    assert len(result) == 2


def test_description_whitespace_and_punctuation_are_normalized():
    issue1 = {
        "file_path": "app.py",
        "line_number": 5,
        "source": "ruff",
        "code": "F401",
        "message": "Unused import detected!"
    }

    issue2 = {
        "file_path": "app.py",
        "line_number": 5,
        "source": "ruff",
        "code": "F401",
        "message": " unused   import detected "
    }

    result = remove_duplicate_issues([issue1, issue2])

    assert len(result) == 1