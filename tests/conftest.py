import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.messages import PREFILLED_MESSAGE


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        meta_access_token="unit-test-access-token-only",
        meta_app_secret="unit-test-app-secret-only",
        whatsapp_verify_token="unit-test-verify-token-only",
        whatsapp_phone_number_id="123456789012345",
        whatsapp_expected_number="15551234567",
        database_path=tmp_path / "vin.sqlite3",
    )


@pytest.fixture
def app(settings):
    # Tests never start an outbound worker or contact Meta.
    return create_app(settings, start_worker=False)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def store(client, app):
    return app.state.store


def incoming(
    text=PREFILLED_MESSAGE, *, message_id="wamid.inbound1", timestamp=None, sender="60111111111"
):
    return {
        "from": sender,
        "id": message_id,
        "timestamp": str(int(time.time()) if timestamp is None else timestamp),
        "type": "text",
        "text": {"body": text},
    }


def envelope(*messages, phone_id="123456789012345", statuses=None):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "999999999999999",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": phone_id},
                            "messages": list(messages),
                            "statuses": statuses or [],
                        },
                    }
                ],
            }
        ],
    }


def post_signed(client, settings, payload):
    raw = json.dumps(payload, ensure_ascii=False).encode()
    digest = hmac.new(settings.meta_app_secret.get_secret_value().encode(), raw, hashlib.sha256)
    return client.post(
        "/webhook",
        content=raw,
        headers={"X-Hub-Signature-256": f"sha256={digest.hexdigest()}"},
    )
