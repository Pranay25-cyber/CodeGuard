import re


def normalize_description(description):
    """
    Normalize issue descriptions for duplicate comparison.
    """

    if not description:
        return ""

    normalized = description.lower().strip()

    # Remove extra whitespace
    normalized = re.sub(r"\s+", " ", normalized)

    # Remove punctuation
    normalized = re.sub(r"[^\w\s]", "", normalized)

    return normalized


def get_issue_fingerprint(issue):
    """
    Create a fingerprint to identify potential duplicate findings.
    """

    source = issue.get("source", "ai")
    rule_id = issue.get("rule_id") or issue.get("code") or issue.get("test_id")

    description = (
        issue.get("description")
        or issue.get("message")
        or issue.get("issue_text")
        or ""
    )

    return (
        issue.get("file_path"),
        issue.get("line_number"),
        source,
        rule_id,
        normalize_description(description)
    )


def remove_duplicate_issues(issues):
    """
    Remove exact duplicate findings while preserving their original data.

    Findings from different sources are kept separate.
    """

    unique_issues = []
    seen_fingerprints = set()

    for issue in issues:

        fingerprint = get_issue_fingerprint(issue)

        if fingerprint in seen_fingerprints:
            continue

        seen_fingerprints.add(fingerprint)
        unique_issues.append(issue)

    return unique_issues