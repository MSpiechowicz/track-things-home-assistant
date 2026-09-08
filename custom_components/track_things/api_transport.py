"""Shared-session HTTP transport with bounded read retries and safe failures."""

import asyncio
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import aiohttp
from yarl import URL

from .api_errors import (
    ApiError,
    ApiTimeoutError,
    AuthenticationError,
    ConflictError,
    InvalidResponseError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    TransportError,
)

# Only fixed, known machine codes may cross the trust boundary into logs.
_SAFE_CODES = frozenset(
    {
        "invalid_request",
        "invalid_cursor",
        "invalid_session",
        "rate_limited",
        "auth_unavailable",
        "tracker_schema_changed",
        "tracker_schema_unavailable",
        "idempotency_conflict",
        "entry_version_conflict",
    }
)
_ERROR_TYPES = {
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    429: RateLimitError,
}


def retry_after_seconds(value: str | None) -> float | None:
    """Support both HTTP Retry-After forms; malformed headers use local backoff."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                return None
            seconds = (date - datetime.now(UTC)).total_seconds()
        except ValueError, TypeError, OverflowError:
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


class ApiTransport:
    """Borrows the caller's session and never closes or mutates it."""

    def __init__(
        self,
        base_url: str,
        session: aiohttp.ClientSession,
        *,
        access_token: str | None = None,
        timeout: float = 15,
        read_retries: int = 2,
        max_retry_delay: float = 30,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        try:
            url = URL(base_url)
            valid = (
                url.scheme in {"http", "https"}
                and url.host
                and url.user is None
                and not url.query_string
                and not url.fragment
            )
        except ValueError, TypeError:
            valid = False
        if not valid:
            raise ValueError("A backend HTTP(S) URL without credentials/query/fragment is required")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        if type(read_retries) is not int or not 0 <= read_retries <= 5:
            raise ValueError("read_retries must be between zero and five")
        if not math.isfinite(max_retry_delay) or not 0 <= max_retry_delay <= 60:
            raise ValueError("max_retry_delay must be between zero and sixty seconds")
        self._base_url = str(url).rstrip("/")
        self._session = session
        self._access_token = access_token
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._read_retries = read_retries
        self._max_retry_delay = max_retry_delay
        self._sleep = sleep

    def set_access_token(self, access_token: str | None) -> None:
        """Update only this client's authorization, never shared session headers."""
        self._access_token = access_token

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
        authenticated: bool = True,
        idempotency_key: str | None = None,
    ) -> Any:
        """Return JSON, retrying GET only and releasing responses before sleeping."""
        headers = {"Accept": "application/json"}
        if authenticated and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        if idempotency_key is not None:
            if not 1 <= len(idempotency_key) <= 255 or any(
                not 33 <= ord(char) <= 126 for char in idempotency_key
            ):
                raise ValueError("Invalid idempotency key")
            headers["Idempotency-Key"] = idempotency_key
        attempts = 1 + (self._read_retries if method == "GET" else 0)
        for attempt in range(attempts):
            error: ApiError
            try:
                async with self._session.request(
                    method,
                    self._base_url + path,
                    headers=headers,
                    params=params,
                    json=body,
                    timeout=self._timeout,
                    allow_redirects=False,
                    raise_for_status=False,
                ) as response:
                    if 200 <= response.status < 300:
                        try:
                            return await response.json()
                        except ValueError, aiohttp.ContentTypeError, UnicodeError:
                            error = InvalidResponseError(code="invalid_json")
                    else:
                        code = "request_failed"
                        try:
                            payload = await response.json()
                            candidate = payload.get("error", {}).get("code")
                            if isinstance(candidate, str) and candidate in _SAFE_CODES:
                                code = candidate
                        except ValueError, AttributeError, aiohttp.ContentTypeError, UnicodeError:
                            pass
                        error_type = _ERROR_TYPES.get(
                            response.status, ServerError if response.status >= 500 else ApiError
                        )
                        error = error_type(
                            response.status,
                            code=code,
                            retry_after=retry_after_seconds(response.headers.get("Retry-After")),
                        )
            except TimeoutError:
                error = ApiTimeoutError(code="timeout")
            except aiohttp.ClientError:
                error = TransportError(code="transport_error")
            # Raise outside the original exception handler to avoid retaining secrets
            # in exception chains, including connection-error URLs and headers.
            retryable = isinstance(error, (TransportError, ServerError, RateLimitError))
            delay = error.retry_after if error.retry_after is not None else 2**attempt
            if not retryable or attempt + 1 == attempts or delay > self._max_retry_delay:
                raise error from None
            await self._sleep(delay)
        raise AssertionError("unreachable")
