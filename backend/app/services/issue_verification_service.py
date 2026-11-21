
def verify_issue_line(issue, code):
    """
    Check whether an AI-reported issue has a valid source line.

    This is a basic evidence check, not proof that the
    reported bug is genuine.
    """

    line_number = issue.get("line_number")

    if line_number is None:
        return {
            "verified": False,
            "reason": "No source line number was provided."
        }

    lines = code.splitlines()

    if (
        isinstance(line_number, bool)
        or not isinstance(line_number, int)
        or line_number < 1
        or line_number > len(lines)
    ):
        return {
            "verified": False,
            "reason": "Reported line number is outside the source code."
        }

    source_line = lines[line_number - 1].strip()

    if not source_line:
        return {
            "verified": False,
            "reason": "Reported source line is empty."
        }

    return {
        "verified": True,
        "source_line": source_line,
        "reason": "Reported source line exists."
    }


def verify_review_issues(issues, code):
    """
    Verify the source-line references of all AI review issues.
    """

    results = []

    for issue in issues:
        verification = verify_issue_line(issue, code)

        results.append({
            "title": issue.get("title"),
            "line_number": issue.get("line_number"),
            **verification
        })

    return results


def match_issues_to_added_lines(issues, verification_results, file_diff):
    """
    Match verified AI findings to lines added in the pull request.

    Only findings whose line numbers match newly added lines
    are returned as GitHub comment candidates.
    """

    if not file_diff or not file_diff.get("patch_available"):
        return []

    added_positions = {
        item["line_number"]: item
        for item in file_diff.get("added_line_positions", [])
    }

    verified_by_line = {
        item.get("line_number"): item
        for item in verification_results
        if item.get("verified") is True
    }

    comment_candidates = []

    for issue in issues:

        line_number = issue.get("line_number")

        if isinstance(line_number, bool) or not isinstance(line_number, int):
            continue

        verification = verified_by_line.get(line_number)

        if not verification:
            continue

        added_line = added_positions.get(line_number)

        if not added_line:
            continue

        # Ensure the verified source line matches the added diff line.
        if verification.get("source_line") != added_line.get("content", "").strip():
            continue

        comment_candidates.append({
            "file_path": file_diff.get("filename"),
            "line_number": line_number,
            "diff_position": added_line["diff_position"],
            "severity": issue.get("severity"),
            "issue_type": issue.get("issue_type"),
            "title": issue.get("title"),
            "description": issue.get("description"),
            "suggestion": issue.get("suggestion"),
            "source_line": verification.get("source_line"),
        })

    return comment_candidates
