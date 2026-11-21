
from unittest.mock import patch

from anthropic import APITimeoutError

from app.services.webhook_review_service import (
    process_tracked_pull_request_review,
)


def test_maximum_retry_attempts():

    with patch(
        "app.services.webhook_review_service.update_webhook_event_status"
    ) as mock_status:

        with patch(
            "app.services.webhook_review_service.process_pull_request_review"
        ) as mock_review:

            mock_review.side_effect = APITimeoutError(request=None)

            with patch(
                "app.services.webhook_review_service.time.sleep"
            ) as mock_sleep:

                try:
                    process_tracked_pull_request_review(
                        event_id=999,
                        repository_full_name="test/repository",
                        pr_number=1,
                        installation_id=123
                    )

                except APITimeoutError:
                    print("PASS: Maximum retry limit reached.")

                else:
                    raise AssertionError(
                        "Expected APITimeoutError was not raised"
                    )

                assert mock_review.call_count == 3
                assert mock_sleep.call_count == 2

                statuses = [
                    call.args[1]
                    for call in mock_status.call_args_list
                ]

                assert statuses == [
                    "processing",
                    "failed"
                ]

                print("Total attempts:", mock_review.call_count)
                print("Retry delays:", mock_sleep.call_count)
                print("Webhook statuses:", statuses)


if __name__ == "__main__":
    test_maximum_retry_attempts()
