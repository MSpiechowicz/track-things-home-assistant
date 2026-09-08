"""Date-filtered, paginated calendar reads with a bounded in-memory range cache."""

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, time, timedelta
from time import monotonic
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from homeassistant.components.calendar import CalendarEvent

from .api_errors import InvalidResponseError
from .api_models import Entry
from .calendar_mapping import calendar_event_overlaps, entry_to_calendar_event
from .coordinator import CONF_TRACKER_IDS

if TYPE_CHECKING:
    from .coordinator import MetadataCoordinator

CACHE_SECONDS = 60
MAX_CACHED_RANGES = 32


class CalendarQuery:
    """Cache complete reads only; never publish partial pages or failed lookups."""

    def __init__(
        self, coordinator: MetadataCoordinator, *, clock: Callable[[], float] | None = None
    ) -> None:
        self.coordinator = coordinator
        self._clock = clock or (lambda: monotonic())
        self._generation = 0
        self._cache: OrderedDict[tuple, tuple[float, list[tuple[Entry, CalendarEvent]]]] = (
            OrderedDict()
        )
        self._lock = asyncio.Lock()

    def invalidate(self) -> None:
        """Discard ranges after metadata/options changes, explicit refresh, or writes."""
        self._generation += 1
        self._cache.clear()

    async def async_get_events(
        self, start: datetime, end: datetime, time_zone: str
    ) -> list[CalendarEvent]:
        return [event for _, event in await self.async_get_records(start, end, time_zone)]

    async def async_get_records(
        self, start: datetime, end: datetime, time_zone: str
    ) -> list[tuple[Entry, CalendarEvent]]:
        """Return complete entries and their display events from the shared range cache."""
        if start.utcoffset() is None or end.utcoffset() is None:
            raise ValueError("Calendar query timestamps must include a timezone")
        start, end = start.astimezone(UTC), end.astimezone(UTC)
        if end <= start:
            return []
        zone = ZoneInfo(time_zone)
        # A timestamp has a one-minute display duration and may start just before
        # local midnight. Include that preceding date, then filter exact instants.
        first = (start - timedelta(minutes=1)).astimezone(zone).date()
        local_end = end.astimezone(zone)
        last = local_end.date()
        if local_end.timetz().replace(tzinfo=None) != time.min:
            last += timedelta(days=1)
        async with self._lock:
            while True:
                generation = self._generation
                selected = self.coordinator.entry.options.get(CONF_TRACKER_IDS)
                selection = None if selected is None else tuple(sorted(selected))
                key = (first, last, time_zone, selection)
                cached = self._cache.get(key)
                if cached and self._clock() - cached[0] < CACHE_SECONDS:
                    self._cache.move_to_end(key)
                    events = cached[1]
                    break
                events = await self._async_read(
                    first.isoformat(), last.isoformat(), time_zone, selection
                )
                # An options/metadata refresh can arrive while HTTP is in flight.
                # Retry against its snapshot rather than re-inserting stale data.
                if generation != self._generation:
                    continue
                self._cache[key] = (self._clock(), events)
                self._cache.move_to_end(key)
                while len(self._cache) > MAX_CACHED_RANGES:
                    self._cache.popitem(last=False)
                break
        return deepcopy(
            [
                (entry, event)
                for entry, event in events
                if calendar_event_overlaps(event, start, end, time_zone=zone)
            ]
        )

    async def _async_read(
        self, first: str, last: str, time_zone: str, selection: tuple[str, ...] | None
    ) -> list[tuple[Entry, CalendarEvent]]:
        if selection == ():
            return []
        store = self.coordinator.store
        filters = {"startDate": first, "endDateExclusive": last, "timeZone": time_zone}
        events = []
        seen = set()
        async for entry in store.api.iter_entries(store.workspace_id, filters=filters):
            if entry["workspaceId"] != store.workspace_id:
                raise InvalidResponseError(code="calendar_workspace_mismatch")
            if selection is not None and entry["trackerId"] not in selection:
                continue
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            events.append(
                (
                    entry,
                    entry_to_calendar_event(
                        entry,
                        await store.async_schema(entry["trackerId"], entry["schemaVersionId"]),
                        tracker=await store.async_tracker(entry["trackerId"]),
                        subject=await store.async_subject(entry["subjectId"]),
                    ),
                )
            )
        events.sort(
            key=lambda event: (
                event[1].start_datetime_local.astimezone(UTC),
                event[1].end_datetime_local.astimezone(UTC),
                event[1].uid or "",
            )
        )
        return events
