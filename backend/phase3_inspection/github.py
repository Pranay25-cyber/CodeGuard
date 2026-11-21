from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.github.webhook_security import verify_webhook_signature 


from app.database.connection import get_db
from app.services.review_storage_service import save_review_results
from sqlalchemy.exc import IntegrityError

from app.database.models import WebhookEvent
from app.services.webhook_review_service import (
    process_pull_request_review,
    process_tracked_pull_request_review
)
from app.github.github_service import (
    verify_github_app,
    get_repository_details,
    get_pull_request_details,
    get_pull_request_file_content
)



from app.services.static_analyzer import analyze_python_code
from app.services.ai_review_service import review_python_code
from app.services.fix_workflow_service import run_fix_workflow


# Create the API router
router = APIRouter(
    prefix="/github",
    tags=["GitHub Integration"]
)


# Request body for the AI Fix API
class FixRequest(BaseModel):
    filename: str = Field(min_length=1)
    test_code: str = Field(min_length=1)


# 1. Verify GitHub App
@router.get("/verify")
def verify_github():

    try:
        return verify_github_app()

    except Exception as e:
        print("GitHub verification error:", repr(e))

        raise HTTPException(
            status_code=500,
            detail="GitHub authentication failed"
        )


# 2. Get repository details
@router.get("/repository")
def get_repository():

    try:
        return get_repository_details()

    except Exception as e:
        print("Repository error:", repr(e))

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve repository"
        )


# 3. Get Pull Request details
@router.get("/pull-request/{pr_number}")
def get_pull_request(pr_number: int):

    try:
        return get_pull_request_details(pr_number)

    except Exception as e:
        print("Pull Request error:", repr(e))

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve Pull Request details"
        )


# 4. Static analysis
@router.get("/pull-request/{pr_number}/static-analysis")
def static_analysis_pull_request(pr_number: int):

    try:
        pr_data = get_pull_request_details(pr_number)

        static_results = []

        for file in pr_data["changed_files"]:

            filename = file["filename"]

            if not filename.endswith(".py"):
                continue

            if file["status"] == "removed":
                continue

            # Retrieve the complete file from the PR branch
            code = get_pull_request_file_content(
                pr_number,
                filename
            )

            analysis = analyze_python_code(code)

            static_results.append({
                "filename": filename,
                "analysis": analysis
            })

        return {
            "status": "success",
            "pull_request_number": pr_number,
            "static_analysis": static_results
        }

    except Exception as e:
        print("Static analysis error:", repr(e))

        raise HTTPException(
            status_code=500,
            detail="Unable to perform static analysis"
        )


# 5. AI code review
@router.get("/pull-request/{pr_number}/ai-review")
def ai_review_pull_request(
    pr_number: int,
    db: Session = Depends(get_db)
):

    try:
        pr_data = get_pull_request_details(pr_number)

        review_results = []

        for file in pr_data["changed_files"]:

            filename = file["filename"]

            if not filename.endswith(".py"):
                continue

            if file["status"] == "removed":
                continue

            code = get_pull_request_file_content(
                pr_number,
                filename
            )

            static_analysis = analyze_python_code(code)

            ai_review = review_python_code(
                code=code,
                filename=filename,
                static_analysis=static_analysis
            )

            review_results.append({
                "filename": filename,
                "static_analysis": static_analysis,
                "ai_review": ai_review
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
            review_results=review_results
        )

        return {
            "status": "success",
            "pull_request_number": pr_number,
            "total_files_reviewed": len(review_results),
            "reviews": review_results,
            "database_storage": database_result
        }

    except Exception as e:
        db.rollback()

        print("AI review and database storage error:", repr(e))

        raise HTTPException(
            status_code=500,
            detail="Unable to perform AI review and save results"
        )


# 6. AI Fix Agent - Generate and publish a validated fix
@router.post("/pull-request/{pr_number}/fix")
def fix_pull_request(
    pr_number: int,
    request: FixRequest
):

    try:
        # Step 1: Retrieve original Pull Request
        pr_data = get_pull_request_details(pr_number)

        if pr_data["state"] != "open":
            raise HTTPException(
                status_code=400,
                detail="Only open Pull Requests can be fixed."
            )

        filename = request.filename

        # Step 2: Confirm the requested file belongs to this PR
        changed_file = next(
            (
                file for file in pr_data["changed_files"]
                if file["filename"] == filename
            ),
            None
        )

        if changed_file is None:
            raise HTTPException(
                status_code=400,
                detail="The requested file is not part of this Pull Request."
            )

        if changed_file["status"] == "removed":
            raise HTTPException(
                status_code=400,
                detail="Deleted files cannot be fixed by this endpoint."
            )

        if not filename.endswith(".py"):
            raise HTTPException(
                status_code=400,
                detail="Only Python files are supported currently."
            )

        # Step 3: Retrieve complete source code
        code = get_pull_request_file_content(
            pr_number,
            filename
        )

        # Step 4: Run static analysis
        static_analysis = analyze_python_code(code)

        # Step 5: Run Claude AI review
        ai_review = review_python_code(
            code=code,
            filename=filename,
            static_analysis=static_analysis
        )

        # Step 6: Generate fix and validate it
        fix_result = run_fix_workflow(
             code=code,
             filename=filename,
             review_result=ai_review,
             test_code=request.test_code,
             publish_to_github=True,
             repository_full_name=pr_data["repository_full_name"],
             original_pr_number=pr_number
            )

        # Do not publish a fix if validation or tests fail
        if fix_result["status"] != "passed":

            return {
                "status": fix_result["status"],
                "filename": filename,
                "message": fix_result.get("message"),
                "changes_summary": fix_result.get("changes_summary"),
                "validation": fix_result.get("validation"),
                "automated_tests": fix_result.get("automated_tests"),
                "github_fix_pr": None
            }

        
        
        
        return {
            "status": "success",
            "filename": filename,
            "message": "AI-generated fix passed validation and tests.",
            "changes_summary": fix_result["changes_summary"],
            "validation": fix_result["validation"],
            "automated_tests": fix_result["automated_tests"],
            "github_fix_pr": fix_result.get("github")
        }

    except HTTPException:
        raise

    except Exception as e:
        print("AI Fix workflow error:", repr(e))

        raise HTTPException(
            status_code=500,
            detail="Unable to generate and publish AI fix"
        )

# 7. GitHub Webhook Endpoint
@router.post("/webhook")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    # Step 1: Read original request body
    payload = await request.body()

    # Step 2: Get GitHub signature
    signature = request.headers.get("X-Hub-Signature-256")

    # Step 3: Verify signature
    try:
        is_valid = verify_webhook_signature(payload, signature)

    except RuntimeError as e:
        print("Webhook configuration error:", str(e))
        raise HTTPException(
            status_code=500,
            detail="Webhook security is not configured"
        )

    if not is_valid:
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature"
        )

    # Step 4: Identify event
    event_type = request.headers.get("X-GitHub-Event")

    # Step 5: Handle GitHub ping
    if event_type == "ping":
        return {
            "status": "success",
            "message": "GitHub webhook connection successful"
        }

    # Step 6: Parse JSON
    try:
        event_data = await request.json()

    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook JSON payload"
        )

    # Step 7: Process Pull Request events
    if event_type == "pull_request":

        action = event_data.get("action")

        supported_actions = [
            "opened",
            "synchronize",
            "reopened"
        ]

        if action not in supported_actions:
            return {
                "status": "ignored",
                "action": action,
                "message": "Pull Request action is not supported"
            }

        # Step 8: Validate GitHub delivery ID
        delivery_id = request.headers.get("X-GitHub-Delivery")

        if not delivery_id or not delivery_id.strip():
            raise HTTPException(
                status_code=400,
                detail="Missing GitHub delivery ID"
            )

        # Step 9: Retrieve repository information
        repository = event_data.get("repository") or {}
        repository_full_name = repository.get("full_name")

        # Retrieve Pull Request number
        pull_request = event_data.get("pull_request") or {}
        pr_number = pull_request.get("number")

        # Retrieve installation ID
        installation = event_data.get("installation") or {}
        installation_id = installation.get("id")

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
                detail="Missing or invalid GitHub event information"
            )
        print("WEBHOOK DELIVERY ID:", delivery_id)
        existing_event = (
            db.query(WebhookEvent)
            .filter(WebhookEvent.delivery_id == delivery_id)
            .first()
            )
        print("EXISTING WEBHOOK EVENT:", existing_event.id if existing_event else None)
        # Step 10: Save webhook event in PostgreSQL
        webhook_event = WebhookEvent(
            delivery_id=delivery_id,
            event_type=event_type,
            action=action,
            repository_full_name=repository_full_name,
            pr_number=pr_number,
            status="received"
        )

        db.add(webhook_event)

        try:
            db.commit()
            db.refresh(webhook_event)

        except IntegrityError:
            db.rollback()

            # Confirm whether this delivery ID already exists
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
                    "message": "This GitHub webhook delivery was already received.",
                    "delivery_id": delivery_id
                }

            raise HTTPException(
                status_code=500,
                detail="Unable to save webhook event"
            )

        # Step 11: Schedule tracked automatic AI review
        background_tasks.add_task(
            process_tracked_pull_request_review,
            webhook_event.id,
            repository_full_name,
            pr_number,
            installation_id
        )

        return {
            "status": "accepted",
            "message": "Pull Request received. Automatic AI review scheduled.",
            "repository": repository_full_name,
            "pull_request_number": pr_number,
            "action": action,
            "delivery_id": delivery_id,
            "event_id": webhook_event.id
        }

    # Step 12: Ignore unsupported events
    return {
        "status": "ignored",
        "event": event_type,
        "message": "Event received but no action is configured"
    }