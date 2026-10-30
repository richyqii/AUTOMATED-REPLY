"""Check the running local server and ngrok callback without printing secrets."""

import secrets
from pathlib import Path

import httpx
from dotenv import dotenv_values


def main():
    root = Path(__file__).resolve().parents[1]
    token = dotenv_values(root / ".env").get("WHATSAPP_VERIFY_TOKEN")
    if not token:
        raise SystemExit("WHATSAPP_VERIFY_TOKEN is missing from .env")
    try:
        with httpx.Client(timeout=8, trust_env=False, follow_redirects=False) as client:
            health = client.get("http://127.0.0.1:8000/healthz")
            if health.status_code != 200:
                raise SystemExit(f"Local health check failed: HTTP {health.status_code}")
            tunnels = client.get("http://127.0.0.1:4040/api/tunnels")
            tunnels.raise_for_status()
            urls = [
                item.get("public_url", "")
                for item in tunnels.json().get("tunnels", [])
                if item.get("public_url", "").startswith("https://")
            ]
            if not urls:
                raise SystemExit("No active ngrok HTTPS endpoint")
            challenge = secrets.token_urlsafe(18)
            params = {
                "hub.mode": "subscribe",
                "hub.verify_token": token,
                "hub.challenge": challenge,
            }
            response = client.get("http://127.0.0.1:8000/webhook", params=params)
            if response.status_code != 200 or response.text != challenge:
                raise SystemExit(f"local webhook challenge failed: HTTP {response.status_code}")
            print("local webhook challenge: passed")
            public_health = client.get(urls[0].rstrip("/") + "/healthz")
            if public_health.status_code != 200:
                raise SystemExit(f"public health check failed: HTTP {public_health.status_code}")
            print("public health check: passed")
            print(f"Meta Callback URL: {urls[0].rstrip('/')}/webhook")
    except httpx.HTTPError:
        raise SystemExit(
            "Webhook probe could not reach the server or ngrok; check both processes"
        ) from None


if __name__ == "__main__":
    main()
