
import os
import hmac
import hashlib

from app.github.webhook_security import verify_webhook_signature


secret = os.environ["GITHUB_WEBHOOK_SECRET"]

payload = b'{"test":"webhook"}'

signature = "sha256=" + hmac.new(
    secret.encode("utf-8"),
    payload,
    hashlib.sha256
).hexdigest()

print("Valid signature:", verify_webhook_signature(payload, signature))

print(
    "Invalid signature:",
    verify_webhook_signature(payload, "sha256=invalid")
)
