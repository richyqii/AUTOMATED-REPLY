import re

import httpx

from app.config import Settings


class SendFailure(Exception):
    def __init__(self, state: str, code: str, delay: float = 0):
        super().__init__(code)
        self.state = state
        self.code = code
        self.delay = delay


class WhatsAppClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client
        self.sender_verified = False

    async def verify_sender(self) -> dict:
        """Read the Meta sender record before allowing any outbound customer reply."""
        url = (
            f"https://graph.facebook.com/{self.settings.meta_graph_version}/"
            f"{self.settings.whatsapp_phone_number_id}"
        )
        try:
            response = await self.client.get(
                url,
                params={"fields": "id,display_phone_number,verified_name"},
                headers={
                    "Authorization": f"Bearer {self.settings.meta_access_token.get_secret_value()}"
                },
            )
        except httpx.RequestError:
            raise SendFailure("failed", "sender_check_network_error") from None
        if response.status_code != 200:
            code = "unknown"
            try:
                value = response.json().get("error", {}).get("code")
                if isinstance(value, int):
                    code = str(value)
            except (ValueError, AttributeError):
                pass
            raise SendFailure("failed", f"sender_check_http_{response.status_code}_meta_{code}")
        try:
            result = response.json()
            number = re.sub(r"\D", "", result["display_phone_number"])
            if result["id"] != self.settings.whatsapp_phone_number_id:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise SendFailure("failed", "sender_check_invalid_response") from None
        if number != self.settings.whatsapp_expected_number:
            raise SendFailure("failed", "sender_check_number_mismatch")
        self.sender_verified = True
        return {
            "id": result["id"],
            "display_phone_number": result["display_phone_number"],
            "verified_name": result.get("verified_name"),
        }

    async def send(self, job: dict) -> str:
        if not self.sender_verified:
            await self.verify_sender()
        url = (
            f"https://graph.facebook.com/{self.settings.meta_graph_version}/"
            f"{self.settings.whatsapp_phone_number_id}/messages"
        )
        try:
            response = await self.client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.settings.meta_access_token.get_secret_value()}"
                },
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": job["recipient"],
                    "type": "text",
                    "text": {"preview_url": True, "body": job["reply"]},
                    "biz_opaque_callback_data": job["inbound_id"],
                },
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            # No request reached Meta. Safe to retry.
            raise SendFailure("retry", "connect_failed") from None
        except httpx.RequestError:
            # A read/write timeout may happen after Meta accepts a message.
            raise SendFailure("uncertain", "transport_outcome_unknown") from None

        if response.status_code == 429:
            try:
                delay = min(max(float(response.headers.get("Retry-After", "60")), 1), 3600)
            except ValueError:
                delay = 60
            raise SendFailure("retry", "http_429", delay)
        if response.status_code >= 500:
            raise SendFailure("uncertain", f"http_{response.status_code}")
        if not 200 <= response.status_code < 300:
            # Log only status and numeric Meta error code, never raw bodies or tokens.
            code = "unknown"
            try:
                value = response.json().get("error", {}).get("code")
                if isinstance(value, int):
                    code = str(value)
            except (ValueError, AttributeError):
                pass
            raise SendFailure("failed", f"http_{response.status_code}_meta_{code}")
        try:
            message_id = response.json()["messages"][0]["id"]
            if not isinstance(message_id, str) or not message_id:
                raise ValueError
            return message_id
        except (ValueError, KeyError, IndexError, TypeError):
            raise SendFailure("uncertain", "missing_outbound_id") from None
