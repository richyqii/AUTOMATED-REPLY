import asyncio
import time

import httpx
import pytest

from app.payloads import Message
from app.whatsapp import WhatsAppClient
from app.worker import process_one
from tests.conftest import envelope, incoming, post_signed
from tests.test_webhook import rows


def run_send(settings, store, handler):
    def meta(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": settings.whatsapp_phone_number_id,
                    "display_phone_number": "+1 (555) 123-4567",
                },
            )
        return handler(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(meta)) as client:
            return await process_one(store, WhatsAppClient(settings, client))

    return asyncio.run(run())


def test_official_api_request_and_no_duplicate_send(client, settings, store):
    post_signed(client, settings, envelope(incoming()))
    calls = []

    def meta(request):
        import json

        calls.append(request)
        assert str(request.url) == "https://graph.facebook.com/v25.0/123456789012345/messages"
        assert request.headers["authorization"] == "Bearer unit-test-access-token-only"
        body = json.loads(request.content)
        assert body["messaging_product"] == "whatsapp"
        assert body["to"] == "60111111111"
        assert body["type"] == "text"
        assert body["text"]["body"] == rows(store)[0]["reply"]
        assert body["biz_opaque_callback_data"] == "wamid.inbound1"
        return httpx.Response(200, json={"messages": [{"id": "wamid.outbound"}]})

    assert run_send(settings, store, meta)
    assert rows(store)[0]["state"] == "sent"
    post_signed(client, settings, envelope(incoming()))
    assert not run_send(settings, store, meta)
    assert len(calls) == 1


def test_sender_mismatch_prevents_outbound_message(client, settings, store):
    post_signed(client, settings, envelope(incoming()))
    calls = []

    async def run():
        def meta(request):
            calls.append(request.method)
            return httpx.Response(
                200,
                json={
                    "id": settings.whatsapp_phone_number_id,
                    "display_phone_number": "+60 12-418 2788",
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(meta)) as http:
            return await process_one(store, WhatsAppClient(settings, http))

    asyncio.run(run())
    assert calls == ["GET"]
    assert rows(store)[0]["error"] == "sender_check_number_mismatch"


@pytest.mark.parametrize(
    "status,expected", [(401, "failed"), (400, "failed"), (429, "retry"), (503, "uncertain")]
)
def test_api_failures(client, settings, store, status, expected):
    post_signed(client, settings, envelope(incoming()))
    run_send(
        settings,
        store,
        lambda request: httpx.Response(
            status, json={"error": {"code": 190}}, headers={"Retry-After": "10"}
        ),
    )
    job = rows(store)[0]
    assert job["state"] == expected
    assert job["attempts"] == 1
    assert store.claim() is None


@pytest.mark.parametrize(
    "exception,expected",
    [
        (httpx.ReadTimeout, "uncertain"),
        (httpx.WriteError, "uncertain"),
        (httpx.ConnectError, "retry"),
        (httpx.ConnectTimeout, "retry"),
    ],
)
def test_network_failure_safety(client, settings, store, exception, expected):
    post_signed(client, settings, envelope(incoming()))

    def meta(request):
        raise exception("test only", request=request)

    run_send(settings, store, meta)
    assert rows(store)[0]["state"] == expected


def test_retry_limit(client, settings, store):
    post_signed(client, settings, envelope(incoming()))
    with store.connect() as db:
        db.execute("UPDATE jobs SET attempts = 4")
    run_send(settings, store, lambda request: httpx.Response(429))
    assert rows(store)[0]["state"] == "failed"


def test_crashed_worker_becomes_uncertain_not_resent(client, settings, store):
    post_signed(client, settings, envelope(incoming()))
    assert store.claim() is not None
    assert store.claim() is None
    with store.connect() as db:
        db.execute("UPDATE jobs SET lease_until = ?", (time.time() - 1,))
    assert store.claim() is None
    assert rows(store)[0]["state"] == "uncertain"


def test_expired_token_failure_can_be_safely_requeued(client, settings, store):
    post_signed(client, settings, envelope(incoming()))
    job = store.claim()
    store.finish(job["inbound_id"], "failed", error="sender_check_http_401_meta_190")
    assert store.retry_expired_token_failures() == 1
    assert store.claim()["inbound_id"] == job["inbound_id"]
    assert store.retry_expired_token_failures() == 0


def test_window_checked_again_before_delivery(client, settings, store):
    post_signed(client, settings, envelope(incoming()))
    with store.connect() as db:
        db.execute("UPDATE jobs SET inbound_at = ?", (int(time.time()) - 86400,))
    assert store.claim() is None
    assert rows(store)[0]["state"] == "expired"


def test_delivery_receipt_reconciles_uncertain_job(client, settings, store):
    post_signed(client, settings, envelope(incoming()))
    store.claim()
    store.finish("wamid.inbound1", "uncertain", error="transport_outcome_unknown")
    post_signed(
        client,
        settings,
        envelope(
            statuses=[
                {
                    "id": "wamid.outbound",
                    "status": "delivered",
                    "timestamp": str(int(time.time())),
                    "biz_opaque_callback_data": "wamid.inbound1",
                }
            ]
        ),
    )
    job = rows(store)[0]
    assert job["state"] == "sent"
    assert job["delivery_status"] == "delivered"
    assert job["outbound_id"] == "wamid.outbound"
    assert store.claim() is None


def test_statuses_cannot_regress_to_older_timestamp(client, settings, store):
    post_signed(client, settings, envelope(incoming()))
    store.claim()
    store.finish("wamid.inbound1", "sent", outbound_id="wamid.outbound")
    for state, timestamp in [("read", 200), ("sent", 200), ("sent", 100)]:
        post_signed(
            client,
            settings,
            envelope(
                statuses=[
                    {
                        "id": "wamid.outbound",
                        "status": state,
                        "timestamp": str(timestamp),
                    }
                ]
            ),
        )
    assert rows(store)[0]["delivery_status"] == "read"


def test_repeated_help_is_deduplicated(client, settings, store):
    payload = envelope(incoming("HELP"))
    post_signed(client, settings, payload)
    post_signed(client, settings, payload)
    assert len(rows(store, "help_requests")) == 1


def test_claim_is_exclusive(store):
    from concurrent.futures import ThreadPoolExecutor

    store.ingest([Message.model_validate(incoming())], [])
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: store.claim(), [1, 2]))
    assert sum(result is not None for result in results) == 1
