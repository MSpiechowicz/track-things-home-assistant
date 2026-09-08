"""Fresh metadata invalidates old confirmation and preserves compatible answers."""

from copy import deepcopy

from custom_components.track_things.api_errors import ConflictError, TransportError
from custom_components.track_things.metadata import MetadataSnapshot

from .conversation_fixtures import say, speech
from .voice_creation_fixtures import reviewed, setup_voice


def change_schema(entry, *, required=False):
    store = entry.runtime_data.coordinator.store
    version = deepcopy(store._schemas["schema-1"])
    version["id"] = "schema-2"
    if required:
        version["schema"]["fields"].append(
            {"id": "extra", "key": "extra", "label": "Extra", "type": "boolean", "required": True}
        )
    store._schemas["schema-2"] = version
    store.snapshot.trackers["headache"]["currentSchemaVersionId"] = "schema-2"


async def test_schema_change_retains_answers_and_requires_new_confirmation(
    hass, config_entry, auth_http
):
    agent, api, writes = await setup_voice(hass, config_entry, auth_http)
    result = await reviewed(hass, agent)
    change_schema(config_entry, required=True)
    cid = result.conversation_id
    result = await say(hass, agent, "confirm", cid)
    assert "changed" in speech(result)
    assert "Extra" in speech(result)
    assert not writes
    await say(hass, agent, "confirm", cid)
    assert not writes
    result = await say(hass, agent, "yes", cid)
    assert "Severity: 7" in speech(result)
    assert "Extra: yes" in speech(result)
    assert not writes
    assert "Entry saved" in speech(await say(hass, agent, "confirm", cid))
    assert next(iter(writes.values()))["expectedSchemaVersionId"] == "schema-2"


async def test_reassignment_requires_explicit_subject_choice(hass, config_entry, auth_http):
    agent, api, writes = await setup_voice(hass, config_entry, auth_http)
    result = await reviewed(hass, agent)
    config_entry.runtime_data.coordinator.store.snapshot.trackers["headache"]["subjectIds"] = [
        "ben"
    ]
    cid = result.conversation_id
    result = await say(hass, agent, "confirm", cid)
    assert "Who is this for" in speech(result)
    assert "Ben" in speech(result)
    assert not writes
    result = await say(hass, agent, "Ben", cid)
    assert "Headache; Ben;" in speech(result)
    assert "Severity: 7" in speech(result)
    await say(hass, agent, "confirm", cid)
    assert next(iter(writes.values()))["subjectId"] == "ben"


async def test_backend_guard_conflict_recovers_to_fresh_review(hass, config_entry, auth_http):
    agent, api, writes = await setup_voice(hass, config_entry, auth_http)
    sink = api.create_entry.side_effect

    async def conflict(*args, **kwargs):
        change_schema(config_entry)
        raise ConflictError(409, code="schema_conflict")

    api.create_entry.side_effect = conflict
    result = await reviewed(hass, agent)
    cid = result.conversation_id
    result = await say(hass, agent, "confirm", cid)
    assert "Review" in speech(result)
    assert not writes
    api.create_entry.side_effect = sink
    await say(hass, agent, "confirm", cid)
    assert len(writes) == 1
    assert next(iter(writes.values()))["expectedSchemaVersionId"] == "schema-2"


async def test_metadata_race_between_refresh_and_prepare_cannot_write(
    hass, config_entry, auth_http
):
    agent, api, writes = await setup_voice(hass, config_entry, auth_http)
    original = api.get_tracker.side_effect

    async def racing(*args):
        change_schema(config_entry)
        return original(*args)

    api.get_tracker.side_effect = racing
    result = await reviewed(hass, agent)
    result = await say(hass, agent, "confirm", result.conversation_id)
    assert "changed" in speech(result)
    assert not writes
    api.create_entry.assert_not_called()


async def test_refresh_failure_does_not_consume_review(hass, config_entry, auth_http):
    agent, api, writes = await setup_voice(hass, config_entry, auth_http)
    result = await reviewed(hass, agent)
    store = config_entry.runtime_data.coordinator.store
    refresh = store.async_refresh.side_effect
    store.async_refresh.side_effect = TransportError()
    assert "No write was attempted" in speech(
        await say(hass, agent, "confirm", result.conversation_id)
    )
    assert not writes
    store.async_refresh.side_effect = refresh
    await say(hass, agent, "confirm", result.conversation_id)
    assert len(writes) == 1


async def test_removed_tracker_returns_to_selection(hass, config_entry, auth_http):
    agent, api, writes = await setup_voice(hass, config_entry, auth_http)
    result = await reviewed(hass, agent)
    store = config_entry.runtime_data.coordinator.store
    store.snapshot = MetadataSnapshot({}, store.snapshot.subjects, frozenset())
    result = await say(hass, agent, "confirm", result.conversation_id)
    assert "changed" in speech(result)
    assert not writes
    api.create_entry.assert_not_called()


async def test_compatible_answer_survives_changed_constraints(hass, config_entry, auth_http):
    agent, api, writes = await setup_voice(hass, config_entry, auth_http)
    result = await reviewed(hass, agent)
    change_schema(config_entry)
    schema = config_entry.runtime_data.coordinator.store._schemas["schema-2"]["schema"]
    schema["fields"][1]["validation"]["max"] = 20
    result = await say(hass, agent, "confirm", result.conversation_id)
    assert "Severity: 7" in speech(result)
    assert "Review" in speech(result)
    assert not writes


async def test_invalid_answer_is_requested_again(hass, config_entry, auth_http):
    agent, api, writes = await setup_voice(hass, config_entry, auth_http)
    result = await reviewed(hass, agent)
    change_schema(config_entry)
    schema = config_entry.runtime_data.coordinator.store._schemas["schema-2"]["schema"]
    schema["fields"][1]["validation"]["max"] = 5
    result = await say(hass, agent, "confirm", result.conversation_id)
    assert "Severity?" in speech(result)
    assert not writes


async def test_conflict_reconfirmation_uses_new_key(hass, config_entry, auth_http):
    agent, api, writes = await setup_voice(hass, config_entry, auth_http)
    sink = api.create_entry.side_effect
    api.create_entry.side_effect = ConflictError(409, code="schema_conflict")
    result = await reviewed(hass, agent)
    await say(hass, agent, "confirm", result.conversation_id)
    first_key = api.create_entry.call_args.kwargs["idempotency_key"]
    api.create_entry.side_effect = sink
    await say(hass, agent, "confirm", result.conversation_id)
    assert api.create_entry.call_args.kwargs["idempotency_key"] != first_key
    assert len(writes) == 1


async def test_queued_old_confirmation_cannot_confirm_changed_review(hass, config_entry, auth_http):
    import asyncio

    agent, api, writes = await setup_voice(hass, config_entry, auth_http)
    result = await reviewed(hass, agent)
    change_schema(config_entry)
    # Force both turns to arrive against the old review before processing either.
    async with agent._turn_lock:
        one = asyncio.create_task(say(hass, agent, "confirm", result.conversation_id))
        two = asyncio.create_task(say(hass, agent, "confirm", result.conversation_id))
        await asyncio.sleep(0)
    responses = await asyncio.gather(one, two)
    assert any("changed" in speech(item) for item in responses)
    assert not writes
    await say(hass, agent, "confirm", result.conversation_id)
    assert len(writes) == 1
