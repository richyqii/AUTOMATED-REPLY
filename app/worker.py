import asyncio
import logging

from app.store import Store
from app.whatsapp import SendFailure, WhatsAppClient

logger = logging.getLogger("uvicorn.error")


async def process_one(store: Store, whatsapp: WhatsAppClient) -> bool:
    job = await asyncio.to_thread(store.claim)
    if job is None:
        return False
    try:
        outbound_id = await whatsapp.send(job)
    except SendFailure as exc:
        state = exc.state
        if state == "retry" and job["attempts"] >= 5:
            state = "failed"
        delay = max(exc.delay, min(2 ** job["attempts"], 300))
        await asyncio.to_thread(store.finish, job["inbound_id"], state, error=exc.code, delay=delay)
        logger.warning("Reply outcome state=%s reason=%s", state, exc.code)
    else:
        await asyncio.to_thread(store.finish, job["inbound_id"], "sent", outbound_id=outbound_id)
        logger.info("Reply accepted by WhatsApp Cloud API")
    return True


async def run_worker(store: Store, whatsapp: WhatsAppClient):
    while True:
        try:
            busy = await process_one(store, whatsapp)
        except Exception:
            # Preserve the lease for uncertain-outcome recovery; avoid logging payloads.
            logger.error("Reply worker failed; inspect the database and service configuration")
            busy = False
        await asyncio.sleep(1 if busy else 0.5)
