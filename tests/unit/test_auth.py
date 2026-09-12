from __future__ import annotations

import json
import time

import httpx
import pytest

from digikey_list_mcp.config import Settings
from digikey_list_mcp.digikey.auth import DigiKeyOAuth, TokenBundle


@pytest.mark.asyncio
async def test_exchange_code_saves_rotating_token_bundle_atomically(memory_store) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = (await request.aread()).decode()
        assert "grant_type=authorization_code" in body
        assert "code=abc" in body
        return httpx.Response(
            200,
            json={
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 1800,
                "refresh_token_expires_in": 7776000,
                "token_type": "BearerToken",
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    oauth = DigiKeyOAuth(Settings(), memory_store, http=http)
    bundle = await oauth.exchange_code("abc")
    await http.aclose()

    assert bundle.access_token == "access"
    assert [key for key, _ in memory_store.writes] == ["oauth_tokens"]
    saved = TokenBundle.model_validate_json(memory_store.get("oauth_tokens"))
    assert saved.refresh_token == "refresh"


@pytest.mark.asyncio
async def test_expired_access_token_refreshes_and_replaces_refresh_token(memory_store) -> None:
    memory_store.set(
        "oauth_tokens",
        TokenBundle(
            access_token="old-access",
            refresh_token="old-refresh",
            expires_at=time.time() - 5,
            refresh_expires_at=time.time() + 500,
        ).model_dump_json(),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        body = (await request.aread()).decode()
        assert "refresh_token=old-refresh" in body
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 1800,
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    oauth = DigiKeyOAuth(Settings(), memory_store, http=http)
    assert await oauth.access_token() == "new-access"
    await http.aclose()
    assert json.loads(memory_store.get("oauth_tokens"))["refresh_token"] == "new-refresh"


def test_authorization_url_has_state_and_exact_redirect(memory_store) -> None:
    oauth = DigiKeyOAuth(Settings(redirect_uri="https://localhost/callback"), memory_store)
    request = oauth.begin_authorization()
    assert "response_type=code" in request.url
    assert "redirect_uri=https%3A%2F%2Flocalhost%2Fcallback" in request.url
    assert request.state in request.url
