"""Synthetic calendar setup through the actual HA platform and API pagination."""

from copy import deepcopy

from .api_fixtures import SCHEMA, SUBJECT, TRACKER, USER, WORKSPACE


def calendar_setup_responses(http, entries=(), *, pages=None):
    http.respond(USER)
    http.respond(WORKSPACE)
    http.respond({"items": [{**TRACKER, "subjectIds": [SUBJECT["id"]]}], "nextCursor": None})
    http.respond({"items": [SUBJECT], "nextCursor": None})
    http.respond(SCHEMA)
    for page in pages or [{"items": list(entries), "nextCursor": None}]:
        http.respond(deepcopy(page))


async def setup_calendar(hass, config_entry, http, entries=()):
    calendar_setup_responses(http, entries)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    from homeassistant.components.calendar.const import DATA_COMPONENT

    return next(
        entity
        for entity in hass.data[DATA_COMPONENT].entities
        if entity.unique_id == f"{config_entry.entry_id}_calendar"
    )
