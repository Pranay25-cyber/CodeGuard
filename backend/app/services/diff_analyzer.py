
import re


def analyze_diff(patch):
    """
    Analyze a GitHub unified diff patch.

    Collects:
    - Added lines
    - Deleted lines
    - Addition and deletion counts
    - New-file line numbers
    - GitHub diff positions for added lines
    """

    added_lines = []
    deleted_lines = []
    added_line_positions = []

    additions_count = 0
    deletions_count = 0

    new_line_number = None
    diff_position = 0

    if not patch:
        return {
            "added_lines": [],
            "deleted_lines": [],
            "additions_count": 0,
            "deletions_count": 0,
            "added_line_positions": [],
        }

    for line in patch.splitlines():

        # Start of a new diff hunk.
        if line.startswith("@@"):
            match = re.match(
                r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@",
                line,
            )

            if match:
                new_line_number = int(match.group(1))
            else:
                new_line_number = None

            # Hunk headers are not counted as diff positions.
            continue

        # Ignore Git diff metadata.
        if line.startswith(
            (
                "diff ",
                "index ",
                "\\ No newline",
            )
        ):
            continue

        # Added line.
        if line.startswith("+"):
            diff_position += 1
            content = line[1:]

            added_lines.append(content)
            additions_count += 1

            if new_line_number is not None:
                added_line_positions.append(
                    {
                        "line_number": new_line_number,
                        "diff_position": diff_position,
                        "content": content,
                    }
                )

                new_line_number += 1

        # Deleted line.
        elif line.startswith("-"):
            diff_position += 1

            deleted_lines.append(line[1:])
            deletions_count += 1

        # Context line.
        elif line.startswith(" "):
            diff_position += 1

            if new_line_number is not None:
                new_line_number += 1

    return {
        "added_lines": added_lines,
        "deleted_lines": deleted_lines,
        "additions_count": additions_count,
        "deletions_count": deletions_count,
        "added_line_positions": added_line_positions,
    }


def analyze_changed_files(changed_files):
    """
    Analyze all changed files returned by the GitHub API.

    Returns a dictionary compatible with webhook_review_service.py.
    """

    analyzed_files = []

    total_additions = 0
    total_deletions = 0
    total_changes = 0

    for file in changed_files:

        patch = file.get("patch")

        diff_analysis = analyze_diff(patch)

        additions = diff_analysis["additions_count"]
        deletions = diff_analysis["deletions_count"]

        total_additions += additions
        total_deletions += deletions
        total_changes += additions + deletions

        analyzed_files.append(
            {
                "filename": file.get("filename"),
                "status": file.get("status"),
                "additions_count": additions,
                "deletions_count": deletions,
                "changes_count": file.get("changes", 0),
                "added_lines": diff_analysis["added_lines"],
                "deleted_lines": diff_analysis["deleted_lines"],
                "added_line_positions": diff_analysis[
                    "added_line_positions"
                ],
                "patch_available": patch is not None,
                "changes_available": patch is not None,
            }
        )

    return {
        "total_files": len(analyzed_files),
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "total_changes": total_changes,
        "files": analyzed_files,
    }
