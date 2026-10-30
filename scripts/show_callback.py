"""Print the active ngrok HTTPS callback, without reading or printing secrets."""

import httpx


def main():
    try:
        response = httpx.get("http://127.0.0.1:4040/api/tunnels", timeout=3, trust_env=False)
        response.raise_for_status()
        tunnels = response.json().get("tunnels", [])
    except (httpx.HTTPError, ValueError):
        raise SystemExit(
            "No ngrok local API found. Start scripts/start_tunnel.ps1 first."
        ) from None
    urls = [
        t.get("public_url", "") for t in tunnels if t.get("public_url", "").startswith("https://")
    ]
    if not urls:
        raise SystemExit("ngrok has no active HTTPS tunnel for this service.")
    print(f"Meta Callback URL: {urls[0].rstrip('/')}/webhook")
    print("Verify Token: use the private WHATSAPP_VERIFY_TOKEN value from .env")


if __name__ == "__main__":
    main()
