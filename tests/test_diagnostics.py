"""Diagnostics deliberately omit arbitrary config, content, and runtime secrets."""

import json
from unittest.mock import AsyncMock, patch

import aiohttp
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.track_things.api_errors import ServerError
from custom_components.track_things.diagnostics import async_get_config_entry_diagnostics

from .api_fixtures import ENTRY
from .calendar_fixtures import setup_calendar
from .conversation_fixtures import say, setup_agent

HTTP_REQUEST = aiohttp.ClientSession._request


async def test_diagnostics_allowlist_omits_private_data(hass, hass_client, config_entry, auth_http):
    await setup_calendar(hass, config_entry, auth_http, [ENTRY])
    auth_http.respond({"items": [ENTRY], "nextCursor": None})  # Options invalidate the calendar.
    # Include future/unknown credential fields: a redaction denylist would miss these.
    hass.config_entries.async_update_entry(
        config_entry,
        data={**config_entry.data, "model_api_key": "private-model-key"},
        options={"future_option": {"prompt": "private-prompt", "tool": "private-tool"}},
    )
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data.coordinator
    coordinator.last_exception = ValueError("private-exception")
    calls = auth_http.request.call_count
    result = await async_get_config_entry_diagnostics(hass, config_entry)
    # Restore HTTP only for the local HA test server; backend setup is already complete.
    with patch.object(aiohttp.ClientSession, "_request", HTTP_REQUEST):
        assert await get_diagnostics_for_config_entry(hass, hass_client, config_entry) == result
    encoded = json.dumps(result)
    for secret in (
        "sentinel-access",
        "sentinel-refresh",
        "sentinel-note",
        "Anna",
        "Headache",
        "subject-1",
        "tracker-1",
        "workspace-1",
        "user-1",
        "backend.example.test",
        "private-model-key",
        "private-prompt",
        "private-tool",
        "private-exception",
    ):
        assert secret not in encoded
    assert result["runtime"]["counts"] == {
        "trackers": 1,
        "subjects": 1,
        "missing_schemas": 0,
        "calendar_trackers": 1,
        "voice_trackers": 1,
    }
    assert result["runtime"]["metadata_available"] is True
    assert result["runtime"]["reauth_required"] is False
    assert auth_http.request.call_count == calls


async def test_active_conversation_content_is_never_exported(hass, config_entry, auth_http):
    agent = await setup_agent(hass, config_entry, auth_http)
    await say(hass, agent, "log Headache")
    session = next(iter(agent._sessions.values()))
    session.last_speech = "private-transcript-sentinel"
    before = agent.drafts.view(session.draft_id)
    result = await async_get_config_entry_diagnostics(hass, config_entry)
    encoded = json.dumps(result)
    for secret in ("private-transcript-sentinel", session.draft_id, "Headache", "Anna", "Ben"):
        assert secret not in encoded
    assert agent.drafts.view(session.draft_id) == before


async def test_refresh_timestamp_survives_failure_then_advances(
    hass, config_entry, auth_http, freezer
):
    freezer.move_to("2026-09-08T10:00:00Z")
    await setup_calendar(hass, config_entry, auth_http)
    coordinator = config_entry.runtime_data.coordinator
    first = await async_get_config_entry_diagnostics(hass, config_entry)
    assert first["runtime"]["last_successful_metadata_refresh"] == "2026-09-08T10:00:00+00:00"
    freezer.move_to("2026-09-08T10:01:00Z")
    with patch.object(coordinator.store, "async_refresh", AsyncMock(side_effect=ServerError())):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    failed = await async_get_config_entry_diagnostics(hass, config_entry)
    assert failed["runtime"]["metadata_available"] is False
    assert (
        failed["runtime"]["last_successful_metadata_refresh"]
        == first["runtime"]["last_successful_metadata_refresh"]
    )
    auth_http.respond({"items": [], "nextCursor": None})
    with patch.object(coordinator.store, "async_refresh", AsyncMock(return_value=coordinator.data)):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    recovered = await async_get_config_entry_diagnostics(hass, config_entry)
    assert recovered["runtime"]["last_successful_metadata_refresh"] == "2026-09-08T10:01:00+00:00"
    assert recovered["runtime"]["metadata_available"] is True


async def test_not_loaded_and_unloaded_diagnostics_have_no_live_runtime(
    hass, config_entry, auth_http
):
    initial = await async_get_config_entry_diagnostics(hass, config_entry)
    assert initial["runtime"] is None
    await setup_calendar(hass, config_entry, auth_http)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    result = await async_get_config_entry_diagnostics(hass, config_entry)
    assert result["runtime"] is None
    assert result["configuration"]["state"] == "not_loaded"
