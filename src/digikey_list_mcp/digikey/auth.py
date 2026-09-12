from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict

from digikey_list_mcp.config import Settings
from digikey_list_mcp.credentials import CredentialStore
from digikey_list_mcp.errors import AuthenticationError, ConfigurationError


class TokenBundle(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: str
    refresh_token: str
    expires_at: float
    refresh_expires_at: float | None = None
    token_type: str = "Bearer"

    def access_is_valid(self, *, now: float | None = None, skew: int = 30) -> bool:
        return self.expires_at > (now or time.time()) + skew

    def refresh_is_valid(self, *, now: float | None = None, skew: int = 30) -> bool:
        return (
            self.refresh_expires_at is None or self.refresh_expires_at > (now or time.time()) + skew
        )


@dataclass(frozen=True)
class AuthorizationRequest:
    url: str
    state: str


class DigiKeyOAuth:
    def __init__(
        self,
        settings: Settings,
        store: CredentialStore,
        *,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self._http = http
        self._refresh_lock = asyncio.Lock()

    def client_credentials(self) -> tuple[str, str]:
        client_id = self.store.get("client_id")
        client_secret = self.store.get("client_secret")
        if not client_id or not client_secret:
            raise ConfigurationError(
                "DigiKey client credentials are missing. Run `digikey-list-mcp configure`."
            )
        return client_id, client_secret

    def begin_authorization(self) -> AuthorizationRequest:
        client_id, _ = self.client_credentials()
        state = secrets.token_urlsafe(32)
        query = urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": self.settings.redirect_uri,
                "state": state,
            }
        )
        return AuthorizationRequest(url=f"{self.settings.authorize_url}?{query}", state=state)

    def load_tokens(self) -> TokenBundle | None:
        encoded = self.store.get("oauth_tokens")
        if not encoded:
            return None
        try:
            return TokenBundle.model_validate_json(encoded)
        except ValueError as exc:
            message = "Stored DigiKey OAuth tokens are invalid; log in again."
            raise AuthenticationError(message) from exc

    def clear_tokens(self) -> None:
        self.store.delete("oauth_tokens")

    async def exchange_code(self, code: str) -> TokenBundle:
        client_id, client_secret = self.client_credentials()
        payload = await self._token_request(
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": self.settings.redirect_uri,
                "grant_type": "authorization_code",
            }
        )
        return self._save_token_response(payload)

    async def access_token(self) -> str:
        tokens = self.load_tokens()
        if tokens and tokens.access_is_valid():
            return tokens.access_token
        async with self._refresh_lock:
            tokens = self.load_tokens()
            if tokens and tokens.access_is_valid():
                return tokens.access_token
            if not tokens or not tokens.refresh_is_valid():
                raise AuthenticationError(
                    "DigiKey login is missing or expired. Run `digikey-list-mcp auth login`."
                )
            return (await self._refresh(tokens.refresh_token)).access_token

    async def force_refresh(self) -> str:
        async with self._refresh_lock:
            tokens = self.load_tokens()
            if not tokens or not tokens.refresh_is_valid():
                raise AuthenticationError(
                    "DigiKey login is missing or expired. Run `digikey-list-mcp auth login`."
                )
            return (await self._refresh(tokens.refresh_token)).access_token

    async def _refresh(self, refresh_token: str) -> TokenBundle:
        client_id, client_secret = self.client_credentials()
        payload = await self._token_request(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        )
        return self._save_token_response(payload)

    async def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        owns_client = self._http is None
        client = self._http or httpx.AsyncClient(timeout=self.settings.request_timeout_seconds)
        try:
            response = await client.post(
                self.settings.token_url,
                data=data,
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise AuthenticationError("Could not reach DigiKey's OAuth service.") from exc
        finally:
            if owns_client:
                await client.aclose()
        if response.is_error:
            message = (
                f"DigiKey OAuth failed with HTTP {response.status_code}; "
                "check the app and callback URL."
            )
            raise AuthenticationError(message)
        try:
            return response.json()
        except ValueError as exc:
            raise AuthenticationError("DigiKey OAuth returned an invalid response.") from exc

    def _save_token_response(self, payload: dict[str, Any]) -> TokenBundle:
        now = time.time()
        try:
            bundle = TokenBundle(
                access_token=payload["access_token"],
                refresh_token=payload["refresh_token"],
                expires_at=now + int(payload.get("expires_in", 1800)),
                refresh_expires_at=(
                    now + int(payload["refresh_token_expires_in"])
                    if payload.get("refresh_token_expires_in") is not None
                    else None
                ),
                token_type=payload.get("token_type", "Bearer"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthenticationError("DigiKey OAuth response omitted required tokens.") from exc
        # One serialized write keeps rotating access and refresh tokens together.
        self.store.set("oauth_tokens", bundle.model_dump_json())
        return bundle
