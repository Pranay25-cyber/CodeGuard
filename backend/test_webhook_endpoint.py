
import hashlib
import hmac
import json
import os

from dotenv import load_dotenv
from fastapi.testclient import TestClient
from unittest.mock import patch

# Prevent database table creation during isolated Docker testing
with patch("sqlalchemy.schema.MetaData.create_all"):
    from app.main import app

load_dotenv()

secret = os.getenv("GITHUB_WEBHOOK_SECRET")

if not secret:
    raise RuntimeError("Webhook secret is missing")

# Simulated GitHub ping event
payload = b'{"zen":"Keep it logically awesome."}'

signature = "sha256=" + hmac.new(
    secret.encode("utf-8"),
    payload,
    hashlib.sha256
).hexdigest()

headers = {
    "X-GitHub-Event": "ping",
    "X-Hub-Signature-256": signature,
    "Content-Type": "application/json"
}

# Test FastAPI directly without starting a server
with TestClient(app) as client:

    response = client.post(
        "/github/webhook",
        content=payload,
        headers=headers
    )

print("HTTP Status:", response.status_code)
print("Response:", response.json())

assert response.status_code == 200
assert response.json()["status"] == "success"

print("PASS: GitHub webhook endpoint test successful.")
