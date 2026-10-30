import re
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    meta_access_token: SecretStr
    meta_app_secret: SecretStr
    whatsapp_verify_token: SecretStr
    whatsapp_phone_number_id: str
    whatsapp_expected_number: str
    whatsapp_sender_mode: Literal["test", "production"] = "test"
    meta_app_id: str = ""
    whatsapp_business_account_id: str = ""
    meta_graph_version: str = "v25.0"
    database_path: Path = Path("data/vin.sqlite3")

    @field_validator("meta_access_token", "meta_app_secret", "whatsapp_verify_token")
    @classmethod
    def real_secret(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw.strip()) < 16 or raw.startswith("replace_"):
            raise ValueError("Set a real credential of at least 16 characters in .env")
        if raw != raw.strip():
            raise ValueError("Remove whitespace surrounding the credential")
        return value

    @field_validator("whatsapp_phone_number_id")
    @classmethod
    def phone_id(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9]{6,30}", value) or value == "60124182788":
            raise ValueError("Use Meta's numeric Phone Number ID, not the WhatsApp phone number")
        return value

    @field_validator("meta_graph_version")
    @classmethod
    def graph_version(cls, value: str) -> str:
        if not re.fullmatch(r"v[0-9]{2,3}\.0", value):
            raise ValueError("Expected a Graph API version such as v25.0")
        return value

    @field_validator("whatsapp_expected_number")
    @classmethod
    def expected_number(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9]{8,20}", value):
            raise ValueError("Use the sender's international display number with digits only")
        return value

    @model_validator(mode="after")
    def test_mode_is_virtual(self):
        if self.whatsapp_sender_mode == "test" and self.whatsapp_expected_number == "60124182788":
            raise ValueError("Test mode cannot use VIN's existing WhatsApp Business number")
        return self
