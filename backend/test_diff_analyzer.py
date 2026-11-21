
import pytest

from app.services.diff_analyzer import (
    analyze_diff,
    analyze_changed_files,
)


def test_analyze_diff_with_added_lines():
    patch = """@@ -1,2 +1,4 @@
 line_one = 10
+line_two = 20
+line_three = 30
 line_four = 40
"""

    result = analyze_diff(patch)

    assert result["additions_count"] == 2
    assert result["deletions_count"] == 0

    assert result["added_lines"] == [
        "line_two = 20",
        "line_three = 30",
    ]

    assert result["added_line_positions"] == [
        {
            "line_number": 2,
            "diff_position": 2,
            "content": "line_two = 20",
        },
        {
            "line_number": 3,
            "diff_position": 3,
            "content": "line_three = 30",
        },
    ]


def test_analyze_diff_with_deleted_lines():
    patch = """@@ -1,3 +1,1 @@
 line_one = 10
-line_two = 20
-line_three = 30
 line_four = 40
"""

    result = analyze_diff(patch)

    assert result["additions_count"] == 0
    assert result["deletions_count"] == 2

    assert result["deleted_lines"] == [
        "line_two = 20",
        "line_three = 30",
    ]


def test_analyze_diff_with_added_and_deleted_lines():
    patch = """@@ -1,2 +1,2 @@
 value = 10
-value = 20
+value = 30
"""

    result = analyze_diff(patch)

    assert result["additions_count"] == 1
    assert result["deletions_count"] == 1

    assert result["added_lines"] == ["value = 30"]
    assert result["deleted_lines"] == ["value = 20"]

    assert result["added_line_positions"] == [
        {
            "line_number": 2,
            "diff_position": 3,
            "content": "value = 30",
        }
    ]


def test_analyze_diff_with_multiple_hunks():
    patch = """@@ -1,2 +1,3 @@
 first = 10
+second = 20
 third = 30
@@ -10,2 +11,3 @@
 tenth = 100
+eleventh = 110
 twelfth = 120
"""

    result = analyze_diff(patch)

    assert result["additions_count"] == 2

    assert result["added_line_positions"] == [
        {
            "line_number": 2,
            "diff_position": 2,
            "content": "second = 20",
        },
        {
            "line_number": 12,
            "diff_position": 5,
            "content": "eleventh = 110",
        },
    ]


def test_analyze_diff_with_empty_patch():
    result = analyze_diff(None)

    assert result == {
        "added_lines": [],
        "deleted_lines": [],
        "additions_count": 0,
        "deletions_count": 0,
        "added_line_positions": [],
    }


def test_analyze_diff_with_empty_string():
    result = analyze_diff("")

    assert result["added_lines"] == []
    assert result["deleted_lines"] == []
    assert result["additions_count"] == 0
    assert result["deletions_count"] == 0


def test_analyze_diff_with_no_newline_metadata():
    patch = r"""@@ -1,1 +1,2 @@
 first = 10
+second = 20
\ No newline at end of file
"""

    result = analyze_diff(patch)

    assert result["additions_count"] == 1
    assert result["added_lines"] == ["second = 20"]


def test_analyze_diff_with_metadata():
    patch = """diff --git a/example.py b/example.py
index 1234567..abcdefg 100644
@@ -1,1 +1,2 @@
 first = 10
+second = 20
"""

    result = analyze_diff(patch)

    assert result["additions_count"] == 1
    assert result["added_lines"] == ["second = 20"]


def test_analyze_diff_with_malformed_hunk():
    patch = """@@ invalid hunk @@
+new_line = 100
"""

    result = analyze_diff(patch)

    assert result["additions_count"] == 1
    assert result["added_lines"] == ["new_line = 100"]

    # No reliable new-file line number is available.
    assert result["added_line_positions"] == []


def test_analyze_changed_files():
    changed_files = [
        {
            "filename": "example.py",
            "status": "modified",
            "changes": 3,
            "patch": """@@ -1,2 +1,3 @@
 first = 10
+second = 20
-third = 30
""",
        }
    ]

    result = analyze_changed_files(changed_files)

    assert result["total_files"] == 1
    assert result["total_additions"] == 1
    assert result["total_deletions"] == 1
    assert result["total_changes"] == 2

    file_result = result["files"][0]

    assert file_result["filename"] == "example.py"
    assert file_result["status"] == "modified"
    assert file_result["additions_count"] == 1
    assert file_result["deletions_count"] == 1
    assert file_result["patch_available"] is True
    assert file_result["changes_available"] is True


def test_analyze_changed_files_without_patch():
    changed_files = [
        {
            "filename": "image.png",
            "status": "added",
            "changes": 0,
        }
    ]

    result = analyze_changed_files(changed_files)

    assert result["total_files"] == 1
    assert result["total_additions"] == 0
    assert result["total_deletions"] == 0

    file_result = result["files"][0]

    assert file_result["filename"] == "image.png"
    assert file_result["patch_available"] is False
    assert file_result["changes_available"] is False


def test_analyze_changed_files_multiple_files():
    changed_files = [
        {
            "filename": "first.py",
            "status": "modified",
            "changes": 2,
            "patch": """@@ -1,1 +1,2 @@
 first = 10
+second = 20
""",
        },
        {
            "filename": "second.py",
            "status": "modified",
            "changes": 2,
            "patch": """@@ -1,2 +1,1 @@
 first = 10
-second = 20
""",
        },
    ]

    result = analyze_changed_files(changed_files)

    assert result["total_files"] == 2
    assert result["total_additions"] == 1
    assert result["total_deletions"] == 1
    assert result["total_changes"] == 2

    assert len(result["files"]) == 2
