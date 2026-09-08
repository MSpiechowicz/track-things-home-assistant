"""Response actions through the real HA service registry with synthetic HTTP."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.track_things.api_errors import NotFoundError, ServerError

from .api_fixtures import ENTRY, SUBJECT, TRACKER
from .calendar_fixtures import setup_calendar

pytestmark = pytest.mark.usefixtures("freezer")


async def daily(hass, entry, **data):
    return await hass.services.async_call(
        "track_things",
        "get_daily_calendar",
        {"config_entry_id": entry.entry_id, **data},
        blocking=True,
        return_response=True,
    )


async def test_full_entries_local_today_filters_language_and_shared_cache(
    hass, config_entry, auth_http, freezer
):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-09-07T22:30:00Z")
    entity = await setup_calendar(hass, config_entry, auth_http)
    record = {**ENTRY, "values": {"severity": 6}, "note": "Synthetic note", "tagIds": ["tag-1"]}
    auth_http.respond({"items": [record, {**record, "id": "second"}], "nextCursor": None})
    result = await daily(hass, config_entry, trackerId=TRACKER["id"], subjectId=SUBJECT["id"])
    assert result["date"] == "2026-09-08"
    assert result["time_zone"] == "Europe/Berlin"
    assert result["total"] == 2
    assert result["entries"] == [record, {**record, "id": "second"}]
    assert result["summary"] == "2026-09-08: 2 entries. Anna · Headache Anna · Headache"
    calls = auth_http.request.call_count
    result["entries"][0]["values"]["severity"] = 999
    polish = await daily(hass, config_entry, date="2026-09-08", language="pl")
    assert polish["summary"].startswith("2026-09-08: 2 wpisy.")
    assert polish["entries"][0]["values"]["severity"] == 6
    from datetime import datetime
    from zoneinfo import ZoneInfo

    await entity.async_get_events(
        hass,
        datetime(2026, 9, 8, tzinfo=ZoneInfo("Europe/Berlin")),
        datetime(2026, 9, 9, tzinfo=ZoneInfo("Europe/Berlin")),
    )
    assert auth_http.request.call_count == calls


async def test_empty_filtered_day_and_explicit_date(hass, config_entry, auth_http):
    await setup_calendar(hass, config_entry, auth_http)
    store = config_entry.runtime_data.coordinator.store
    store._subjects["other"] = {**SUBJECT, "id": "other", "archivedAt": "2026-01-01T00:00:00Z"}
    auth_http.respond({"items": [ENTRY], "nextCursor": None})
    result = await daily(hass, config_entry, date="2026-09-08", subjectId="other", language="pl")
    assert result["entries"] == []
    assert result["total"] == 0
    assert result["summary"] == "2026-09-08: 0 wpisów."
    auth_http.respond({"items": [], "nextCursor": None})
    assert (await daily(hass, config_entry, date="2026-09-09"))[
        "summary"
    ] == "2026-09-09: 0 entries."


@pytest.mark.parametrize(
    "field,method,resource",
    [
        ("trackerId", "async_tracker", TRACKER),
        ("subjectId", "async_subject", SUBJECT),
    ],
)
@pytest.mark.parametrize("foreign", [False, True])
async def test_unknown_and_foreign_resources(
    hass, config_entry, auth_http, field, method, resource, foreign
):
    await setup_calendar(hass, config_entry, auth_http)
    mock = (
        AsyncMock(return_value={**resource, "workspaceId": "foreign"})
        if foreign
        else AsyncMock(side_effect=NotFoundError())
    )
    with patch.object(config_entry.runtime_data.coordinator.store, method, mock):
        with pytest.raises(ServiceValidationError):
            await daily(hass, config_entry, **{field: resource["id"]})


async def test_target_validation_and_unloaded_instance(hass, config_entry, auth_http):
    await setup_calendar(hass, config_entry, auth_http)
    for entry in [MockConfigEntry(domain="track_things"), MockConfigEntry(domain="other")]:
        entry.add_to_hass(hass)
        with pytest.raises(ServiceValidationError):
            await daily(hass, entry)
    unknown = MockConfigEntry(domain="track_things")
    with pytest.raises(ServiceValidationError):
        await daily(hass, unknown)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    with pytest.raises(ServiceValidationError, match="not loaded"):
        await daily(hass, config_entry)


async def test_two_instances_use_only_target_workspace(hass, config_entry, auth_http):
    await setup_calendar(hass, config_entry, auth_http)
    second = MockConfigEntry(domain="track_things", data=dict(config_entry.data))
    await setup_calendar(hass, second, auth_http)
    with patch.object(
        config_entry.runtime_data.calendar, "async_get_records", AsyncMock(return_value=[])
    ) as first_read:
        with patch.object(
            second.runtime_data.calendar, "async_get_records", AsyncMock(return_value=[])
        ) as second_read:
            await daily(hass, second)
            first_read.assert_not_awaited()
            second_read.assert_awaited_once()


async def test_errors_are_explicit_and_inputs_validated(hass, config_entry, auth_http):
    import voluptuous as vol

    await setup_calendar(hass, config_entry, auth_http)
    for data in [{"language": "de"}, {"date": "nonsense"}, {"unexpected": True}]:
        with pytest.raises(vol.Invalid):
            await daily(hass, config_entry, **data)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            "track_things", "get_daily_calendar", {}, blocking=True, return_response=True
        )
    with patch.object(
        config_entry.runtime_data.calendar, "_async_read", AsyncMock(side_effect=ServerError())
    ):
        with pytest.raises(HomeAssistantError, match="temporarily unavailable"):
            await daily(hass, config_entry)
    config_entry.runtime_data.coordinator.last_update_success = False
    with pytest.raises(HomeAssistantError, match="metadata is unavailable"):
        await daily(hass, config_entry)


async def test_unselected_tracker_is_rejected(hass, config_entry, auth_http):
    await setup_calendar(hass, config_entry, auth_http)
    hass.config_entries.async_update_entry(config_entry, options={"tracker_ids": []})
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError, match="not selected"):
        await daily(hass, config_entry, trackerId=TRACKER["id"])


async def test_pagination_filters_and_dst_day(hass, config_entry, auth_http):
    await hass.config.async_set_time_zone("Europe/Berlin")
    await setup_calendar(hass, config_entry, auth_http)
    store = config_entry.runtime_data.coordinator.store
    store._subjects["other"] = {**SUBJECT, "id": "other"}
    first = {**ENTRY, "occurredAt": "2026-10-25T00:30:00Z"}
    second = {**ENTRY, "id": "second-fold", "occurredAt": "2026-10-25T01:30:00Z"}
    outside = {**ENTRY, "id": "outside", "occurredAt": "2026-10-25T23:00:00Z"}
    other = {**first, "id": "other-subject", "subjectId": "other"}
    auth_http.respond({"items": [first, other], "nextCursor": "page2"})
    auth_http.respond({"items": [second, outside, first], "nextCursor": None})
    result = await daily(hass, config_entry, date="2026-10-25", subjectId=SUBJECT["id"])
    assert result["total"] == 2
    assert result["entries"] == [first, second]
    assert auth_http.request.call_args.kwargs["params"]["cursor"] == "page2"
    assert auth_http.request.call_args.kwargs["params"]["endDateExclusive"] == "2026-10-26"


async def test_action_descriptions_load(hass, config_entry, auth_http):
    from homeassistant.helpers.service import async_get_all_descriptions

    await setup_calendar(hass, config_entry, auth_http)
    descriptions = (await async_get_all_descriptions(hass))["track_things"]
    assert descriptions["get_daily_calendar"]["fields"]["config_entry_id"]["required"]
    assert descriptions["refresh"]["fields"]["config_entry_id"]["required"]
