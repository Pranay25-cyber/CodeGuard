
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.github.webhook_security import verify_webhook_signature
from app.database.connection import get_db
from app.database.models import WebhookEvent, FixProposal, Repository
from app.services.review_storage_service import save_review_results
from app.services.webhook_review_service import (
    process_pull_request_review,
    process_tracked_pull_request_review,
)
from app.github.github_service import (
    verify_github_app,
    get_repository_details,
    get_pull_request_details,
    get_pull_request_file_content,
    get_recent_pull_requests,
    get_repository_python_test_files,
    get_repository_snapshot,
    get_pull_request_counts,
)

from app.services.static_analyzer import analyze_python_code
from app.services.ai_review_service import review_python_code
from app.services.fix_workflow_service import run_fix_workflow


router = APIRouter(
    prefix="/github",
    tags=["GitHub Integration"],
)


class FixRequest(BaseModel):
    repository_full_name: str = Field(min_length=1)
    filename: str = Field(min_length=1)


@router.get("/verify")
def verify_github():
    try:
        return verify_github_app()
    except Exception as error:
        print("GitHub verification error:", repr(error))
        raise HTTPException(
            status_code=500,
            detail="GitHub authentication failed",
        )


@router.get("/repository")
def get_repository():
    try:
        return get_repository_details()
    except Exception as error:
        print("Repository error:", repr(error))
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve repository",
        )


@router.get("/pull-request/{pr_number}")
def get_pull_request(
    pr_number: int,
    repository_full_name: str
):
    try:
        return get_pull_request_details(
            pr_number,
            repository_full_name=repository_full_name
        )
    except Exception as error:
        print("Pull Request error:", repr(error))
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve Pull Request details",
        )

@router.get("/pull-requests")
def list_recent_pull_requests(
    repository_full_name: str,
    limit: int = 20
):
    try:
        return get_recent_pull_requests(
            repository_full_name=repository_full_name,
            limit=limit
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )
    except Exception as error:
        print(
            "GitHub Pull Request retrieval failed:",
            repr(error)
        )
        
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve pull requests from GitHub"
        )


@router.get("/pull-request/{pr_number}/static-analysis")
def static_analysis_pull_request(
    pr_number: int,
    repository_full_name: str,
):
    try:
        pr_data = get_pull_request_details(
            pr_number,
            repository_full_name=repository_full_name,
        )

        static_results = []

        for file in pr_data["changed_files"]:
            filename = file["filename"]

            if not filename.endswith(".py") or file["status"] == "removed":
                continue

            code = get_pull_request_file_content(
                pr_number,
                filename,
                commit_sha=pr_data["head_sha"],
                repository_full_name=repository_full_name,
            )

            analysis = analyze_python_code(code)

            static_results.append({
                "filename": filename,
                "analysis": analysis,
            })

        return {
            "status": "success",
            "pull_request_number": pr_number,
            "static_analysis": static_results,
        }

    except Exception as error:
        print("Static analysis error:", repr(error))
        raise HTTPException(
            status_code=500,
            detail="Unable to perform static analysis",
        )


@router.get("/pull-request/{pr_number}/ai-review")
def ai_review_pull_request(
    pr_number: int,
    db: Session = Depends(get_db),
):
    try:
        pr_data = get_pull_request_details(pr_number)
        review_results = []

        for file in pr_data["changed_files"]:
            filename = file["filename"]

            if not filename.endswith(".py") or file["status"] == "removed":
                continue

            code = get_pull_request_file_content(
                pr_number,
                filename,
                commit_sha=pr_data["head_sha"],
            )

            static_analysis = analyze_python_code(code)

            ai_review = review_python_code(
                code=code,
                filename=filename,
                static_analysis=static_analysis,
            )

            review_results.append({
                "filename": filename,
                "static_analysis": static_analysis,
                "ai_review": ai_review,
            })

        database_result = save_review_results(
            db=db,
            github_repo_id=pr_data["repository_id"],
            repository_name=pr_data["repository_name"],
            repository_full_name=pr_data["repository_full_name"],
            repository_url=pr_data["repository_url"],
            pr_number=pr_data["pull_request_number"],
            pr_title=pr_data["title"],
            pr_description=pr_data["description"],
            pr_status=pr_data["state"],
            commit_sha=pr_data["head_sha"],
            review_results=review_results,
        )

        return {
            "status": "success",
            "pull_request_number": pr_number,
            "total_files_reviewed": len(review_results),
            "reviews": review_results,
            "database_storage": database_result,
        }

    except Exception as error:
        db.rollback()
        print("AI review and database storage error:", repr(error))
        raise HTTPException(
            status_code=500,
            detail="Unable to perform AI review and save results",
        )





@router.post("/pull-request/{pr_number}/fix")
def fix_pull_request(
    pr_number: int,
    request: FixRequest,
    db: Session = Depends(get_db),
):
    """Generate and validate a fix using repository files."""

    repository_full_name = request.repository_full_name.strip()

    if (
        not repository_full_name
        or len(repository_full_name.split("/")) != 2
        or any(not part.strip() for part in repository_full_name.split("/"))
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid repository name. Use owner/repository format.",
        )

    try:
        # 1. Retrieve the selected Pull Request.
        pr_data = get_pull_request_details(
            pr_number,
            repository_full_name=repository_full_name,
        )

        if pr_data["state"] != "open":
            raise HTTPException(
                status_code=400,
                detail="Only open Pull Requests can be fixed.",
            )

        # 2. Confirm that the requested file belongs to this PR.
        filename = request.filename

        changed_file = next(
            (
                item
                for item in pr_data["changed_files"]
                if item["filename"] == filename
            ),
            None,
        )

        if changed_file is None:
            raise HTTPException(
                status_code=400,
                detail="The requested file is not part of this Pull Request.",
            )

        if changed_file["status"] == "removed":
            raise HTTPException(
                status_code=400,
                detail="Deleted files cannot be fixed.",
            )

        if not filename.endswith(".py"):
            raise HTTPException(
                status_code=400,
                detail="Only Python files are supported currently.",
            )

        # 3. Capture the exact PR commit.
        original_commit_sha = pr_data.get("head_sha")

        if not original_commit_sha:
            raise HTTPException(
                status_code=409,
                detail="Pull Request commit SHA is unavailable.",
            )

        # 4. Retrieve the selected source file at that commit.
        code = get_pull_request_file_content(
            pr_number,
            filename,
            commit_sha=original_commit_sha,
            repository_full_name=repository_full_name,
        )

        # 5. Retrieve the repository snapshot at the same commit.
        snapshot = get_repository_snapshot(
            repository_full_name=repository_full_name,
            commit_sha=original_commit_sha,
        )

        if snapshot.get("tree_truncated"):
            raise HTTPException(
                status_code=422,
                detail=(
                    "The GitHub repository tree was truncated. "
                    "A complete repository snapshot could not be retrieved. "
                    "The fix was not generated."
                ),
            )

        repository_files = snapshot.get("files", {}).copy()

        if not repository_files:
            raise HTTPException(
                status_code=422,
                detail="No supported repository files were retrieved.",
            )

        # Ensure the selected PR source file is present.
        repository_files[filename] = code

        # 6. Run static analysis.
        static_analysis = analyze_python_code(code)

        # 7. Ask Claude to review the source code.
        ai_review = review_python_code(
            code=code,
            filename=filename,
            static_analysis=static_analysis,
        )

        # 8. Generate the fix and run repository tests.
        # GitHub publishing remains disabled here.
        fix_result = run_fix_workflow(
            code=code,
            filename=filename,
            review_result=ai_review,
            repository_files=repository_files,
            publish_to_github=False,
        )

        if fix_result.get("status") != "passed":
            return {
                "status": fix_result.get("status", "fix_failed"),
                "filename": filename,
                "message": fix_result.get("message"),
                "changes_summary": fix_result.get("changes_summary"),
                "validation": fix_result.get("validation"),
                "automated_tests": fix_result.get("automated_tests"),
                "fix_id": None,
            }

        # 9. Check whether the PR changed during fix generation.
        latest_pr_data = get_pull_request_details(
            pr_number,
            repository_full_name=repository_full_name,
        )

        if (
            latest_pr_data.get("state") != "open"
            or latest_pr_data.get("head_sha") != original_commit_sha
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "The Pull Request changed while the fix was being generated. "
                    "Generate a new fix proposal."
                ),
            )

        # 10. Save the proposal for developer approval.
        proposal = FixProposal(
            repository_full_name=pr_data["repository_full_name"],
            original_pr_number=pr_number,
            original_commit_sha=original_commit_sha,
            filename=filename,
            original_code=code,
            fixed_code=fix_result["fixed_code"],
            changes_summary=fix_result["changes_summary"],
            validation_result=fix_result["validation"],
            test_result=fix_result["automated_tests"],
            status="pending_approval",
        )

        db.add(proposal)
        db.commit()
        db.refresh(proposal)

        return {
            "status": "pending_approval",
            "fix_id": proposal.id,
            "repository": repository_full_name,
            "filename": filename,
            "original_commit_sha": original_commit_sha,
            "repository_snapshot": {
                "total_files": snapshot["total"],
                "python_files": len(snapshot["python_files"]),
                "test_files": len(snapshot["test_files"]),
                "config_files": len(snapshot["config_files"]),
            },
            "message": (
                "Fix passed validation and repository tests. "
                "Developer approval is required before publishing."
            ),
            "changes_summary": proposal.changes_summary,
            "validation": proposal.validation_result,
            "automated_tests": proposal.test_result,
            "preview_url": f"/fixes/{proposal.id}",
            "approve_url": f"/fixes/{proposal.id}/approve",
            "reject_url": f"/fixes/{proposal.id}/reject",
        }

    except HTTPException:
        raise

    except Exception as error:
        db.rollback()
        print("AI Fix workflow error:", repr(error))

        raise HTTPException(
            status_code=500,
            detail="Unable to generate and save AI fix proposal",
        ) from error





@router.post("/webhook")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # Read the original request body.
    payload = await request.body()

    signature = request.headers.get("X-Hub-Signature-256")

    # Verify GitHub webhook signature.
    try:
        is_valid = verify_webhook_signature(payload, signature)

    except RuntimeError as error:
        print("Webhook configuration error:", str(error))

        raise HTTPException(
            status_code=500,
            detail="Webhook security is not configured",
        )

    if not is_valid:
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature",
        )

    event_type = request.headers.get("X-GitHub-Event")

    # Handle GitHub ping event.
    if event_type == "ping":
        return {
            "status": "success",
            "message": "GitHub webhook connection successful",
        }

    # Parse webhook JSON.
    try:
        event_data = await request.json()

    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook JSON payload",
        )

    if event_type == "pull_request":

        action = event_data.get("action")

        supported_actions = [
            "opened",
            "synchronize",
            "reopened",
        ]

        if action not in supported_actions:
            return {
                "status": "ignored",
                "action": action,
                "message": "Pull Request action is not supported",
            }

        # Read GitHub delivery ID.
        delivery_id = request.headers.get("X-GitHub-Delivery")

        if not delivery_id or not delivery_id.strip():
            raise HTTPException(
                status_code=400,
                detail="Missing GitHub delivery ID",
            )

        repository = event_data.get("repository") or {}

        repository_full_name = repository.get("full_name")

        pull_request = event_data.get("pull_request") or {}

        pr_number = pull_request.get("number")

        installation = event_data.get("installation") or {}

        installation_id = installation.get("id")

        # Validate required GitHub event information.
        if (
            not isinstance(repository_full_name, str)
            or not repository_full_name.strip()
            or not isinstance(pr_number, int)
            or isinstance(pr_number, bool)
            or pr_number <= 0
            or not isinstance(installation_id, int)
            or isinstance(installation_id, bool)
            or installation_id <= 0
        ):
            raise HTTPException(
                status_code=400,
                detail="Missing or invalid GitHub event information",
            )

        print("WEBHOOK DELIVERY ID:", delivery_id)

        # Check whether this delivery was already recorded.
        existing_event = (
            db.query(WebhookEvent)
            .filter(
                WebhookEvent.delivery_id == delivery_id
            )
            .first()
        )

        event_id = None
        is_retry = False

        if existing_event:

            # Only failed events can be retried.
            if existing_event.status != "failed":
                return {
                    "status": "duplicate",
                    "message": (
                        "This GitHub webhook delivery was already received."
                    ),
                    "delivery_id": delivery_id,
                    "event_status": existing_event.status,
                }

            # Atomically claim a failed event.
            # Only one concurrent request can change
            # the status from failed to received.
            claimed = (
                db.query(WebhookEvent)
                .filter(
                    WebhookEvent.id == existing_event.id,
                    WebhookEvent.status == "failed",
                )
                .update(
                    {"status": "received"},
                    synchronize_session=False,
                )
            )

            db.commit()

            if claimed != 1:

                current_event = (
                    db.query(WebhookEvent)
                    .filter(
                        WebhookEvent.delivery_id == delivery_id
                    )
                    .first()
                )

                return {
                    "status": "duplicate",
                    "message": (
                        "This webhook delivery is already being processed "
                        "or was completed."
                    ),
                    "delivery_id": delivery_id,
                    "event_status": (
                        current_event.status
                        if current_event
                        else "unknown"
                    ),
                }

            event_id = existing_event.id
            is_retry = True

        else:

            # First delivery: create a new webhook event.
            webhook_event = WebhookEvent(
                delivery_id=delivery_id,
                event_type=event_type,
                action=action,
                repository_full_name=repository_full_name,
                pr_number=pr_number,
                status="received",
            )

            db.add(webhook_event)

            try:
                db.commit()
                db.refresh(webhook_event)

                event_id = webhook_event.id

            except IntegrityError:
                # Another simultaneous request may have inserted
                # the same delivery ID.
                db.rollback()

                existing_event = (
                    db.query(WebhookEvent)
                    .filter(
                        WebhookEvent.delivery_id == delivery_id
                    )
                    .first()
                )

                if existing_event:
                    return {
                        "status": "duplicate",
                        "message": (
                            "This GitHub webhook delivery was already received."
                        ),
                        "delivery_id": delivery_id,
                        "event_status": existing_event.status,
                    }

                raise HTTPException(
                    status_code=500,
                    detail="Unable to save webhook event",
                )

        # Schedule the review only for the request that
        # created or successfully reclaimed the event.
        background_tasks.add_task(
            process_tracked_pull_request_review,
            event_id,
            repository_full_name,
            pr_number,
            installation_id,
        )

        return {
            "status": "accepted",
            "message": (
                "Failed webhook delivery retry scheduled."
                if is_retry
                else "Pull Request received. Automatic AI review scheduled."
            ),
            "repository": repository_full_name,
            "pull_request_number": pr_number,
            "action": action,
            "delivery_id": delivery_id,
            "event_id": event_id,
            "retry": is_retry,
        }

    return {
        "status": "ignored",
        "event": event_type,
        "message": "Event received but no action is configured",
    }


# Repository-wise Open and Closed Pull Request summary.
# This endpoint is additive; existing Pull Request and review routes remain unchanged.
@router.get("/pull-request-summary")
def get_repository_pull_request_summary(
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = request.session.get("user_id")

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Please log in first",
        )

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=401,
            detail="Invalid user session",
        )

    repositories = (
        db.query(Repository)
        .filter(
            Repository.user_id == user_id,
            Repository.installation_id.isnot(None),
        )
        .order_by(Repository.full_name.asc())
        .all()
    )

    # Copy scalar values before starting worker threads. SQLAlchemy
    # session objects are not shared with background worker threads.
    repository_items = [
        (
            repository.full_name,
            repository.installation_id,
            repository.html_url,
        )
        for repository in repositories
    ]

    def fetch_one_repository(item):
        repository_full_name, installation_id, html_url = item

        try:
            return get_pull_request_counts(
                repository_full_name=repository_full_name,
                installation_id=installation_id,
            )
        except Exception as error:
            print(
                "Unable to retrieve Pull Request counts for "
                f"{repository_full_name}: {error!r}"
            )
            return {
                "repository": repository_full_name,
                "html_url": html_url,
                "open_count": None,
                "closed_count": None,
                "error": "Unable to retrieve pull request counts",
            }

    if repository_items:
        # GitHub calls are network-bound, so process repositories
        # concurrently instead of waiting for each repository in turn.
        with ThreadPoolExecutor(
            max_workers=min(8, len(repository_items))
        ) as executor:
            results = list(executor.map(fetch_one_repository, repository_items))
    else:
        results = []

    return {
        "status": "success",
        "total_repositories": len(results),
        "repositories": results,
    }
