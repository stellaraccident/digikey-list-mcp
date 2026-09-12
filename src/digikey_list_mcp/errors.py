from __future__ import annotations

from typing import Any


class DigiKeyListError(Exception):
    """Base error with a safe message suitable for an MCP result."""


class ConfigurationError(DigiKeyListError):
    pass


class AuthenticationError(DigiKeyListError):
    pass


class PreviewError(DigiKeyListError):
    pass


class DigiKeyAPIError(DigiKeyListError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id
        self.details = details
