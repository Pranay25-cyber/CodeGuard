
from unittest.mock import patch

from anthropic import APITimeoutError

from app.services.webhook_review_service import (
    process_tracked_pull_request_review,
)


def test_retry_after_temporary_failure():

    with patch(
        "app.services.webhook_review_service.update_webhook_event_status"
    ) as mock_status:

        with patch(
            "app.services.webhook_review_service.process_pull_request_review"
        ) as mock_review:

            mock_review.side_effect = [
                APITimeoutError(request=None),
                {"status": "success", "message": "Review completed"}
            ]

            with patch(
                "app.services.webhook_review_service.time.sleep"
            ) as mock_sleep:

                result = process_tracked_pull_request_review(
                    event_id=999,
                    repository_full_name="test/repository",
                    pr_number=1,
                    installation_id=123
                )

                assert mock_review.call_count == 2
                assert mock_sleep.call_count == 1

                assert result["status"] == "success"

                print("PASS: Temporary failure retried successfully.")
                print("Review attempts:", mock_review.call_count)
                print("Retry delays:", mock_sleep.call_count)


if __name__ == "__main__":
    test_retry_after_temporary_failure()

