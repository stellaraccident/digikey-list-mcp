from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

import keyring
from keyring.errors import KeyringError

from digikey_list_mcp.config import APP_NAME, Settings

ENV_KEYS = {
    "client_id": "DIGIKEY_CLIENT_ID",
    "client_secret": "DIGIKEY_CLIENT_SECRET",
    "oauth_tokens": "DIGIKEY_OAUTH_TOKENS",
}


class CredentialStore(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...

    def delete(self, key: str) -> None: ...


class FileCredentialStore:
    """User-only fallback when no usable system keyring backend exists."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Settings.data_dir() / "credentials.json")

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data), encoding="utf-8")
        tmp_path.chmod(0o600)
        tmp_path.replace(self.path)
        self.path.chmod(0o600)

    def get(self, key: str) -> str | None:
        return self._read().get(key)

    def set(self, key: str, value: str) -> None:
        data = self._read()
        data[key] = value
        self._write(data)

    def delete(self, key: str) -> None:
        data = self._read()
        data.pop(key, None)
        self._write(data)


class SystemCredentialStore:
    """Environment overrides plus Keychain/keyring with a secure file fallback."""

    def __init__(self, fallback: CredentialStore | None = None) -> None:
        self.fallback = fallback or FileCredentialStore()

    def get(self, key: str) -> str | None:
        env_name = ENV_KEYS.get(key)
        if env_name and os.environ.get(env_name):
            return os.environ[env_name]
        try:
            value = keyring.get_password(APP_NAME, key)
        except KeyringError:
            value = None
        return value if value is not None else self.fallback.get(key)

    def set(self, key: str, value: str) -> None:
        try:
            keyring.set_password(APP_NAME, key, value)
        except KeyringError:
            self.fallback.set(key, value)

    def delete(self, key: str) -> None:
        try:
            keyring.delete_password(APP_NAME, key)
        except (KeyringError, PasswordDeleteError):
            self.fallback.delete(key)


try:
    from keyring.errors import PasswordDeleteError
except ImportError:  # pragma: no cover - compatibility with unusual keyring backends
    PasswordDeleteError = KeyringError


def default_credential_store() -> CredentialStore:
    return SystemCredentialStore()
