"""Cross-platform outage, revoked session, reauthentication, and restart replay."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components import conversation
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.track_things.api_errors import ServerError
from custom_components.track_things.diagnostics import async_get_config_entry_diagnostics

from .api_fixtures import SESSION
from .auth_fixtures import LOGIN, login_responses, setup_responses
from .conversation_fixtures import say, setup_agent, speech
from .voice_creation_fixtures import reviewed, setup_voice


async def test_backend_recovery_restores_calendar_and_conversation(hass, config_entry, auth_http):
    agent = await setup_agent(hass, config_entry, auth_http)
    coordinator = config_entry.runtime_data.coordinator
    first = await say(hass, agent, "log Headache")
    calendar_id = hass.states.async_entity_ids("calendar")[0]
    with patch.object(coordinator.store, "async_refresh", AsyncMock(side_effect=ServerError())):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get(calendar_id).state == STATE_UNAVAILABLE
    assert "unavailable" in speech(await say(hass, agent, "Anna", first.conversation_id))
    auth_http.respond({"items": [], "nextCursor": None})
    with patch.object(
        coordinator.store, "async_refresh", AsyncMock(return_value=coordinator.store.snapshot)
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get(calendar_id).state != STATE_UNAVAILABLE
    assert "Pain" in speech(await say(hass, agent, "Anna", first.conversation_id))
    assert all(call.args[0] == "GET" for call in auth_http.request.call_args_list)


@pytest.mark.parametrize("revocation", ["refresh", "workspace"])
async def test_revocation_reauth_and_reload_do_not_replay_draft(
    hass, config_entry, auth_http, revocation
):
    agent = await setup_agent(hass, config_entry, auth_http)
    first = await say(hass, agent, "log Headache")
    previous = config_entry.runtime_data
    if revocation == "refresh":
        # Reject the access token, then its refresh token at the real HTTP boundary.
        auth_http.respond(status=401)
        auth_http.respond(status=401)
    else:
        auth_http.respond(status=403)
    await previous.coordinator.async_refresh()
    await hass.async_block_till_done()
    result = await async_get_config_entry_diagnostics(hass, config_entry)
    assert result["runtime"]["reauth_required"] is True
    assert hass.states.get(hass.states.async_entity_ids("calendar")[0]).state == STATE_UNAVAILABLE
    assert "unavailable" in speech(await say(hass, agent, "Anna", first.conversation_id))
    flows = hass.config_entries.flow.async_progress()
    flow = next(item for item in flows if item["context"].get("source") == "reauth")
    rotated = {
        **SESSION,
        "access_token": "replacement-access",
        "refresh_token": "replacement-refresh",
    }
    login_responses(auth_http, credentials=rotated)
    setup_responses(auth_http)
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"identifier": LOGIN["identifier"], "password": LOGIN["password"]}
    )
    await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    replacement = conversation.async_get_agent(hass, agent.entity_id)
    assert replacement is not agent
    assert not agent._sessions
    assert "Say log" in speech(await say(hass, replacement, "confirm", first.conversation_id))
    with pytest.raises(RuntimeError, match="unloaded"):
        await previous.api.get_user()
    assert not list(previous.coordinator.async_contexts())
    assert not any(
        "/entries" in str(call.args[1]) and call.args[0] == "POST"
        for call in auth_http.request.call_args_list
    )
    recovered = await async_get_config_entry_diagnostics(hass, config_entry)
    assert recovered["runtime"]["metadata_available"] is True
    assert recovered["runtime"]["reauth_required"] is False


async def test_unload_pending_write_clears_tasks_and_restart_never_retries(
    hass, config_entry, auth_http
):
    agent, api, writes = await setup_voice(hass, config_entry, auth_http)
    result = await reviewed(hass, agent)
    api.create_entry.side_effect = ServerError()
    await say(hass, agent, "confirm", result.conversation_id)
    assert next(iter(agent._sessions.values())).pending is not None
    old = config_entry.runtime_data
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert not agent._sessions
    assert not agent.calendar.sessions
    assert not old.calendar._cache
    assert not list(old.coordinator.async_contexts())
    calls = auth_http.request.call_count
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=10))
    await hass.async_block_till_done()
    assert auth_http.request.call_count == calls
    setup_responses(auth_http)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    replacement = conversation.async_get_agent(hass, agent.entity_id)
    assert "Say log" in speech(await say(hass, replacement, "confirm", result.conversation_id))
    api.create_entry.assert_awaited_once()
    assert not writes
    assert all(call.args[0] == "GET" for call in auth_http.request.call_args_list)
