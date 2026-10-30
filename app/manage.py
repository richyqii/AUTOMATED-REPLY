"""Local staff and Meta setup tools. No public administration endpoint."""

import argparse
import asyncio
import json
import re

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.whatsapp import SendFailure, WhatsAppClient


def safe_meta_error(response: httpx.Response) -> str:
    """Keep only numeric API error codes, never Meta response bodies or tokens."""
    code = "unknown"
    try:
        value = response.json().get("error", {}).get("code")
        if isinstance(value, int):
            code = str(value)
    except (ValueError, AttributeError):
        pass
    return f"HTTP {response.status_code}, Meta code {code}"


def probe_settings() -> Settings:
    """Load only the Meta GET/POST account credentials; webhook secrets are unused here."""
    return Settings(
        meta_app_secret="unused-in-read-only-meta-probe",
        whatsapp_verify_token="unused-in-read-only-meta-probe",
    )


async def test_sender(settings: Settings) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        return await WhatsAppClient(settings, client).verify_sender()


def subscription(settings: Settings, *, create: bool) -> str:
    if not settings.whatsapp_business_account_id:
        raise ValueError("Set WHATSAPP_BUSINESS_ACCOUNT_ID in .env")
    if not re.fullmatch(r"[0-9]{6,30}", settings.whatsapp_business_account_id):
        raise ValueError("WHATSAPP_BUSINESS_ACCOUNT_ID must be numeric")
    if create and not settings.meta_app_id:
        raise ValueError("Set META_APP_ID in .env before subscribing")
    if settings.meta_app_id and not re.fullmatch(r"[0-9]{6,30}", settings.meta_app_id):
        raise ValueError("META_APP_ID must be numeric")
    base = f"https://graph.facebook.com/{settings.meta_graph_version}"
    headers = {"Authorization": f"Bearer {settings.meta_access_token.get_secret_value()}"}
    waba = settings.whatsapp_business_account_id
    try:
        with httpx.Client(timeout=15, headers=headers) as client:
            # Check that this WABA owns the configured sender before a write.
            numbers = client.get(f"{base}/{waba}/phone_numbers")
            if numbers.status_code != 200:
                return f"WABA phone-number check failed: {safe_meta_error(numbers)}"
            try:
                entries = numbers.json()["data"]
                sender = next(
                    (
                        item
                        for item in entries
                        if str(item["id"]) == settings.whatsapp_phone_number_id
                    ),
                    None,
                )
            except (ValueError, KeyError, TypeError, AttributeError):
                return "Meta returned an unexpected WABA phone-number response"
            if sender is None:
                return "Configured Phone Number ID is not in this WABA; no subscription was changed"
            display = re.sub(r"\D", "", sender.get("display_phone_number", ""))
            if display != settings.whatsapp_expected_number:
                return "WABA sender display number does not match; no subscription was changed"
            url = f"{base}/{waba}/subscribed_apps"
            response = client.get(url)
            if response.status_code != 200:
                return f"Subscription check failed: {safe_meta_error(response)}"
            try:
                entries = response.json()["data"]
                apps = {
                    str(item.get("whatsapp_business_api_data", {}).get("id", item.get("id", "")))
                    for item in entries
                }
            except (ValueError, KeyError, TypeError, AttributeError):
                return "Meta returned an unexpected subscription response"
            if not settings.meta_app_id:
                names = [
                    {
                        "id": item.get("whatsapp_business_api_data", {}).get("id", item.get("id")),
                        "name": item.get("whatsapp_business_api_data", {}).get(
                            "name", item.get("name")
                        ),
                    }
                    for item in entries
                ]
                return "Set META_APP_ID to verify your app. WABA subscriptions: " + json.dumps(
                    names
                )
            if settings.meta_app_id in apps:
                return "This Meta app is already subscribed to the configured WABA"
            if not create:
                return "This Meta app is not subscribed to the configured WABA"
            if settings.whatsapp_sender_mode != "test":
                return "Automatic subscription is restricted to test mode"
            # Only subscribe after verifying the exact Phone Number ID and WABA.
            response = client.post(url)
            if response.status_code != 200:
                return f"Test WABA subscription failed: {safe_meta_error(response)}"
            return "Subscribed this Meta app to the configured test WABA; check again to verify"
    except httpx.RequestError:
        return "Meta network request failed; check connectivity"


def main():
    parser = argparse.ArgumentParser(description="VIN WhatsApp staff and setup tools")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Queue counts and failed/uncertain delivery codes")
    sub.add_parser("help-requests", help="Read unresolved customer support requests (private data)")
    resume = sub.add_parser("resume", help="Resolve support requests and resume future replies")
    resume.add_argument("recipient", help="Customer WhatsApp ID, digits only")
    sub.add_parser("check-meta", help="Read-only check of the configured sender")
    sub.add_parser("check-subscription", help="Read-only check of the WABA subscription")
    sub.add_parser("subscribe-test-waba", help="Subscribe this app to its checked test WABA")
    sub.add_parser(
        "retry-expired-token-replies",
        help="After refreshing the token and restarting the server, requeue safe failed replies",
    )
    args = parser.parse_args()

    if args.command in {"check-meta", "check-subscription", "subscribe-test-waba"}:
        try:
            settings = probe_settings()
        except ValidationError:
            parser.exit(2, "Set META_ACCESS_TOKEN, Phone Number ID, and expected sender in .env.\n")

    if args.command == "check-meta":
        try:
            result = asyncio.run(test_sender(settings))
        except SendFailure as exc:
            parser.exit(1, f"Sender check failed: {exc.code}. No message sent.\n")
        print(json.dumps(result))
        print("Configured sender matches the expected number. No message was sent.")
        return

    if args.command in {"check-subscription", "subscribe-test-waba"}:
        try:
            result = subscription(settings, create=args.command == "subscribe-test-waba")
        except ValueError as exc:
            parser.exit(1, f"{exc}\n")
        print(result)
        if not (
            result.startswith("This Meta app is already subscribed")
            or result.startswith("Subscribed this Meta app")
        ):
            parser.exit(1)
        return

    try:
        app = create_app(start_worker=False)
    except RuntimeError as exc:
        parser.exit(2, f"{exc}\n")
    store = app.state.store
    store.initialize()
    if args.command == "retry-expired-token-replies":
        try:
            asyncio.run(test_sender(Settings()))
        except SendFailure as exc:
            parser.exit(1, f"Fresh sender check failed: {exc.code}. No job was retried.\n")
        count = store.retry_expired_token_failures()
        print(f"Requeued {count} customer-initiated reply job(s) that failed before sending.")
        return
    with store.connect() as db:
        if args.command == "status":
            rows = db.execute("SELECT state, COUNT(*) AS count FROM jobs GROUP BY state").fetchall()
            print("Job states:")
            print(json.dumps([dict(row) for row in rows], indent=2))
            deliveries = db.execute(
                "SELECT delivery_status, COUNT(*) AS count FROM jobs "
                "WHERE delivery_status IS NOT NULL GROUP BY delivery_status"
            ).fetchall()
            print("Meta delivery states:")
            print(json.dumps([dict(row) for row in deliveries], indent=2))
            problems = db.execute(
                """SELECT state, error, delivery_status, COUNT(*) AS count FROM jobs
                   WHERE state IN ('failed', 'uncertain', 'expired') OR delivery_status = 'failed'
                   GROUP BY state, error, delivery_status"""
            ).fetchall()
            print("Problems requiring review:")
            print(json.dumps([dict(row) for row in problems], indent=2))
        elif args.command == "help-requests":
            rows = db.execute(
                """SELECT recipient, received_at, body FROM help_requests
                   WHERE resolved = 0 ORDER BY received_at"""
            ).fetchall()
            print(json.dumps([dict(row) for row in rows], indent=2, ensure_ascii=True))
        elif args.command == "resume":
            if not re.fullmatch(r"[0-9]{6,20}", args.recipient):
                parser.error("Recipient must contain 6 to 20 digits")
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE contacts SET paused = 0 WHERE recipient = ?", (args.recipient,))
            db.execute(
                "UPDATE help_requests SET resolved = 1 WHERE recipient = ?", (args.recipient,)
            )
            print("Support requests resolved; future incoming messages can receive replies.")


if __name__ == "__main__":
    main()
