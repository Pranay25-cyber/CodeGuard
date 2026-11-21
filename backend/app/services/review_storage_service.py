
from sqlalchemy.orm import Session

from app.database.models import (
    Repository,
    GitHubInstallation,
    PullRequest,
    Review,
    ReviewIssue,
    ReviewFile
)

from app.services.duplicate_detection_service import (
    remove_duplicate_issues
)


def get_ruff_severity(rule_code):
    """Map Ruff rule codes to an initial review severity."""

    if not rule_code:
        return "low"

    if rule_code.startswith("S"):
        return "high"

    if rule_code in {"F821", "F822", "F823", "F831", "E999"}:
        return "high"

    if rule_code.startswith("F"):
        return "medium"

    return "low"


def get_bandit_severity(severity):
    """Normalize Bandit severity."""

    severity = str(severity or "medium").lower()

    if severity in {"low", "medium", "high", "critical"}:
        return severity

    return "medium"


def collect_unified_issues(review_results):
    """Collect Claude AI, Ruff and Bandit findings."""

    all_issues = []

    for file_result in review_results:

        if not isinstance(file_result, dict):
            continue

        filename = file_result.get("filename")

        if not filename:
            continue

        # Claude AI findings
        ai_review = file_result.get("ai_review", {})

        if isinstance(ai_review, dict):

            for finding in ai_review.get("issues", []):

                if not isinstance(finding, dict):
                    continue

                all_issues.append({
                    "file_path": filename,
                    "line_number": finding.get("line_number"),
                    "source": "ai",
                    "rule_id": (
                        finding.get("rule_id")
                        or finding.get("code")
                    ),
                    "issue_type": finding.get(
                        "issue_type", "general"
                    ),
                    "description": finding.get(
                        "description", ""
                    ),
                    "issue": finding
                })

        static_analysis = file_result.get(
            "static_analysis", {}
        )

        if not isinstance(static_analysis, dict):
            continue

        # Ruff findings
        ruff_findings = static_analysis.get(
            "ruff_issues", []
        )

        if isinstance(ruff_findings, list):

            for finding in ruff_findings:

                if not isinstance(finding, dict):
                    continue

                code = finding.get("code") or "RUFF"
                message = finding.get("message", "")

                location = finding.get("location", {})

                if not isinstance(location, dict):
                    location = {}

                line_number = location.get("row")

                description = f"{code}: {message}"

                normalized_finding = {
                    "line_number": line_number,
                    "issue_type": "quality",
                    "severity": get_ruff_severity(code),
                    "description": description,
                    "suggestion": (
                        "Review the Ruff rule and apply "
                        "the recommended correction."
                    )
                }

                all_issues.append({
                    "file_path": filename,
                    "line_number": line_number,
                    "source": "ruff",
                    "rule_id": code,
                    "issue_type": "quality",
                    "description": description,
                    "issue": normalized_finding
                })

        # Bandit findings
        bandit_findings = static_analysis.get(
            "bandit_issues", []
        )

        if isinstance(bandit_findings, list):

            for finding in bandit_findings:

                if not isinstance(finding, dict):
                    continue

                test_id = finding.get("test_id") or "BANDIT"
                test_name = finding.get("test_name", "")
                issue_text = finding.get("issue_text", "")
                line_number = finding.get("line_number")

                severity = get_bandit_severity(
                    finding.get("issue_severity")
                )

                description = (
                    f"{test_id} ({test_name}): {issue_text}"
                )

                normalized_finding = {
                    "line_number": line_number,
                    "issue_type": "security",
                    "severity": severity,
                    "description": description,
                    "suggestion": (
                        "Review this security finding and "
                        "replace unsafe code with a safer alternative."
                    )
                }

                all_issues.append({
                    "file_path": filename,
                    "line_number": line_number,
                    "source": "bandit",
                    "rule_id": test_id,
                    "issue_type": "security",
                    "description": description,
                    "issue": normalized_finding
                })

    return all_issues


def save_review_results(
    db: Session,
    github_repo_id: int,
    repository_name: str,
    repository_full_name: str,
    repository_url: str,
    pr_number: int,
    pr_title: str,
    pr_description: str | None,
    pr_status: str,
    commit_sha: str,
    review_results: list,
    diff_analysis: dict | None = None,
    installation_id: int | None = None
):
    """Save GitHub Pull Request review results."""

    try:

        # 1. Resolve repository ownership from the verified installation.
        installation = None

        if installation_id is not None:
            installation = (
                db.query(GitHubInstallation)
                .filter(
                    GitHubInstallation.installation_id == installation_id
                )
                .first()
            )

            if installation is None:
                raise ValueError(
                    "The GitHub installation is not registered in this application."
                )

        # Find or create the repository using GitHub's immutable repository ID.
        repository = db.query(Repository).filter(
            Repository.github_repo_id == github_repo_id
        ).first()

        if repository is None:
            repository = Repository(
                github_repo_id=github_repo_id,
                name=repository_name,
                full_name=repository_full_name,
                html_url=repository_url,
                user_id=installation.user_id if installation else None,
                installation_id=installation_id,
            )

            db.add(repository)
            db.flush()

        else:
            # Never silently transfer a repository between application users
            # or GitHub installations.
            if installation is not None:
                if (
                    repository.user_id is not None
                    and repository.user_id != installation.user_id
                ):
                    raise ValueError(
                        "Repository ownership conflicts with the GitHub installation."
                    )

                if (
                    repository.installation_id is not None
                    and repository.installation_id != installation_id
                ):
                    raise ValueError(
                        "Repository is already linked to a different GitHub installation."
                    )

                # Backfill only missing ownership fields after verifying the
                # installation record and its owning application user.
                if repository.user_id is None:
                    repository.user_id = installation.user_id

                if repository.installation_id is None:
                    repository.installation_id = installation_id

            repository.name = repository_name
            repository.full_name = repository_full_name
            repository.html_url = repository_url

        # 2. Find or create Pull Request
        pull_request = db.query(PullRequest).filter(
            PullRequest.repository_id == repository.id,
            PullRequest.github_pr_number == pr_number
        ).first()

        if not pull_request:

            pull_request = PullRequest(
                repository_id=repository.id,
                github_pr_number=pr_number,
                title=pr_title,
                description=pr_description,
                status=pr_status,
                head_sha=commit_sha
            )

            db.add(pull_request)
            db.flush()

        else:

            pull_request.title = pr_title
            pull_request.description = pr_description
            pull_request.status = pr_status
            pull_request.head_sha = commit_sha

        # 3. Check duplicate commit
        existing_review = db.query(Review).filter(
            Review.pull_request_id == pull_request.id,
            Review.commit_sha == commit_sha
        ).first()

        if existing_review:

            db.commit()

            return {
                "status": "success",
                "message": "This commit has already been reviewed",
                "review_id": existing_review.id,
                "pull_request_id": pull_request.id,
                "overall_status": existing_review.overall_status,
                "duplicate": True
            }

        # 4. Collect summaries and unified findings
        summaries = []

        for file_result in review_results:

            if not isinstance(file_result, dict):
                continue

            ai_review = file_result.get("ai_review", {})

            if (
                isinstance(ai_review, dict)
                and ai_review.get("summary")
            ):

                summaries.append(
                    f"{file_result.get('filename', 'unknown')}: "
                    f"{ai_review['summary']}"
                )

        all_issues = collect_unified_issues(review_results)

        # 5. Remove exact duplicates
        unique_issues = remove_duplicate_issues(all_issues)

        duplicate_count = len(all_issues) - len(unique_issues)

        overall_status = (
            "issues_found" if unique_issues else "passed"
        )

        summary = "\n".join(summaries)

        # 6. Create review record
        review = Review(
            pull_request_id=pull_request.id,
            commit_sha=commit_sha,
            summary=summary,
            overall_status=overall_status
        )

        db.add(review)
        db.flush()

        # 7. Save unified findings
        for item in unique_issues:

            issue = item["issue"]

            db.add(
                ReviewIssue(
                    review_id=review.id,
                    file_path=item["file_path"],
                    line_number=item["line_number"],
                    issue_type=item["issue_type"],
                    severity=issue.get("severity", "medium"),
                    description=item["description"],
                    suggestion=issue.get("suggestion"),
                    source=item["source"]
                )
            )

        # 8. Prepare diff information
        diff_files = []

        if isinstance(diff_analysis, dict):

            candidate_files = diff_analysis.get("files", [])

            if isinstance(candidate_files, list):
                diff_files = candidate_files

        # Backward compatibility
        if not diff_files:

            for item in review_results:

                if not isinstance(item, dict):
                    continue

                file_diff = item.get("diff_analysis")

                if not isinstance(file_diff, dict):
                    continue

                diff_files.append({
                    "filename": item.get("filename"),
                    **file_diff
                })

        # 9. Save changed files
        saved_file_count = 0

        for diff_data in diff_files:

            if not isinstance(diff_data, dict):
                continue

            filename = diff_data.get("filename")

            if not isinstance(filename, str) or not filename:
                continue

            additions = diff_data.get("additions_count", 0)
            deletions = diff_data.get("deletions_count", 0)

            if (
                not isinstance(additions, int)
                or isinstance(additions, bool)
                or additions < 0
            ):
                additions = 0

            if (
                not isinstance(deletions, int)
                or isinstance(deletions, bool)
                or deletions < 0
            ):
                deletions = 0

            changes_count = diff_data.get("changes_available")

            if (
                not isinstance(changes_count, int)
                or isinstance(changes_count, bool)
                or changes_count < 0
            ):
                changes_count = additions + deletions

            added_lines = diff_data.get("added_lines", [])
            deleted_lines = diff_data.get("deleted_lines", [])

            if not isinstance(added_lines, list):
                added_lines = []

            if not isinstance(deleted_lines, list):
                deleted_lines = []

            patch_available = diff_data.get("patch_available", False)

            if not isinstance(patch_available, bool):
                patch_available = False

            db.add(
                ReviewFile(
                    review_id=review.id,
                    file_path=filename,
                    file_status=diff_data.get("status"),
                    additions_count=additions,
                    deletions_count=deletions,
                    changes_count=changes_count,
                    added_lines=added_lines,
                    deleted_lines=deleted_lines,
                    patch_available=patch_available
                )
            )

            saved_file_count += 1

        # 10. Commit everything
        db.commit()
        db.refresh(review)

        # 11. Return result
        return {
            "status": "success",
            "message": "Review results saved successfully",
            "review_id": review.id,
            "pull_request_id": pull_request.id,
            "total_issues": len(unique_issues),
            "duplicate_issues_removed": duplicate_count,
            "total_files_with_diff": saved_file_count,
            "overall_status": overall_status,
            "duplicate": False
        }

    except Exception:
        db.rollback()
        raise
