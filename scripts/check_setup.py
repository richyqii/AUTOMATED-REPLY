"""Inspect local setup without printing any credential values."""

import os
import shutil
from pathlib import Path

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
values = {**dotenv_values(root / ".env"), **os.environ}
for key in (
    "META_ACCESS_TOKEN",
    "META_APP_SECRET",
    "META_APP_ID",
    "WHATSAPP_VERIFY_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_EXPECTED_NUMBER",
    "WHATSAPP_BUSINESS_ACCOUNT_ID",
    "NGROK_AUTHTOKEN",
):
    value = (values.get(key) or "").strip()
    state = "missing" if not value else "placeholder" if value.startswith("replace_") else "set"
    print(f"{key}: {state}")
print(f"ngrok executable on PATH: {'installed' if shutil.which('ngrok') else 'missing'}")
ngrok_config = Path(os.environ.get("LOCALAPPDATA", "")) / "ngrok" / "ngrok.yml"
print(
    "ngrok local configuration: "
    + ("present" if ngrok_config.is_file() else "not visible here; run ngrok config check")
)
print(f"queue database: {'exists' if (root / 'data/vin.sqlite3').exists() else 'not created'}")
