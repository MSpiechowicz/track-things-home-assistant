"""Real Home Assistant calendar platform state, services, options, and lifecycle."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.track_things.api_errors import ServerError

from .api_fixtures import ENTRY
from .calendar_fixtures import calendar_setup_responses, setup_calendar

pytestmark = pytest.mark.usefixtures("freezer")
START = datetime(2026, 9, 8, tzinfo=UTC)
END = datetime(2026, 9, 9, tzinfo=UTC)


async def test_calendar_service_pages_sorting_ranges_and_read_only(
    hass, config_entry, auth_http, freezer
):
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-09-08T09:00:00Z")
    entity = await setup_calendar(hass, config_entry, auth_http)
    auth_http.respond(
        {
            "items": [
                {**ENTRY, "id": "later", "occurredAt": "2026-09-08T15:00:00Z"},
                {**ENTRY, "id": "excluded", "occurredAt": "2026-09-09T00:00:00Z"},
            ],
            "nextCursor": "page-2",
        }
    )
    auth_http.respond(
        {
            "items": [
                {**ENTRY, "id": "earlier"},
                {
                    **ENTRY,
                    "id": "period",
                    "periodStart": "2026-09-07T00:00:00Z",
                    "periodEnd": "2026-09-09T00:00:00Z",
                },
            ],
            "nextCursor": None,
        }
    )
    result = await hass.services.async_call(
        "calendar",
        "get_events",
        {"entity_id": entity.entity_id, "start_date_time": START, "end_date_time": END},
        blocking=True,
        return_response=True,
    )
    events = result[entity.entity_id]["events"]
    assert [e["summary"] for e in events] == ["Anna · Headache"] * 3
    assert events[0]["start"] == "2026-09-07"
    assert events[0]["end"] == "2026-09-10"
    calls = auth_http.request.call_args_list[-2:]
    assert calls[0].kwargs["params"] == {
        "startDate": "2026-09-07",
        "endDateExclusive": "2026-09-09",
        "timeZone": "UTC",
        "pagination": "cursor",
        "limit": 100,
    }
    assert calls[1].kwargs["params"]["cursor"] == "page-2"
    assert entity.supported_features == 0
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "calendar",
            "create_event",
            {
                "entity_id": entity.entity_id,
                "summary": "Cannot create",
                "start_date": "2026-09-08",
                "end_date": "2026-09-09",
            },
            blocking=True,
        )
    assert all(call.args[0] == "GET" for call in auth_http.request.call_args_list)


async def test_current_next_state_transitions_without_property_io(
    hass, config_entry, auth_http, freezer
):
    freezer.move_to("2026-09-08T10:00:30Z")
    records = [
        {**ENTRY, "id": "future", "occurredAt": "2028-01-01T00:00:00Z"},
        ENTRY,
        {**ENTRY, "id": "past", "occurredAt": "2026-09-08T09:00:00Z"},
    ]
    entity = await setup_calendar(hass, config_entry, auth_http, records)
    assert entity.event.uid == "entry-1"
    assert hass.states.get(entity.entity_id).state == STATE_ON
    calls = auth_http.request.call_count
    freezer.move_to("2026-09-08T10:01:00Z")
    assert entity.event.uid == "future"
    entity.async_write_ha_state()
    assert hass.states.get(entity.entity_id).state == STATE_OFF
    assert auth_http.request.call_count == calls


async def test_local_all_day_state_and_dst_order(hass, config_entry, auth_http, freezer):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-10-25T00:45:00Z")
    records = [
        {**ENTRY, "id": "second-fold", "occurredAt": "2026-10-25T01:30:00Z"},
        {**ENTRY, "id": "first-fold", "occurredAt": "2026-10-25T00:30:00Z"},
        {**ENTRY, "id": "all-day", "periodStart": "2026-10-25T00:00:00Z", "periodEnd": None},
    ]
    entity = await setup_calendar(hass, config_entry, auth_http, records)
    assert entity.event.uid == "all-day"
    assert entity.event.start == date(2026, 10, 25)
    assert hass.states.get(entity.entity_id).state == STATE_ON
    auth_http.respond({"items": records, "nextCursor": None})
    events = await entity.async_get_events(
        hass, datetime(2026, 10, 25, 0, 40, tzinfo=UTC), datetime(2026, 10, 25, 2, tzinfo=UTC)
    )
    assert [e.uid for e in events] == ["all-day", "second-fold"]


async def test_backend_failure_is_unavailable_and_recovers(hass, config_entry, auth_http, freezer):
    freezer.move_to("2026-09-08T10:00:30Z")
    entity = await setup_calendar(hass, config_entry, auth_http, [ENTRY])
    with patch.object(entity._query, "_async_read", AsyncMock(side_effect=ServerError())):
        with pytest.raises(HomeAssistantError, match="temporarily unavailable"):
            await entity.async_get_events(hass, START, END)
    assert hass.states.get(entity.entity_id).state == STATE_UNAVAILABLE
    auth_http.respond({"items": [], "nextCursor": None})
    await entity.async_update()
    entity.async_write_ha_state()
    assert entity.event is None
    assert hass.states.get(entity.entity_id).state == STATE_OFF


async def test_metadata_failure_disables_calendar(hass, config_entry, auth_http, freezer):
    freezer.move_to("2026-09-08T10:00:30Z")
    entity = await setup_calendar(hass, config_entry, auth_http, [ENTRY])
    coordinator = config_entry.runtime_data.coordinator
    with patch.object(coordinator.store, "async_refresh", AsyncMock(side_effect=ServerError())):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get(entity.entity_id).state == STATE_UNAVAILABLE
    with pytest.raises(HomeAssistantError):
        await entity.async_get_events(hass, START, END)


async def test_selection_invalidates_cache_updates_state_and_stable_entity(
    hass, config_entry, auth_http, freezer
):
    freezer.move_to("2026-09-08T10:00:30Z")
    entity = await setup_calendar(hass, config_entry, auth_http, [ENTRY])
    registry = er.async_get(hass)
    registration = registry.async_get(entity.entity_id)
    calls = auth_http.request.call_count
    hass.config_entries.async_update_entry(config_entry, options={"tracker_ids": []})
    await hass.async_block_till_done()
    assert entity.event is None
    assert hass.states.get(entity.entity_id).state == STATE_OFF
    assert auth_http.request.call_count == calls
    auth_http.respond(
        {"items": [ENTRY, {**ENTRY, "id": "hidden", "trackerId": "another"}], "nextCursor": None}
    )
    hass.config_entries.async_update_entry(config_entry, options={"tracker_ids": ["tracker-1"]})
    await hass.async_block_till_done()
    assert entity.event.uid == "entry-1"
    assert len(entity._events) == 1
    calendar_setup_responses(auth_http, [ENTRY])
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(entity.entity_id).unique_id == registration.unique_id
    assert len(hass.states.async_entity_ids("calendar")) == 1
    coordinator = config_entry.runtime_data.coordinator
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert hass.states.get(entity.entity_id).state == STATE_UNAVAILABLE
    assert not list(coordinator.async_contexts())


async def test_polling_refreshes_state_and_unload_stops_requests(
    hass, config_entry, auth_http, freezer
):
    freezer.move_to("2026-09-08T10:00:30Z")
    entity = await setup_calendar(hass, config_entry, auth_http)
    auth_http.respond({"items": [ENTRY], "nextCursor": None})
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert entity._events[0].uid == "entry-1"
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    calls = auth_http.request.call_count
    freezer.tick(timedelta(minutes=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert auth_http.request.call_count == calls


async def test_initial_read_failure_keeps_unavailable_entity(hass, config_entry, auth_http):
    from custom_components.track_things.calendar_query import CalendarQuery

    with patch.object(CalendarQuery, "_async_read", AsyncMock(side_effect=ServerError())):
        entity = await setup_calendar(hass, config_entry, auth_http)
    assert entity.event is None
    assert hass.states.get(entity.entity_id).state == STATE_UNAVAILABLE
    # The initial page remains queued because the read was failed before HTTP.
    await entity.async_update()
    entity.async_write_ha_state()
    assert hass.states.get(entity.entity_id).state == STATE_OFF
