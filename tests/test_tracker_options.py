"""Read-only selection and active manual write eligibility from cached metadata."""

from custom_components.track_things.coordinator import MetadataCoordinator

from .api_fixtures import TRACKER
from .auth_fixtures import setup_responses
from .test_metadata import metadata_api


async def test_tracker_kinds_and_empty_selection(hass, config_entry):
    config_entry.add_to_hass(hass)
    trackers = [
        TRACKER,
        {**TRACKER, "id": "integration", "kind": "integration"},
        {**TRACKER, "id": "computed", "kind": "computed"},
        {**TRACKER, "id": "archived", "archivedAt": "past"},
        {**TRACKER, "id": "no-schema", "currentSchemaVersionId": None},
    ]
    # Each tracker has its own immutable schema identity.
    for tracker in trackers[1:]:
        tracker["currentSchemaVersionId"] = None
    coordinator = MetadataCoordinator(hass, config_entry, metadata_api(trackers))
    await coordinator.async_refresh()
    assert set(coordinator.calendar_trackers) == {t["id"] for t in trackers}
    assert set(coordinator.voice_trackers) == {"tracker-1"}
    hass.config_entries.async_update_entry(config_entry, options={"tracker_ids": ["computed"]})
    assert set(coordinator.calendar_trackers) == {"computed"}
    assert not coordinator.voice_trackers
    hass.config_entries.async_update_entry(config_entry, options={"tracker_ids": []})
    assert not coordinator.calendar_trackers
    await coordinator.async_shutdown()


async def test_real_options_flow_keeps_runtime_and_schema_cache(hass, config_entry, auth_http):
    setup_responses(auth_http)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    runtime = config_entry.runtime_data
    runtime.coordinator.store.snapshot.trackers["tracker-1"] = TRACKER
    calls = auth_http.request.call_count
    auth_http.respond({"items": [], "nextCursor": None})
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"tracker_ids": ["tracker-1"]}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert config_entry.options == {
        "tracker_ids": ["tracker-1"],
        "voice_workspace_entries": [config_entry.entry_id],
        "voice_preferred_workspace": "",
    }
    assert config_entry.runtime_data is runtime
    assert auth_http.request.call_count == calls + 1
    assert auth_http.request.call_args.args[1].endswith("/entries")
    assert await hass.config_entries.async_unload(config_entry.entry_id)
