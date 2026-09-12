from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx

from digikey_list_mcp.config import Settings
from digikey_list_mcp.digikey.auth import DigiKeyOAuth
from digikey_list_mcp.errors import DigiKeyAPIError


class DigiKeyClient:
    def __init__(
        self,
        settings: Settings,
        oauth: DigiKeyOAuth,
        *,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.oauth = oauth
        self._owns_http = http is None
        self.http = http or httpx.AsyncClient(
            base_url=settings.api_base_url,
            timeout=settings.request_timeout_seconds,
        )

    async def __aenter__(self) -> DigiKeyClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self.http.aclose()

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        expected_status: set[int] | None = None,
    ) -> Any:
        expected_status = expected_status or {200}
        token = await self.oauth.access_token()
        refreshed = False
        attempts = self.settings.max_retries + 1

        for attempt in range(attempts):
            headers = self._headers(token)
            try:
                response = await self.http.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                raise DigiKeyAPIError("Could not reach the DigiKey API.") from exc

            if response.status_code == 401 and not refreshed:
                token = await self.oauth.force_refresh()
                refreshed = True
                continue

            if response.status_code == 429 and attempt + 1 < attempts:
                retry_after = _bounded_retry_after(response.headers.get("Retry-After"))
                await asyncio.sleep(retry_after)
                continue

            if response.status_code >= 500 and attempt + 1 < attempts:
                await asyncio.sleep(0.25 * (2**attempt))
                continue

            if response.status_code not in expected_status:
                raise _api_error(response)
            if response.status_code == 204 or not response.content:
                return None
            try:
                return response.json()
            except ValueError as exc:
                raise DigiKeyAPIError(
                    "DigiKey returned a non-JSON response.",
                    status_code=response.status_code,
                    request_id=response.headers.get("X-Request-Id"),
                ) from exc

        raise DigiKeyAPIError("DigiKey request failed after retrying.")

    def _headers(self, token: str) -> dict[str, str]:
        client_id, _ = self.oauth.client_credentials()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "X-DIGIKEY-Client-Id": client_id,
            "X-DIGIKEY-Locale-Site": self.settings.locale_site,
            "X-DIGIKEY-Locale-Language": self.settings.locale_language,
            "X-DIGIKEY-Locale-Currency": self.settings.locale_currency,
        }
        if self.settings.account_id:
            headers["X-DIGIKEY-Account-Id"] = self.settings.account_id
        return headers


def _bounded_retry_after(value: str | None) -> float:
    try:
        return min(max(float(value or 1), 0), 10)
    except ValueError:
        return 1


def _api_error(response: httpx.Response) -> DigiKeyAPIError:
    details: Any = None
    message = f"DigiKey API returned HTTP {response.status_code}."
    try:
        details = response.json()
        if isinstance(details, dict):
            message = str(
                details.get("detail")
                or details.get("ErrorMessage")
                or details.get("title")
                or message
            )
    except ValueError:
        pass
    return DigiKeyAPIError(
        message,
        status_code=response.status_code,
        request_id=response.headers.get("X-Request-Id"),
        details=details,
    )
