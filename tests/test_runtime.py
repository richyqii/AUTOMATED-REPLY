import hashlib
import hmac
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app


def test_placeholder_credentials_are_rejected(settings):
    config = settings.model_dump()
    config["meta_access_token"] = "replace_with_your_system_user_access_token"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **config)
    config = settings.model_dump()
    config["whatsapp_phone_number_id"] = "60124182788"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **config)


def test_missing_config_reports_field_names_without_secret_values(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv("META_ACCESS_TOKEN", "secret-that-must-not-appear")
    with pytest.raises(RuntimeError) as exc:
        create_app()
    assert "meta_app_secret" in str(exc.value)
    assert "secret-that-must-not-appear" not in str(exc.value)


def test_uvicorn_starts_with_worker_and_serves_real_http(settings, tmp_path):
    # No inbound customer messages are submitted: this smoke test cannot send to Meta.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    env.update(
        {
            "META_ACCESS_TOKEN": settings.meta_access_token.get_secret_value(),
            "META_APP_SECRET": settings.meta_app_secret.get_secret_value(),
            "WHATSAPP_VERIFY_TOKEN": settings.whatsapp_verify_token.get_secret_value(),
            "WHATSAPP_PHONE_NUMBER_ID": settings.whatsapp_phone_number_id,
            "WHATSAPP_EXPECTED_NUMBER": settings.whatsapp_expected_number,
            "META_GRAPH_VERSION": settings.meta_graph_version,
            "DATABASE_PATH": str(settings.database_path),
        }
    )
    with (tmp_path / "server.log").open("w+") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            stdout=log,
            stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(base_url=base, timeout=1, trust_env=False) as client:
                for _ in range(100):
                    assert process.poll() is None, "Uvicorn exited before becoming ready"
                    try:
                        if client.get("/healthz").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail("Uvicorn did not become ready within 10 seconds")
                assert client.get("/").json()["service"] == "VIN WhatsApp Sales Automation"
                response = client.get(
                    "/webhook",
                    params={
                        "hub.mode": "subscribe",
                        "hub.challenge": "smoke-challenge",
                        "hub.verify_token": settings.whatsapp_verify_token.get_secret_value(),
                    },
                )
                assert response.status_code == 200
                assert response.text == "smoke-challenge"
                body = b'{"object":"whatsapp_business_account","entry":[]}'
                digest = hmac.new(
                    settings.meta_app_secret.get_secret_value().encode(), body, hashlib.sha256
                ).hexdigest()
                assert (
                    client.post(
                        "/webhook",
                        content=body,
                        headers={"x-hub-signature-256": f"sha256={digest}"},
                    ).status_code
                    == 200
                )
                assert client.get("/healthz").status_code == 200
        finally:
            process.terminate()
            process.wait(timeout=10)
        log.seek(0)
        assert "unit-test-verify-token-only" not in log.read()
