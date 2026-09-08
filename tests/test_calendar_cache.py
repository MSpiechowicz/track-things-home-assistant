"""Range cache expiry, invalidation, precise boundaries and atomic pagination."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from custom_components.track_things.api_errors import ServerError
from custom_components.track_things.calendar_query import CalendarQuery
from custom_components.track_things.coordinator import MetadataCoordinator

from .api_fixtures import ENTRY
from .test_metadata import metadata_api

START = datetime(2026, 9, 8, 10, tzinfo=UTC)
END = datetime(2026, 9, 8, 11, tzinfo=UTC)


async def query_fixture(hass, config_entry, entries=None):
    api = metadata_api()
    calls = []
    records = [deepcopy(ENTRY)] if entries is None else entries

    async def read(workspace, *, filters):
        calls.append((workspace, filters))
        for record in records:
            yield deepcopy(record)

    api.iter_entries = read
    coordinator = MetadataCoordinator(hass, config_entry, api)
    await coordinator.async_refresh()
    now = [0.0]
    query = CalendarQuery(coordinator, clock=lambda: now[0])
    return query, calls, now, coordinator


async def test_expiry_exactly_sixty_seconds_and_defensive_copies(hass, config_entry):
    query, calls, clock, coordinator = await query_fixture(hass, config_entry)
    events = await query.async_get_events(START, END, "Europe/Berlin")
    events[0].summary = "Caller mutation"
    clock[0] = 59.999
    assert (await query.async_get_events(START, END, "Europe/Berlin"))[
        0
    ].summary == "Anna · Headache"
    assert len(calls) == 1
    clock[0] = 60
    await query.async_get_events(START, END, "Europe/Berlin")
    assert len(calls) == 2
    query.invalidate()
    await query.async_get_events(START, END, "Europe/Berlin")
    assert len(calls) == 3
    await coordinator.async_shutdown()


async def test_exact_ranges_share_date_cache_and_zone_is_in_key(hass, config_entry):
    query, calls, _, coordinator = await query_fixture(hass, config_entry)
    assert len(await query.async_get_events(START, END, "Europe/Berlin")) == 1
    assert not await query.async_get_events(START.replace(minute=1), END, "Europe/Berlin")
    assert len(calls) == 1
    await query.async_get_events(START, END, "UTC")
    assert len(calls) == 2
    assert calls[0] == (
        "workspace-1",
        {"startDate": "2026-09-08", "endDateExclusive": "2026-09-09", "timeZone": "Europe/Berlin"},
    )
    await coordinator.async_shutdown()


async def test_midnight_duration_and_exclusive_end(hass, config_entry):
    records = [{**ENTRY, "occurredAt": "2026-09-07T21:59:30Z"}]
    query, calls, _, coordinator = await query_fixture(hass, config_entry, records)
    start = datetime(2026, 9, 7, 22, tzinfo=UTC)
    end = datetime(2026, 9, 8, 22, tzinfo=UTC)
    assert len(await query.async_get_events(start, end, "Europe/Berlin")) == 1
    assert calls[0][1]["startDate"] == "2026-09-07"
    assert calls[0][1]["endDateExclusive"] == "2026-09-09"
    assert not await query.async_get_events(start.replace(second=30), end, "Europe/Berlin")
    await coordinator.async_shutdown()


async def test_partial_failure_is_never_cached(hass, config_entry):
    query, _, _, coordinator = await query_fixture(hass, config_entry)

    async def fail(*args, **kwargs):
        yield ENTRY
        raise ServerError()

    coordinator.store.api.iter_entries = fail
    for _ in range(2):
        with pytest.raises(ServerError):
            await query.async_get_events(START, END, "UTC")
    assert not query._cache
    await coordinator.async_shutdown()


async def test_inflight_invalidation_retries_new_selection(hass, config_entry):
    query, _, _, coordinator = await query_fixture(hass, config_entry)
    config_entry.add_to_hass(hass)
    entered, release = asyncio.Event(), asyncio.Event()

    async def read(*args, **kwargs):
        entered.set()
        await release.wait()
        yield ENTRY

    coordinator.store.api.iter_entries = read
    task = asyncio.create_task(query.async_get_events(START, END, "UTC"))
    await entered.wait()
    hass.config_entries.async_update_entry(config_entry, options={"tracker_ids": []})
    query.invalidate()
    release.set()
    assert await task == []
    assert await query.async_get_events(START, END, "UTC") == []
    await coordinator.async_shutdown()


async def test_concurrent_reads_fetch_once_and_cache_is_bounded(hass, config_entry):
    query, calls, _, coordinator = await query_fixture(hass, config_entry)
    await asyncio.gather(*(query.async_get_events(START, END, "UTC") for _ in range(3)))
    assert len(calls) == 1
    from datetime import timedelta

    for day in range(40):
        await query.async_get_events(START + timedelta(days=day), END + timedelta(days=day), "UTC")
    assert len(query._cache) == 32
    await coordinator.async_shutdown()


async def test_invalid_empty_and_reversed_ranges_do_not_fetch(hass, config_entry):
    query, calls, _, coordinator = await query_fixture(hass, config_entry)
    with pytest.raises(ValueError, match="timezone"):
        await query.async_get_events(START.replace(tzinfo=None), END, "UTC")
    assert await query.async_get_events(END, START, "UTC") == []
    assert await query.async_get_events(START, START, "UTC") == []
    assert calls == []
    await coordinator.async_shutdown()


async def test_historical_schema_and_archived_metadata(hass, config_entry):
    from .api_fixtures import SCHEMA, SUBJECT, TRACKER

    records = [{**ENTRY, "trackerId": "old", "subjectId": "former", "schemaVersionId": "v0"}]
    query, _, _, coordinator = await query_fixture(hass, config_entry, records)
    coordinator.store.api.get_schema_version = AsyncMock(
        return_value={**SCHEMA, "id": "v0", "trackerId": "old"}
    )
    coordinator.store.api.get_tracker = AsyncMock(
        return_value={**TRACKER, "id": "old", "archivedAt": "past", "name": "Archived tracker"}
    )
    coordinator.store.api.get_subject = AsyncMock(
        return_value={**SUBJECT, "id": "former", "archivedAt": "past", "name": "Archived subject"}
    )
    event = (await query.async_get_events(START, END, "UTC"))[0]
    assert event.summary == "Archived subject · Archived tracker"
    assert "Severity: 6" in event.description
    coordinator.store.api.get_schema_version.assert_awaited_with("workspace-1", "old", "v0")
    await coordinator.async_shutdown()


async def test_missing_historical_schema_is_not_an_empty_calendar(hass, config_entry):
    from custom_components.track_things.api_errors import NotFoundError

    records = [{**ENTRY, "schemaVersionId": "deleted"}]
    query, _, _, coordinator = await query_fixture(hass, config_entry, records)
    coordinator.store.api.get_schema_version.side_effect = NotFoundError()
    with pytest.raises(NotFoundError):
        await query.async_get_events(START, END, "UTC")
    assert not query._cache
    await coordinator.async_shutdown()


async def test_wrong_workspace_entries_fail_before_metadata_lookup(hass, config_entry):
    from custom_components.track_things.api_errors import InvalidResponseError

    query, _, _, coordinator = await query_fixture(
        hass, config_entry, [{**ENTRY, "workspaceId": "other"}]
    )
    with pytest.raises(InvalidResponseError, match="calendar_workspace_mismatch"):
        await query.async_get_events(START, END, "UTC")
    assert not query._cache
    await coordinator.async_shutdown()
