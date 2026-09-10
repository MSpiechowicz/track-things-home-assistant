"""Only relevant, allowlisted metadata crosses the external provider boundary."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from custom_components.track_things.natural_catalog import interpreter_catalog

from .dialogue_fixtures import metadata
from .test_natural_conversation import model_result, natural_agent, user


def private_metadata(data):
    data.subjects["anna"].update(
        name="Anna",
        metadata={"secret": "PRIVATE_SUBJECT"},
        avatarUrl="PRIVATE_AVATAR",
        relationship="PRIVATE_RELATIONSHIP",
        futureProperty="PRIVATE_FUTURE",
    )
    for key, changes in {
        "unassigned": {},
        "archived": {"archivedAt": "2026-09-01"},
        "foreign": {"workspaceId": "another-workspace"},
    }.items():
        data.subjects[key] = {
            **data.subjects["anna"],
            "id": key,
            "name": f"PRIVATE_{key}",
            **changes,
        }
    tracker = data.trackers["headache"]
    tracker.update(name="Headache", description="PRIVATE_DESCRIPTION", future="PRIVATE_TRACKER")
    tracker["subjectIds"] += ["archived", "foreign"]
    version = data.schemas["schema-1"]
    version["createdByUserId"] = "PRIVATE_AUTHOR"
    version["schema"]["future"] = "PRIVATE_SCHEMA"
    fields = version["schema"]["fields"]
    fields[0].update(
        ui={"secret": "PRIVATE_UI"}, defaultValue="PRIVATE_DEFAULT", future="PRIVATE_FIELD"
    )
    fields[1]["validation"]["future"] = "PRIVATE_VALIDATION"
    fields.append(
        {
            "id": "choice",
            "key": "choice",
            "label": "Choice",
            "type": "select",
            "options": [{"id": "yes", "label": "Yes", "future": "PRIVATE_OPTION"}],
        }
    )


def test_catalog_preserves_interpretation_fields_without_private_metadata():
    data = metadata(("anna",))
    private_metadata(data)
    before = deepcopy(data)
    result = interpreter_catalog(data)
    assert data == before
    assert "PRIVATE_" not in json.dumps(result)
    assert result["subjects"] == {"anna": {"id": "anna", "name": "Anna"}}
    assert result["trackers"]["headache"] == {
        "id": "headache",
        "name": "Headache",
        "subjectIds": ["anna"],
        "currentSchemaVersionId": "schema-1",
    }
    fields = result["schemas"]["schema-1"]["schema"]["fields"]
    assert fields[0] == {
        "id": "pain-id",
        "key": "pain",
        "label": "Pain",
        "type": "boolean",
        "required": True,
    }
    assert fields[1]["validation"] == {"min": 1, "max": 10, "step": 1}
    assert fields[1]["visibleWhen"] == {"fieldId": "pain-id", "operator": "equals", "value": True}
    assert fields[-1]["options"] == [{"id": "yes", "label": "Yes"}]


@pytest.mark.parametrize("selected", [[], ["headache"]])
@pytest.mark.parametrize("multiple", [False, True])
async def test_provider_payload_filters_every_workspace(
    hass, config_entry, auth_http, selected, multiple
):
    agent = await natural_agent(hass, config_entry, auth_http)
    # Attach private fields to actual cached resources used by the production path.
    data = await agent._metadata()
    private_metadata(data)
    store = config_entry.runtime_data.coordinator.store
    store._schemas = data.schemas
    hass.config_entries.async_update_entry(config_entry, options={"tracker_ids": selected})
    entries = {config_entry.entry_id: config_entry}
    if multiple:
        entries["other"] = SimpleNamespace(
            entry_id="other",
            title="Family",
            data=dict(config_entry.data),
            runtime_data=config_entry.runtime_data,
            options={},
        )
    with (
        patch(
            "custom_components.track_things.natural_conversation.connected", return_value=entries
        ),
        patch.object(agent, "_gemini", return_value="conversation.interpreter"),
        patch(
            "homeassistant.components.conversation.async_converse",
            return_value=model_result({"action": "clarify"}),
        ) as provider,
    ):
        await agent.async_process(user("log headache"))
    prompt = provider.call_args.kwargs["text"]
    assert "PRIVATE_" not in prompt
    payload = json.loads(prompt.split("\nINPUT DATA:\n", 1)[1])
    assert len(payload["workspaces"]) == (2 if multiple else 1)
    for catalog in payload["workspaces"]:
        assert catalog["subjects"] == ({"anna": {"id": "anna", "name": "Anna"}} if selected else {})
        assert bool(catalog["trackers"]) == bool(selected)
        assert bool(catalog["schemas"]) == bool(selected)
    assert payload["subjects"] == (payload["workspaces"][0]["subjects"] if not multiple else {})
