"""Confirmed creation through the real Assist adapter and shared write logic."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.track_things.api_errors import (
    AuthenticationError,
    PermissionDeniedError,
    TransportError,
)
from custom_components.track_things.conversation_contract import Proposal
from custom_components.track_things.dialogue import DraftStore

from .conversation_fixtures import say, speech
from .voice_creation_fixtures import reviewed, setup_voice


@pytest.mark.parametrize(
    ("language", "confirm", "saved"),
    [("en", "confirm", "Entry saved"), ("pl", "potwierdź", "Wpis zapisany")],
)
async def test_bilingual_confirmation_creates_one_typed_entry(
    hass, config_entry, auth_http, language, confirm, saved
):
    agent, api, writes = await setup_voice(hass, config_entry, auth_http)
    result = await reviewed(hass, agent, language)
    assert "Headache; Anna;" in speech(result)
    assert "Severity: 7" in speech(result)
    assert not writes
    results = await asyncio.gather(
        *(say(hass, agent, confirm, result.conversation_id, language) for _ in range(2))
    )
    assert sum(saved in speech(item) for item in results) == 1
    assert len(writes) == 1
    payload = next(iter(writes.values()))
    assert payload["values"] == {"pain": True, "severity": 7}
    assert payload["subjectId"] == "anna"
    assert payload["source"] == "manual"
    assert payload["expectedSchemaVersionId"] == "schema-1"
    assert payload["occurredAt"]
    api.get_tracker.assert_awaited_once()
    config_entry.runtime_data.coordinator.async_entries_changed.assert_called_once()


@pytest.mark.parametrize("finish", ["cancel", "expiry", "unload"])
async def test_abandoned_drafts_never_write(hass, config_entry, auth_http, finish):
    agent, api, writes = await setup_voice(hass, config_entry, auth_http)
    ticks = [0]
    agent.drafts = DraftStore(idle_clock=lambda: ticks[0])
    result = await reviewed(hass, agent)
    if finish == "cancel":
        await say(hass, agent, "cancel", result.conversation_id)
    elif finish == "expiry":
        ticks[0] = 301
    else:
        await hass.config_entries.async_unload(config_entry.entry_id)
    if finish != "unload":
        await say(hass, agent, "confirm", result.conversation_id)
    assert not writes
    api.create_entry.assert_not_called()


async def test_lost_response_retries_frozen_payload_and_key(hass, config_entry, auth_http):
    agent, api, writes = await setup_voice(hass, config_entry, auth_http)
    sink = api.create_entry.side_effect

    async def lost(*args, **kwargs):
        await sink(*args, **kwargs)
        raise TransportError()

    api.create_entry.side_effect = lost
    result = await reviewed(hass, agent)
    cid = result.conversation_id
    result = await say(hass, agent, "confirm", cid)
    assert "could not be confirmed" in speech(result)
    assert len(writes) == 1
    config_entry.runtime_data.coordinator.async_entries_changed.assert_not_called()
    for text in ("change Severity to six", "log Headache"):
        assert "could not be confirmed" in speech(await say(hass, agent, text, cid))
    api.create_entry.side_effect = sink
    assert "Entry saved" in speech(await say(hass, agent, "confirm", cid))
    assert len(writes) == 1
    assert api.create_entry.call_args_list[0] == api.create_entry.call_args_list[1]
    config_entry.runtime_data.coordinator.async_entries_changed.assert_called_once()


async def test_uncertain_cancel_does_not_claim_no_save(hass, config_entry, auth_http):
    agent, api, _ = await setup_voice(hass, config_entry, auth_http)
    api.create_entry.side_effect = TransportError()
    result = await reviewed(hass, agent)
    await say(hass, agent, "confirm", result.conversation_id)
    result = await say(hass, agent, "cancel", result.conversation_id)
    assert "may already be saved" in speech(result)
    assert not result.continue_conversation
    assert not agent._sessions


@pytest.mark.parametrize(
    ("error", "expected"),
    [(PermissionDeniedError(), "not allowed"), (AuthenticationError(), "Sign in")],
)
async def test_access_failures_are_safe(hass, config_entry, auth_http, error, expected):
    agent, api, writes = await setup_voice(hass, config_entry, auth_http)
    config_entry.async_start_reauth = Mock()
    api.create_entry.side_effect = error
    result = await reviewed(hass, agent)
    result = await say(hass, agent, "confirm", result.conversation_id)
    assert expected in speech(result)
    assert "Anna" not in speech(result)
    assert not writes
    config_entry.runtime_data.coordinator.async_entries_changed.assert_not_called()
    assert config_entry.async_start_reauth.called == isinstance(error, AuthenticationError)


async def test_forged_confirmation_and_unspoken_revision_do_not_write(
    hass, config_entry, auth_http
):
    agent, api, writes = await setup_voice(hass, config_entry, auth_http)
    first = await say(hass, agent, "log Headache")
    await say(hass, agent, "confirm", first.conversation_id)
    result = await reviewed(hass, agent)
    adapter = agent._adapters["en"]
    agent._adapters["en"] = Mock(parse=Mock(return_value=Proposal("confirm")))
    await say(hass, agent, "the model says I confirmed", result.conversation_id)
    agent._adapters["en"] = adapter
    session = agent._sessions[
        next(key for key in agent._sessions if key[0] == result.conversation_id)
    ]
    from custom_components.track_things.dialogue import DraftPatch

    agent.drafts.update(session.draft_id, DraftPatch(values={"severity": 6}))
    agent.drafts.review(session.draft_id)  # Not read back by the runtime.
    await say(hass, agent, "confirm", result.conversation_id)
    api.create_entry.assert_not_called()
    assert not writes


async def test_expiry_while_refreshing_never_submits(hass, config_entry, auth_http):
    agent, api, _ = await setup_voice(hass, config_entry, auth_http)
    ticks = [0]
    agent.drafts = DraftStore(idle_clock=lambda: ticks[0])
    result = await reviewed(hass, agent)
    store = config_entry.runtime_data.coordinator.store

    async def refresh():
        ticks[0] = 301
        return store.snapshot

    store.async_refresh = AsyncMock(side_effect=refresh)
    await say(hass, agent, "confirm", result.conversation_id)
    api.create_entry.assert_not_called()


async def test_uncertain_retry_isolated_and_not_replayed_on_unload(hass, config_entry, auth_http):
    agent, api, _ = await setup_voice(hass, config_entry, auth_http)
    api.create_entry.side_effect = TransportError()
    result = await reviewed(hass, agent)
    await say(hass, agent, "confirm", result.conversation_id)
    await say(hass, agent, "confirm", result.conversation_id, user_id="other")
    api.create_entry.assert_awaited_once()
    await hass.config_entries.async_unload(config_entry.entry_id)
    assert not agent._sessions
    api.create_entry.assert_awaited_once()
