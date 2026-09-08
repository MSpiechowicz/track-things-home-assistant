"""Production voice writer with synthetic API resources and an idempotent sink."""

from copy import deepcopy
from unittest.mock import AsyncMock, Mock

from .conversation_fixtures import say, setup_agent


async def setup_voice(hass, entry, http):
    agent = await setup_agent(hass, entry, http)
    coordinator = entry.runtime_data.coordinator
    store = coordinator.store
    store.async_refresh = AsyncMock(side_effect=lambda: store.snapshot)
    api = entry.runtime_data.api
    api.get_tracker = AsyncMock(
        side_effect=lambda workspace, key: deepcopy(store.snapshot.trackers[key])
    )
    api.get_subject = AsyncMock(
        side_effect=lambda workspace, key: deepcopy(store.snapshot.subjects[key])
    )
    writes = {}

    async def create(workspace, payload, *, idempotency_key):
        if idempotency_key in writes:
            assert writes[idempotency_key] == payload
        writes[idempotency_key] = deepcopy(payload)
        return {"id": "synthetic-entry", **deepcopy(payload)}

    api.create_entry = AsyncMock(side_effect=create)
    coordinator.async_entries_changed = Mock()
    return agent, api, writes


async def reviewed(hass, agent, language="en"):
    phrases = {
        "en": ("log Headache", "Anna", "yes", "seven", "/skip"),
        "pl": ("zapisz Headache", "Anna", "tak", "siedem", "/pomiń"),
    }
    start, *answers = phrases[language]
    result = await say(hass, agent, start, language=language)
    for text in answers:
        result = await say(hass, agent, text, result.conversation_id, language)
    return result
