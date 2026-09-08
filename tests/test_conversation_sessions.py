"""Isolation, expiry, unload/restart, and serialized callback handoff."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.track_things.dialogue import DraftStore

from .auth_fixtures import ENTRY_DATA, setup_responses
from .conversation_fixtures import say, setup_agent, speech


@pytest.mark.parametrize(
    "identity",
    [{"user_id": "other"}, {"device_id": "other"}, {"satellite_id": "other"}, {"user_id": None}],
)
async def test_same_conversation_id_cannot_cross_identity(hass, config_entry, auth_http, identity):
    agent = await setup_agent(hass, config_entry, auth_http)
    first = await say(hass, agent, "log Headache")
    cid = first.conversation_id
    result = await say(hass, agent, "Anna", cid, **identity)
    assert "Say log" in speech(result)
    assert "Pain" not in speech(result)
    result = await say(hass, agent, "Anna", cid)
    assert "Pain" in speech(result)


async def test_conversations_languages_and_entries_are_isolated(hass, config_entry, auth_http):
    agent = await setup_agent(hass, config_entry, auth_http)
    one = await say(hass, agent, "log Headache")
    two = await say(hass, agent, "log Headache")
    assert one.conversation_id != two.conversation_id
    await say(hass, agent, "Anna", one.conversation_id)
    await say(hass, agent, "Ben", two.conversation_id)
    await say(hass, agent, "no", one.conversation_id)
    assert "Pain" in speech(await say(hass, agent, "repeat", two.conversation_id))
    result = await say(hass, agent, "powtórz", one.conversation_id, "pl")
    assert "Powiedz zapisz" in speech(result)
    other = MockConfigEntry(domain="track_things", title="Other", data=ENTRY_DATA)
    other_agent = await setup_agent(hass, other, auth_http)
    result = await say(hass, other_agent, "repeat", one.conversation_id)
    assert "Say log" in speech(result)


async def test_expiry_cancellation_and_unload_clear_drafts(hass, config_entry, auth_http):
    agent = await setup_agent(hass, config_entry, auth_http)
    ticks = [0.0]
    agent.drafts = DraftStore(idle_clock=lambda: ticks[0])
    first = await say(hass, agent, "log Headache")
    ticks[0] = 301
    agent._expire()
    assert not agent._sessions
    result = await say(hass, agent, "Anna", first.conversation_id)
    assert not result.continue_conversation
    first = await say(hass, agent, "log Headache")
    result = await say(hass, agent, "cancel", first.conversation_id)
    assert not result.continue_conversation
    assert not agent._sessions
    first = await say(hass, agent, "log Headache")
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert not agent._sessions
    assert agent.drafts.expire() == ()
    setup_responses(auth_http)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    from homeassistant.components.conversation import async_get_agent

    replacement = async_get_agent(hass, agent.entity_id)
    assert replacement is not agent
    result = await say(hass, replacement, "confirm", first.conversation_id)
    assert not result.continue_conversation
    assert "Say log" in speech(result)


async def test_backend_failure_and_recovery(hass, config_entry, auth_http):
    agent = await setup_agent(hass, config_entry, auth_http)
    first = await say(hass, agent, "log Headache")
    config_entry.runtime_data.coordinator.last_update_success = False
    result = await say(hass, agent, "Anna", first.conversation_id)
    assert "unavailable" in speech(result)
    assert not result.continue_conversation
    config_entry.runtime_data.coordinator.last_update_success = True
    result = await say(hass, agent, "Anna", first.conversation_id)
    assert "Pain" in speech(result)


async def test_concurrent_confirmation_hands_off_once(hass, config_entry, auth_http):
    agent = await setup_agent(hass, config_entry, auth_http, subjects=("anna",))
    callback = agent.confirmed_draft_callback = AsyncMock(return_value="handoff complete")
    first = await say(hass, agent, "log Headache")
    cid = first.conversation_id
    await say(hass, agent, "no", cid)
    await say(hass, agent, "/skip", cid)
    results = await asyncio.gather(
        say(hass, agent, "confirm", cid), say(hass, agent, "confirm", cid)
    )
    callback.assert_awaited_once()
    assert sum(speech(result) == "handoff complete" for result in results) == 1
    assert not agent._sessions


async def test_detached_draft_view_cannot_change_validated_answers(hass, config_entry, auth_http):
    agent = await setup_agent(hass, config_entry, auth_http, subjects=("anna",))
    first = await say(hass, agent, "log Headache")
    await say(hass, agent, "no", first.conversation_id)
    session = next(iter(agent._sessions.values()))
    view = agent.drafts.view(session.draft_id)
    view.values["pain"] = True
    view.metadata.trackers.clear()
    result = await say(hass, agent, "/skip", first.conversation_id)
    assert "Pain: no" in speech(result)
