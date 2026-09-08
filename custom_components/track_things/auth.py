"""Session rotation shared by setup and runtime, with no password retention."""

import asyncio
from collections.abc import Callable
from dataclasses import asdict
from ipaddress import ip_address
from time import time
from typing import Any

from yarl import URL

from .api import TrackThingsApi
from .api_errors import AuthenticationError
from .api_models import Session


def normalize_backend_url(value: str, allow_local_http: bool = False) -> str:
    """Require TLS except an explicitly opted-in private development endpoint."""
    try:
        url = URL(value.strip())
        host = url.host
        local = host == "localhost" or bool(host and host.endswith(".local"))
        if host and not local:
            try:
                address = ip_address(host)
                local = address.is_loopback or address.is_private
            except ValueError:
                pass
        valid = (
            host
            and url.user is None
            and not url.query_string
            and not url.fragment
            and (url.scheme == "https" or (url.scheme == "http" and allow_local_http and local))
        )
        if valid:
            return str(url).rstrip("/")
    except ValueError, TypeError, AttributeError:
        pass
    raise ValueError("Invalid backend URL")


def session_data(session: Session) -> dict[str, Any]:
    """Persist the credential pair and expiry as one config-entry update."""
    return asdict(session)


class AuthenticatedApi(TrackThingsApi):
    """Refresh once for concurrent callers; publish credentials before using them."""

    def __init__(
        self,
        *args,
        credentials: Session,
        persist: Callable[[Session], None],
        auth_failed: Callable[[], None] = lambda: None,
        clock: Callable[[], float] = time,
        **kwargs,
    ) -> None:
        super().__init__(*args, access_token=credentials.access_token, **kwargs)
        self.credentials = credentials
        self._persist = persist
        self._auth_failed = auth_failed
        self._clock = clock
        self._refresh_lock = asyncio.Lock()
        self._invalid = False
        self._closed = False

    def close(self) -> None:
        """Disable this entry's client, leaving HA's shared HTTP session open."""
        self._closed = True
        self.set_access_token(None)

    async def _ensure_session(self, rejected: Session | None = None) -> None:
        async with self._refresh_lock:
            if self._closed:
                raise RuntimeError("Track Things client is unloaded")
            if self._invalid:
                raise AuthenticationError(code="invalid_session")
            expired = self.credentials.expires_at <= self._clock() + 30
            if not expired and (rejected is None or rejected is not self.credentials):
                return
            try:
                rotated = await self.refresh_session(self.credentials.refresh_token)
            except AuthenticationError:
                self._invalid = True
                self._auth_failed()
                raise
            # No await between storage update and making the new session visible.
            self._persist(rotated)
            self.credentials = rotated
            if self._closed:
                raise RuntimeError("Track Things client is unloaded")
            self.set_access_token(rotated.access_token)

    async def request(self, method: str, path: str, **kwargs) -> Any:
        if not kwargs.get("authenticated", True):
            return await super().request(method, path, **kwargs)
        await self._ensure_session()
        used = self.credentials
        try:
            return await super().request(method, path, **kwargs)
        except AuthenticationError:
            await self._ensure_session(rejected=used)
        try:
            return await super().request(method, path, **kwargs)
        except AuthenticationError:
            self._invalid = True
            self._auth_failed()
            raise
