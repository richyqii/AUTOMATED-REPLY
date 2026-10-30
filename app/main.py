import asyncio
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.messages import PREFILLED_MESSAGE, WHATSAPP_LINK
from app.payloads import Webhook
from app.store import Store
from app.whatsapp import WhatsAppClient
from app.worker import run_worker

logger = logging.getLogger("uvicorn.error")
MAX_BODY_BYTES = 1024 * 1024


def create_app(settings: Settings | None = None, *, start_worker: bool = True) -> FastAPI:
    if settings is None:
        try:
            settings = Settings()
        except ValidationError as exc:
            fields = ", ".join(str(error["loc"][0]) for error in exc.errors())
            raise RuntimeError(f"Configure these fields in .env: {fields}") from None
    store = Store(settings.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_in_threadpool(store.initialize)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20, connect=5), follow_redirects=False
        ) as client:
            whatsapp = WhatsAppClient(settings, client)
            worker = asyncio.create_task(run_worker(store, whatsapp)) if start_worker else None
            app.state.worker = worker
            try:
                yield
            finally:
                if worker:
                    worker.cancel()
                    with suppress(asyncio.CancelledError):
                        await worker

    app = FastAPI(
        title="VIN WhatsApp Sales Automation",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store

    @app.get("/")
    async def info():
        return {
            "service": app.title,
            "whatsapp_link": WHATSAPP_LINK,
            "prefilled_message": PREFILLED_MESSAGE,
            "instruction": "Open the link, then manually press Send in WhatsApp.",
            "test_whatsapp_link": (
                f"https://wa.me/{settings.whatsapp_expected_number}"
                f"?text=Hi%2C%20I%20want%20to%20know%20more%20about%20your%20E-Invoice%20training."
                if settings.whatsapp_sender_mode == "test"
                else None
            ),
        }

    @app.get("/healthz")
    async def health():
        worker = app.state.worker
        if start_worker and (worker is None or worker.done()):
            raise HTTPException(503, "Reply worker is unavailable")
        try:
            await run_in_threadpool(store.ready)
        except Exception:
            raise HTTPException(503, "Storage is unavailable") from None
        return {"status": "ok"}

    @app.get("/webhook", response_class=PlainTextResponse)
    async def verify(request: Request):
        mode = request.query_params.get("hub.mode", "")
        token = request.query_params.get("hub.verify_token", "")
        challenge = request.query_params.get("hub.challenge")
        expected = settings.whatsapp_verify_token.get_secret_value().encode()
        if (
            mode != "subscribe"
            or not hmac.compare_digest(token.encode(), expected)
            or not challenge
        ):
            raise HTTPException(403, "Webhook verification failed")
        return challenge

    @app.post("/webhook")
    async def receive(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                raise HTTPException(413, "Payload too large")
            body.extend(chunk)
        digest = hmac.new(
            settings.meta_app_secret.get_secret_value().encode(), body, hashlib.sha256
        ).hexdigest()
        signature = request.headers.get("x-hub-signature-256", "")
        if not hmac.compare_digest(signature.encode(), f"sha256={digest}".encode()):
            raise HTTPException(403, "Invalid webhook signature")
        try:
            payload = Webhook.model_validate_json(body)
        except ValidationError:
            raise HTTPException(400, "Invalid webhook payload") from None
        messages, statuses = [], []
        if payload.object == "whatsapp_business_account":
            for entry in payload.entry:
                for change in entry.changes:
                    value = change.value
                    if (
                        change.field == "messages"
                        and value.messaging_product == "whatsapp"
                        and value.metadata.phone_number_id == settings.whatsapp_phone_number_id
                    ):
                        messages.extend(value.messages)
                        statuses.extend(value.statuses)
        try:
            await run_in_threadpool(store.ingest, messages, statuses)
        except Exception:
            logger.error("Webhook could not be committed; Meta should retry delivery")
            raise HTTPException(503, "Temporary storage failure") from None
        logger.info(
            "WhatsApp webhook stored incoming=%d statuses=%d",
            len(messages),
            len(statuses),
        )
        return {"status": "received"}

    return app
