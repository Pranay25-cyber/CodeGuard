
import hashlib
import hmac
import os
from pathlib import Path

from dotenv import load_dotenv


# Load environment variables from backend/.env
BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


def verify_webhook_signature(
    payload: bytes,
    signature: str | None
) -> bool:
    """
    Verify that a GitHub webhook request has a valid signature.
    """

    secret = os.getenv("GITHUB_WEBHOOK_SECRET")

    if not secret:
        raise RuntimeError("GitHub webhook secret is not configured.")

    if not signature:
        return False

    if not signature.startswith("sha256="):
        return False

    expected_signature = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(
        expected_signature,
        signature
    )
