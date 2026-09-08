"""Real HA entity setup with synthetic cached metadata and no network writes."""

from homeassistant.components import conversation
from homeassistant.core import Context

from custom_components.track_things.metadata import MetadataSnapshot

from .auth_fixtures import setup_responses
from .dialogue_fixtures import metadata


async def setup_agent(hass, entry, http, *, subjects=("anna", "ben")):
    setup_responses(http)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entities = hass.states.async_entity_ids("conversation")
    entity = next(
        conversation.async_get_agent(hass, entity_id)
        for entity_id in entities
        if getattr(conversation.async_get_agent(hass, entity_id), "entry", None) is entry
    )
    data = metadata(subjects)
    for tracker in data.trackers.values():
        tracker["workspaceId"] = entry.data["workspace_id"]
        tracker["name"] = "Headache"
    for subject in data.subjects.values():
        subject["workspaceId"] = entry.data["workspace_id"]
        subject["name"] = subject["id"].title()
    store = entry.runtime_data.coordinator.store
    store.snapshot = MetadataSnapshot(data.trackers, data.subjects, frozenset())
    store._schemas = data.schemas
    return entity


async def say(hass, agent, text, conversation_id=None, language="en", **identity):
    return await conversation.async_converse(
        hass,
        text=text,
        conversation_id=conversation_id,
        context=Context(user_id=identity.get("user_id", "user-a")),
        device_id=identity.get("device_id", "device-a"),
        satellite_id=identity.get("satellite_id"),
        language=language,
        agent_id=agent.entity_id,
    )


def speech(result):
    return result.response.speech["plain"]["speech"]
