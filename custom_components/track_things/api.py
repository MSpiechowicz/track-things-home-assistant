"""Async Track Things client. Supply Home Assistant's async_get_clientsession(hass)."""

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from .api_decode import decode, decode_page, decode_session
from .api_errors import InvalidResponseError
from .api_models import (
    CursorPage,
    Entry,
    EntryCreate,
    EntryFilters,
    SchemaVersion,
    Session,
    Subject,
    Tracker,
    User,
    Workspace,
)
from .api_transport import ApiTransport


def _path(*parts: str) -> str:
    """Encode each resource ID so it cannot change the endpoint or origin."""
    if any(not part or part in {".", ".."} for part in parts):
        raise ValueError("Resource IDs must be nonempty path segments")
    return "/" + "/".join(quote(part, safe="") for part in parts)


class TrackThingsApi(ApiTransport):
    """Resource reads and explicit entry creation; token persistence belongs to callers."""

    async def sign_in(self, identifier: str, password: str) -> Session:
        return decode_session(
            await self.request(
                "POST",
                "/auth/password",
                authenticated=False,
                body={"identifier": identifier, "password": password},
            )
        )

    async def refresh_session(self, refresh_token: str) -> Session:
        return decode_session(
            await self.request(
                "POST",
                "/auth/refresh",
                authenticated=False,
                body={"refresh_token": refresh_token},
            )
        )

    async def get_user(self) -> User:
        return decode(await self.request("GET", "/api/users/me"), User)

    async def get_workspace(self, workspace_id: str) -> Workspace:
        return decode(
            await self.request("GET", _path("api", "workspaces", workspace_id)), Workspace
        )

    async def get_tracker(self, workspace_id: str, tracker_id: str) -> Tracker:
        return decode(
            await self.request(
                "GET",
                _path("api", "workspaces", workspace_id, "trackers", tracker_id),
            ),
            Tracker,
        )

    async def get_subject(self, workspace_id: str, subject_id: str) -> Subject:
        return decode(
            await self.request(
                "GET",
                _path("api", "workspaces", workspace_id, "subjects", subject_id),
            ),
            Subject,
        )

    async def get_schema_version(
        self,
        workspace_id: str,
        tracker_id: str,
        schema_version_id: str,
    ) -> SchemaVersion:
        return decode(
            await self.request(
                "GET",
                _path(
                    "api",
                    "workspaces",
                    workspace_id,
                    "trackers",
                    tracker_id,
                    "schema-versions",
                    schema_version_id,
                ),
            ),
            SchemaVersion,
        )

    async def get_entry(self, workspace_id: str, entry_id: str) -> Entry:
        return decode(
            await self.request(
                "GET",
                _path("api", "workspaces", workspace_id, "entries", entry_id),
            ),
            Entry,
        )

    async def list_workspaces(
        self, *, cursor: str | None = None, limit: int = 50
    ) -> CursorPage[Workspace]:
        return await self._page("/api/workspaces", Workspace, cursor, limit)

    async def list_trackers(
        self,
        workspace_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> CursorPage[Tracker]:
        return await self._page(
            _path("api", "workspaces", workspace_id, "trackers"),
            Tracker,
            cursor,
            limit,
        )

    async def list_subjects(
        self,
        workspace_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> CursorPage[Subject]:
        return await self._page(
            _path("api", "workspaces", workspace_id, "subjects"),
            Subject,
            cursor,
            limit,
        )

    async def list_schema_versions(
        self,
        workspace_id: str,
        tracker_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> CursorPage[SchemaVersion]:
        return await self._page(
            _path(
                "api",
                "workspaces",
                workspace_id,
                "trackers",
                tracker_id,
                "schema-versions",
            ),
            SchemaVersion,
            cursor,
            limit,
        )

    async def list_entries(
        self,
        workspace_id: str,
        *,
        filters: EntryFilters | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> CursorPage[Entry]:
        return await self._page(
            _path("api", "workspaces", workspace_id, "entries"),
            Entry,
            cursor,
            limit,
            filters,
        )

    async def iter_workspaces(self) -> AsyncIterator[Workspace]:
        async for item in self._iterate("/api/workspaces", Workspace):
            yield item

    async def iter_trackers(self, workspace_id: str) -> AsyncIterator[Tracker]:
        async for item in self._iterate(
            _path("api", "workspaces", workspace_id, "trackers"), Tracker
        ):
            yield item

    async def iter_subjects(self, workspace_id: str) -> AsyncIterator[Subject]:
        async for item in self._iterate(
            _path("api", "workspaces", workspace_id, "subjects"), Subject
        ):
            yield item

    async def iter_schema_versions(
        self,
        workspace_id: str,
        tracker_id: str,
    ) -> AsyncIterator[SchemaVersion]:
        async for item in self._iterate(
            _path(
                "api",
                "workspaces",
                workspace_id,
                "trackers",
                tracker_id,
                "schema-versions",
            ),
            SchemaVersion,
        ):
            yield item

    async def iter_entries(
        self,
        workspace_id: str,
        *,
        filters: EntryFilters | None = None,
    ) -> AsyncIterator[Entry]:
        async for item in self._iterate(
            _path("api", "workspaces", workspace_id, "entries"),
            Entry,
            filters,
        ):
            yield item

    async def create_entry(
        self,
        workspace_id: str,
        entry: EntryCreate,
        *,
        idempotency_key: str | None = None,
    ) -> Entry:
        """Submit once, preserving schema guards and the exact caller-authored JSON."""
        return decode(
            await self.request(
                "POST",
                _path("api", "workspaces", workspace_id, "entries"),
                body=entry,
                idempotency_key=idempotency_key,
            ),
            Entry,
        )

    async def _page[T](
        self,
        path: str,
        model: type[T],
        cursor: str | None,
        limit: int,
        filters: EntryFilters | None = None,
    ) -> CursorPage[T]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between one and one hundred")
        if cursor is not None and (not isinstance(cursor, str) or not 0 < len(cursor) <= 1024):
            raise ValueError("Invalid cursor")
        params: dict[str, Any] = dict(filters or {})
        dates = {"startDate", "endDateExclusive", "timeZone"}
        if dates.intersection(params) and not dates <= params.keys():
            raise ValueError("Calendar filtering requires both dates and timeZone")
        params.update(pagination="cursor", limit=limit)
        if cursor is not None:
            params["cursor"] = cursor
        return decode_page(await self.request("GET", path, params=params), model)

    async def _iterate[T](
        self,
        path: str,
        model: type[T],
        filters: EntryFilters | None = None,
    ) -> AsyncIterator[T]:
        # Snapshot before the first await: callers cannot change filters mid-traversal.
        snapshot = dict(filters) if filters else None
        cursor = None
        seen: set[str] = set()
        for _ in range(1000):
            page = await self._page(path, model, cursor, 100, snapshot)
            if page.next_cursor is not None and page.next_cursor in seen:
                raise InvalidResponseError(code="repeated_cursor")
            for item in page.items:
                yield item
            cursor = page.next_cursor
            if cursor is None:
                return
            seen.add(cursor)
        raise InvalidResponseError(code="pagination_limit")
