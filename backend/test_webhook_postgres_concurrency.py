import asyncio
import json
import os
import threading
import uuid

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.database.connection import engine, SessionLocal
from app.database.models import WebhookEvent
from app.routes import github as github_route


# Run this file only when explicitly enabled.
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_WEBHOOK_CONCURRENCY") != "1",
    reason="Enable with RUN_POSTGRES_WEBHOOK_CONCURRENCY=1",
)


class FakeRequest:
    def __init__(self, delivery_id: str):
        self.payload = {
            "action": "opened",
            "repository": {
                "full_name": "test-owner/test-repository"
            },
            "pull_request": {
                "number": 987
            },
            "installation": {
                "id": 12345
            },
        }

        self.headers = {
            "X-Hub-Signature-256": "sha256=test-signature",
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": delivery_id,
        }

    async def body(self):
        return json.dumps(self.payload).encode("utf-8")

    async def json(self):
        return self.payload


@pytest.fixture(scope="module", autouse=True)
def prepare_postgres_table():
    if engine.dialect.name != "postgresql":
        pytest.fail(
            "These concurrency tests must run against PostgreSQL."
        )

    WebhookEvent.__table__.create(
        bind=engine,
        checkfirst=True,
    )


@pytest.fixture(autouse=True)
def mock_signature_verification(monkeypatch):
    monkeypatch.setattr(
        github_route,
        "verify_webhook_signature",
        lambda payload, signature: True,
    )


def send_webhook(delivery_id: str, start_barrier=None):
    """
    Each worker gets its own database session.
    """

    if start_barrier:
        start_barrier.wait(timeout=10)

    db: Session = SessionLocal()
    background_tasks = BackgroundTasks()

    try:
        response = asyncio.run(
            github_route.github_webhook(
                request=FakeRequest(delivery_id),
                background_tasks=background_tasks,
                db=db,
            )
        )

        return {
            "response": response,
            "scheduled_tasks": len(background_tasks.tasks),
        }

    finally:
        db.close()


def delete_test_event(delivery_id: str):
    db = SessionLocal()

    try:
        db.query(WebhookEvent).filter(
            WebhookEvent.delivery_id == delivery_id
        ).delete(synchronize_session=False)

        db.commit()

    finally:
        db.close()


def get_test_event(delivery_id: str):
    db = SessionLocal()

    try:
        return (
            db.query(WebhookEvent)
            .filter(WebhookEvent.delivery_id == delivery_id)
            .first()
        )

    finally:
        db.close()


def test_simultaneous_first_delivery_creates_only_one_event():
    delivery_id = f"concurrency-first-{uuid.uuid4()}"

    barrier = threading.Barrier(2)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    send_webhook,
                    delivery_id,
                    barrier,
                )
                for _ in range(2)
            ]

            results = [
                future.result(timeout=30)
                for future in futures
            ]

        statuses = [
            result["response"]["status"]
            for result in results
        ]

        assert statuses.count("accepted") == 1
        assert statuses.count("duplicate") == 1

        total_scheduled = sum(
            result["scheduled_tasks"]
            for result in results
        )

        assert total_scheduled == 1

        event = get_test_event(delivery_id)

        assert event is not None
        assert event.status == "received"

    finally:
        delete_test_event(delivery_id)


def test_simultaneous_failed_retry_is_claimed_only_once():
    delivery_id = f"concurrency-retry-{uuid.uuid4()}"

    db = SessionLocal()

    try:
        db.add(
            WebhookEvent(
                delivery_id=delivery_id,
                event_type="pull_request",
                action="opened",
                repository_full_name="test-owner/test-repository",
                pr_number=987,
                status="failed",
            )
        )

        db.commit()

    finally:
        db.close()

    barrier = threading.Barrier(2)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    send_webhook,
                    delivery_id,
                    barrier,
                )
                for _ in range(2)
            ]

            results = [
                future.result(timeout=30)
                for future in futures
            ]

        statuses = [
            result["response"]["status"]
            for result in results
        ]

        assert statuses.count("accepted") == 1
        assert statuses.count("duplicate") == 1

        total_scheduled = sum(
            result["scheduled_tasks"]
            for result in results
        )

        assert total_scheduled == 1

        event = get_test_event(delivery_id)

        assert event is not None
        assert event.status == "received"

    finally:
        delete_test_event(delivery_id)
#webhook file 