from __future__ import annotations

import json
import os
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir
from pydantic import BaseModel, ConfigDict, Field

APP_NAME = "digikey-list-mcp"


def _bool_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sandbox: bool = True
    redirect_uri: str = "https://localhost"
    account_id: str | None = None
    locale_site: str = "US"
    locale_language: str = "en"
    locale_currency: str = "USD"
    request_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)
    preview_ttl_seconds: int = Field(default=900, ge=60, le=3600)

    @property
    def api_base_url(self) -> str:
        host = "sandbox-api.digikey.com" if self.sandbox else "api.digikey.com"
        return f"https://{host}"

    @property
    def authorize_url(self) -> str:
        return f"{self.api_base_url}/v1/oauth2/authorize"

    @property
    def token_url(self) -> str:
        return f"{self.api_base_url}/v1/oauth2/token"

    @classmethod
    def config_path(cls) -> Path:
        return Path(user_config_dir(APP_NAME)) / "config.json"

    @classmethod
    def data_dir(cls) -> Path:
        return Path(user_data_dir(APP_NAME))

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or cls.config_path()
        values: dict[str, object] = {}
        if path.exists():
            values = json.loads(path.read_text(encoding="utf-8"))

        env_fields = {
            "DIGIKEY_REDIRECT_URI": "redirect_uri",
            "DIGIKEY_ACCOUNT_ID": "account_id",
            "DIGIKEY_LOCALE_SITE": "locale_site",
            "DIGIKEY_LOCALE_LANGUAGE": "locale_language",
            "DIGIKEY_LOCALE_CURRENCY": "locale_currency",
        }
        for env_name, field_name in env_fields.items():
            if env_name in os.environ:
                values[field_name] = os.environ[env_name]
        if "DIGIKEY_SANDBOX" in os.environ:
            values["sandbox"] = _bool_env(os.environ["DIGIKEY_SANDBOX"])
        return cls.model_validate(values)

    def save(self, path: Path | None = None) -> Path:
        path = path or self.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)
        return path
