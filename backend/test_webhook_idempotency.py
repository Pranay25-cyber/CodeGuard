
import asyncio

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import WebhookEvent
from app.routes import github as github_route


class FakeRequest:
    def __init__(self, delivery_id):
        self.headers = {
            "X-Hub-Signature-256": "test-signature",
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": delivery_id,
        }

        self.payload = {
            "action": "opened",
            "repository": {
                "full_name": "test-owner/test-repo",
            },
            "pull_request": {
                "number": 10,
            },
            "installation": {
                "id": 123,
            },
        }

    async def body(self):
        return b'{"test": "webhook"}'

    async def json(self):
        return self.payload


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    WebhookEvent.__table__.create(engine)

    TestingSession = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    db = TestingSession()

    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def call_webhook(request, background_tasks, db):
    return asyncio.run(
        github_route.github_webhook(
            request=request,
            background_tasks=background_tasks,
            db=db,
        )
    )


def enable_test_signature(monkeypatch):
    monkeypatch.setattr(
        github_route,
        "verify_webhook_signature",
        lambda payload, signature: True,
    )


def test_first_webhook_delivery_is_accepted(
    db_session,
    monkeypatch,
):
    enable_test_signature(monkeypatch)

    background_tasks = BackgroundTasks()

    result = call_webhook(
        FakeRequest("delivery-first"),
        background_tasks,
        db_session,
    )

    assert result["status"] == "accepted"
    assert result["retry"] is False
    assert len(background_tasks.tasks) == 1

    event = (
        db_session.query(WebhookEvent)
        .filter_by(delivery_id="delivery-first")
        .first()
    )

    assert event is not None
    assert event.status == "received"


def test_duplicate_delivery_is_not_scheduled_again(
    db_session,
    monkeypatch,
):
    enable_test_signature(monkeypatch)

    first_tasks = BackgroundTasks()

    first_result = call_webhook(
        FakeRequest("delivery-duplicate"),
        first_tasks,
        db_session,
    )

    assert first_result["status"] == "accepted"
    assert len(first_tasks.tasks) == 1

    duplicate_tasks = BackgroundTasks()

    duplicate_result = call_webhook(
        FakeRequest("delivery-duplicate"),
        duplicate_tasks,
        db_session,
    )

    assert duplicate_result["status"] == "duplicate"
    assert len(duplicate_tasks.tasks) == 0

    assert (
        db_session.query(WebhookEvent)
        .filter_by(delivery_id="delivery-duplicate")
        .count()
        == 1
    )


def test_failed_webhook_can_be_retried(
    db_session,
    monkeypatch,
):
    enable_test_signature(monkeypatch)

    failed_event = WebhookEvent(
        delivery_id="delivery-failed",
        event_type="pull_request",
        action="opened",
        repository_full_name="test-owner/test-repo",
        pr_number=10,
        status="failed",
    )

    db_session.add(failed_event)
    db_session.commit()

    background_tasks = BackgroundTasks()

    result = call_webhook(
        FakeRequest("delivery-failed"),
        background_tasks,
        db_session,
    )

    assert result["status"] == "accepted"
    assert result["retry"] is True
    assert len(background_tasks.tasks) == 1

    db_session.refresh(failed_event)

    assert failed_event.status == "received"


def test_failed_webhook_can_only_be_claimed_once(
    db_session,
    monkeypatch,
):
    enable_test_signature(monkeypatch)

    failed_event = WebhookEvent(
        delivery_id="delivery-single-retry",
        event_type="pull_request",
        action="opened",
        repository_full_name="test-owner/test-repo",
        pr_number=10,
        status="failed",
    )

    db_session.add(failed_event)
    db_session.commit()

    first_tasks = BackgroundTasks()

    first_result = call_webhook(
        FakeRequest("delivery-single-retry"),
        first_tasks,
        db_session,
    )

    assert first_result["status"] == "accepted"
    assert first_result["retry"] is True
    assert len(first_tasks.tasks) == 1

    second_tasks = BackgroundTasks()

    second_result = call_webhook(
        FakeRequest("delivery-single-retry"),
        second_tasks,
        db_session,
    )

    assert second_result["status"] == "duplicate"
    assert len(second_tasks.tasks) == 0

    assert (
        db_session.query(WebhookEvent)
        .filter_by(delivery_id="delivery-single-retry")
        .count()
        == 1
    )
