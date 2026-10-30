import hashlib
import hmac
import time
from urllib.parse import parse_qs, urlparse

import pytest

from app.main import MAX_BODY_BYTES
from app.messages import PREFILLED_MESSAGE, SALES_REPLY, WHATSAPP_LINK, intent
from app.store import Store
from tests.conftest import envelope, incoming, post_signed


def rows(store, table="jobs"):
    assert table in {"jobs", "help_requests", "contacts"}
    with store.connect() as db:
        return [dict(row) for row in db.execute(f"SELECT * FROM {table}").fetchall()]


def test_link_only_prefills(client, store):
    parsed = urlparse(WHATSAPP_LINK)
    assert parsed.netloc == "wa.me"
    assert parsed.path == "/60124182788"
    assert parse_qs(parsed.query)["text"] == [PREFILLED_MESSAGE]
    assert client.get("/").json()["whatsapp_link"] == WHATSAPP_LINK
    assert rows(store) == []


def test_verification_is_plain_text(client, settings):
    params = {
        "hub.mode": "subscribe",
        "hub.challenge": "123456789",
        "hub.verify_token": settings.whatsapp_verify_token.get_secret_value(),
    }
    response = client.get("/webhook", params=params)
    assert response.status_code == 200
    assert response.text == "123456789"
    assert response.headers["content-type"].startswith("text/plain")
    params["hub.verify_token"] = "wrong"
    assert client.get("/webhook", params=params).status_code == 403
    assert client.get("/webhook").status_code == 403


def test_unsigned_and_tampered_requests_are_rejected(client, settings, store):
    assert client.post("/webhook", json=envelope(incoming())).status_code == 403
    response = client.post(
        "/webhook",
        json=envelope(incoming()),
        headers={"x-hub-signature-256": "sha256=invalid"},
    )
    assert response.status_code == 403
    assert rows(store) == []


def test_exact_sales_reply_queued_and_deduplicated_across_restart(client, settings, store):
    payload = envelope(incoming())
    assert post_signed(client, settings, payload).status_code == 200
    assert post_signed(client, settings, payload).status_code == 200
    reopened = Store(store.path)
    reopened.initialize()
    jobs = rows(reopened)
    assert len(jobs) == 1
    assert jobs[0]["reply"] == SALES_REPLY
    assert jobs[0]["recipient"] == "60111111111"
    assert jobs[0]["state"] == "pending"
    assert len(SALES_REPLY) < 4096


@pytest.mark.parametrize(
    "text", ["E-INVOICE training", "eInvoice", "E–Invoice", "e invoicing", "e-invois"]
)
def test_keyword_variants(text):
    assert intent(text) == "sales"


def test_batched_messages_and_wrong_phone(client, settings, store):
    payload = envelope(incoming(message_id="1"), incoming(message_id="2", sender="60222222222"))
    payload["entry"].append(envelope(incoming(message_id="3"))["entry"][0])
    assert post_signed(client, settings, payload).status_code == 200
    assert len(rows(store)) == 3
    assert (
        post_signed(
            client, settings, envelope(incoming(message_id="4"), phone_id="other")
        ).status_code
        == 200
    )
    assert len(rows(store)) == 3


def test_status_events_do_not_reply(client, settings, store):
    response = post_signed(
        client,
        settings,
        envelope(
            statuses=[
                {
                    "id": "wamid.out",
                    "status": "delivered",
                    "timestamp": str(int(time.time())),
                }
            ]
        ),
    )
    assert response.status_code == 200
    assert rows(store) == []


def test_unknown_media_and_stale_messages_do_not_reply(client, settings, store):
    media = incoming(message_id="media")
    media["type"] = "image"
    media.pop("text")
    payload = envelope(
        incoming("Hello there", message_id="unknown"),
        media,
        incoming(message_id="stale", timestamp=int(time.time()) - 86400),
        incoming(message_id="future", timestamp=int(time.time()) + 1000),
    )
    assert post_signed(client, settings, payload).status_code == 200
    assert {job["state"] for job in rows(store)} == {"ignored"}
    assert store.claim() is None


def test_help_saves_followups_and_pauses_sales_until_start(client, settings, store):
    for text, mid in [("HELP", "h1"), ("I cannot find my receipt", "h2"), ("E-Invoice", "h3")]:
        assert (
            post_signed(client, settings, envelope(incoming(text, message_id=mid))).status_code
            == 200
        )
    assert len(rows(store, "help_requests")) == 3
    assert rows(store, "contacts")[0]["paused"] == 1
    assert [job["state"] for job in rows(store)] == ["pending", "suppressed", "suppressed"]
    job = store.claim()
    assert job["kind"] == "help"
    store.finish(job["inbound_id"], "sent", outbound_id="wamid.help")
    assert store.claim() is None
    post_signed(client, settings, envelope(incoming("START", message_id="start")))
    assert rows(store, "contacts")[0]["paused"] == 0
    assert all(row["resolved"] for row in rows(store, "help_requests"))
    assert store.claim()["kind"] == "start"


def test_stop_suppresses_queued_sales_and_requires_start(client, settings, store):
    for text, mid in [("e-invoice", "sales"), ("STOP", "stop"), ("e-invoice", "later")]:
        post_signed(client, settings, envelope(incoming(text, message_id=mid)))
    assert store.claim() is None
    assert rows(store, "contacts")[0]["opted_out"] == 1
    post_signed(client, settings, envelope(incoming("START", message_id="start")))
    assert store.claim()["kind"] == "start"


def test_start_does_not_revive_sales_cancelled_by_help(client, settings, store):
    for text, mid in [("e-invoice", "sales"), ("HELP", "help"), ("START", "start")]:
        post_signed(client, settings, envelope(incoming(text, message_id=mid)))
    assert rows(store)[0]["state"] == "suppressed"


def test_old_start_cannot_undo_stop(client, settings, store):
    post_signed(client, settings, envelope(incoming("STOP")))
    post_signed(client, settings, envelope(incoming("START", message_id="old", timestamp=1)))
    assert rows(store, "contacts")[0]["opted_out"] == 1


def test_storage_error_returns_retryable_http_status(client, settings, store, monkeypatch):
    def fail(*_):
        raise OSError("database full")

    monkeypatch.setattr(store, "ingest", fail)
    assert post_signed(client, settings, envelope(incoming())).status_code == 503


def test_invalid_json_and_payload_limit(client, settings):
    raw = b"not-json"
    digest = hmac.new(settings.meta_app_secret.get_secret_value().encode(), raw, hashlib.sha256)
    assert (
        client.post(
            "/webhook", content=raw, headers={"x-hub-signature-256": f"sha256={digest.hexdigest()}"}
        ).status_code
        == 400
    )
    assert client.post("/webhook", content=b"x" * (MAX_BODY_BYTES + 1)).status_code == 413


def test_health(client):
    assert client.get("/healthz").json() == {"status": "ok"}
