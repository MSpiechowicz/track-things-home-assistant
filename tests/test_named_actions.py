"""Voice-facing names must resolve unambiguously without weakening value types."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.track_things.named_actions import named_values, record_entry, resolve

FIELDS = [{"id": "f", "key": "wellbeing", "label": "Wellbeing", "type": "number"}]


def test_names_normalized():
    item = {"id": "one", "name": "Health check-in"}
    assert resolve([item], "  HEALTH   check-in  ") == item


@pytest.mark.parametrize(
    "items",
    [
        [],
        [
            {"id": "a", "name": "Barbara"},
            {"id": "b", "name": "BARBARA"},
        ],
    ],
)
def test_no_guessing(items):
    with pytest.raises(ServiceValidationError):
        resolve(items, "Barbara")


def test_field_values_preserve_types():
    assert named_values(FIELDS, {"value": 3}) == {"wellbeing": 3}
    assert named_values(FIELDS, {"field": "WELLBEING", "value": "3"}) == {"wellbeing": "3"}


def test_choices_resolve_labels():
    fields = [
        {
            "key": "mood",
            "label": "Mood",
            "type": "select",
            "options": [{"id": "good", "label": "Feeling good"}],
        }
    ]
    assert named_values(fields, {"value": "feeling good"}) == {"mood": "good"}


@pytest.mark.parametrize(
    "data",
    [
        {"value": 3, "values": {}},
        {"values": {"Wellbeing": 3, "wellbeing": 4}},
        {"field": "unknown", "value": 3},
        {"field": "Wellbeing"},
    ],
)
def test_invalid_fields(data):
    with pytest.raises(ServiceValidationError):
        named_values(FIELDS, data)


async def test_record_resolves_ids_and_uses_guarded_writer():
    catalog = {
        "trackers": [
            {
                "id": "t",
                "name": "Health check-in",
                "subjects": [{"id": "s", "name": "Barbara"}],
                "fields": FIELDS,
            }
        ]
    }
    writer = AsyncMock(return_value={"entry": {}, "request_id": "r"})
    with (
        patch(
            "custom_components.track_things.named_actions.recording_options",
            AsyncMock(return_value=catalog),
        ),
        patch("custom_components.track_things.named_actions.async_create_entry", writer),
    ):
        result = await record_entry(
            None,
            SimpleNamespace(),
            {
                "tracker": "Health check-in",
                "subject": "Barbara",
                "value": 3,
            },
        )
    payload = writer.call_args.args[2]
    assert payload["trackerId"] == "t"
    assert payload["subjectId"] == "s"
    assert payload["values"] == {"wellbeing": 3}
    assert result["summary"] == "Recorded Health check-in for Barbara."


async def test_catalog_excludes_unselected_archived_and_unassigned():
    from custom_components.track_things.named_actions import recording_options

    tracker = {
        "id": "t",
        "name": "Health",
        "workspaceId": "w",
        "kind": "manual",
        "archivedAt": None,
        "currentSchemaVersionId": "v",
        "subjectIds": ["s"],
    }
    subjects = {
        "s": {"id": "s", "name": "Barbara", "workspaceId": "w", "archivedAt": None},
        "other": {"id": "other", "name": "Other", "workspaceId": "w", "archivedAt": None},
    }
    store = SimpleNamespace(
        workspace_id="w",
        snapshot=SimpleNamespace(
            trackers={"t": tracker, "other": {**tracker, "id": "other"}},
            subjects=subjects,
            missing_schema_ids=set(),
        ),
        async_schema=AsyncMock(return_value={"schema": {"fields": FIELDS}}),
    )
    coordinator = SimpleNamespace(store=store, async_refresh=AsyncMock(), last_update_success=True)
    entry = SimpleNamespace(
        options={"tracker_ids": ["t"]}, runtime_data=SimpleNamespace(coordinator=coordinator)
    )
    result = await recording_options(entry)
    assert [item["id"] for item in result["trackers"]] == ["t"]
    assert result["trackers"][0]["subjects"] == [{"id": "s", "name": "Barbara"}]
    tracker["archivedAt"] = "2026-01-01"
    assert (await recording_options(entry))["trackers"] == []


async def test_ambiguous_subject_never_writes():
    catalog = {
        "trackers": [
            {
                "id": "t",
                "name": "Health",
                "fields": FIELDS,
                "subjects": [{"id": "a", "name": "Barbara"}, {"id": "b", "name": "Barbara"}],
            }
        ]
    }
    writer = AsyncMock()
    with (
        patch(
            "custom_components.track_things.named_actions.recording_options",
            AsyncMock(return_value=catalog),
        ),
        patch("custom_components.track_things.named_actions.async_create_entry", writer),
        pytest.raises(ServiceValidationError, match="ambiguous"),
    ):
        await record_entry(None, None, {"tracker": "Health", "subject": "Barbara", "value": 3})
    writer.assert_not_called()


async def test_registered_name_action_writes_through_http(hass, config_entry, auth_http):
    from .api_fixtures import ENTRY, NOW, SUBJECT, TRACKER
    from .create_entry_fixtures import fresh_metadata, setup_writer

    await setup_writer(hass, config_entry, auth_http)
    auth_http.respond({"items": [{**TRACKER, "subjectIds": [SUBJECT["id"]]}], "nextCursor": None})
    auth_http.respond({"items": [SUBJECT], "nextCursor": None})
    fresh_metadata(auth_http)
    auth_http.respond(ENTRY, status=201)
    result = await hass.services.async_call(
        "track_things",
        "record_entry",
        {
            "config_entry_id": config_entry.entry_id,
            "tracker": TRACKER["name"],
            "subject": SUBJECT["name"],
            "field": "severity",
            "value": 6,
            "occurred_at": NOW,
        },
        blocking=True,
        return_response=True,
    )
    assert result["entry"] == ENTRY
    assert auth_http.request.call_args.kwargs["json"]["values"] == {"severity": 6}


def test_no_values_are_allowed_for_optional_fields():
    assert named_values(FIELDS, {}) == {}
    assert named_values([], {}) == {}
    assert named_values(FIELDS, {"number": 4}) == {"wellbeing": 4}


def test_relative_date_uses_ha_timezone(freezer):
    from custom_components.track_things.named_actions import recording_timestamp

    freezer.move_to("2026-09-08T23:30:00Z")
    assert recording_timestamp({"date": "tomorrow"}, "Europe/Berlin") == "2026-09-10T00:00:00+02:00"
    assert (
        recording_timestamp({"date": "2026-12-01"}, "Europe/Berlin") == "2026-12-01T00:00:00+01:00"
    )


@pytest.mark.parametrize(
    "data",
    [
        {"date": "nonsense"},
        {"date": "2026-02-30"},
        {"date": "tomorrow", "occurred_at": "2026-09-08T10:00:00Z"},
    ],
)
def test_invalid_or_conflicting_date(data):
    from custom_components.track_things.named_actions import recording_timestamp

    with pytest.raises(ServiceValidationError):
        recording_timestamp(data, "Europe/Berlin")


async def test_required_field_error_names_the_field():
    catalog = {
        "trackers": [
            {
                "id": "t",
                "name": "Migraine",
                "subjects": [{"id": "s", "name": "Maciej"}],
                "fields": [{**FIELDS[0], "required": True}],
            }
        ]
    }
    writer = AsyncMock()
    with (
        patch(
            "custom_components.track_things.named_actions.recording_options",
            AsyncMock(return_value=catalog),
        ),
        patch("custom_components.track_things.named_actions.async_create_entry", writer),
        pytest.raises(ServiceValidationError, match="Wellbeing"),
    ):
        await record_entry(None, None, {"tracker": "Migraine", "subject": "Maciej"})
    writer.assert_not_called()
