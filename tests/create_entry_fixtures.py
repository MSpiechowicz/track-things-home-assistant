"""Write-action fixtures without loading a calendar platform."""

from unittest.mock import AsyncMock, patch

from .api_fixtures import NOW, SCHEMA, SUBJECT, TRACKER, USER, WORKSPACE

DATA = {
    "trackerId": TRACKER["id"],
    "subjectId": SUBJECT["id"],
    "occurredAt": NOW,
    "values": {"severity": 6},
    "request_id": "synthetic-request-1",
}


async def setup_writer(hass, entry, http):
    for response in (
        USER,
        WORKSPACE,
        {"items": [{**TRACKER, "subjectIds": [SUBJECT["id"]]}], "nextCursor": None},
        {"items": [SUBJECT], "nextCursor": None},
        SCHEMA,
    ):
        http.respond(response)
    entry.add_to_hass(hass)
    with patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def fresh_metadata(http, *, tracker=None, subject=None):
    http.respond(TRACKER if tracker is None else tracker)
    http.respond(SUBJECT if subject is None else subject)


async def create(hass, entry, data=None):
    return await hass.services.async_call(
        "track_things",
        "create_entry",
        {"config_entry_id": entry.entry_id, **(DATA if data is None else data)},
        blocking=True,
        return_response=True,
    )
