"""Name-based discovery and recording contracts for automation and voice adapters."""

import unicodedata
from datetime import UTC, datetime

import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .create_entry import _timestamp, async_create_entry

NAME = vol.All(str, vol.Length(min=1))
RECORD_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Required("tracker"): NAME,
        vol.Required("subject"): NAME,
        vol.Optional("field"): NAME,
        vol.Optional("value"): object,
        vol.Optional("values"): dict,
        vol.Optional("occurred_at"): _timestamp,
        vol.Optional("request_id"): vol.All(str, vol.Match(r"^[\x21-\x7e]{1,255}\Z")),
    }
)


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def resolve(items, name, label="name", identity="id"):
    """Exact normalized matching only; even ID/name collisions are ambiguous."""
    matches = [
        item
        for item in items
        if any(normalized(str(item[key])) == normalized(name) for key in (label, identity))
    ]
    if len(matches) != 1:
        reason = "ambiguous" if matches else "unknown"
        raise ServiceValidationError(
            f"{label.capitalize()} is {reason}. Use get_recording_options to select "
            "an available name or unique identifier; do not guess."
        )
    return matches[0]


async def recording_options(entry):
    coordinator = entry.runtime_data.coordinator
    await coordinator.async_refresh()
    if not coordinator.last_update_success:
        raise HomeAssistantError("Track Things metadata is unavailable")
    store = coordinator.store
    snapshot = store.snapshot
    selected = entry.options.get("tracker_ids")
    trackers = []
    for tracker in snapshot.trackers.values():
        if (
            tracker["workspaceId"] != store.workspace_id
            or tracker["kind"] != "manual"
            or tracker["archivedAt"] is not None
            or (selected is not None and tracker["id"] not in selected)
            or not tracker["currentSchemaVersionId"]
            or tracker["currentSchemaVersionId"] in snapshot.missing_schema_ids
        ):
            continue
        schema = await store.async_schema(tracker["id"], tracker["currentSchemaVersionId"])
        subjects = [
            {"id": subject["id"], "name": subject["name"]}
            for subject in snapshot.subjects.values()
            if subject["id"] in tracker["subjectIds"]
            and subject["workspaceId"] == store.workspace_id
            and subject["archivedAt"] is None
        ]
        trackers.append(
            {
                "id": tracker["id"],
                "name": tracker["name"],
                "subjects": subjects,
                "fields": schema["schema"]["fields"],
            }
        )
    return {"contract_version": 1, "trackers": trackers}


def named_values(fields, data):
    if "values" in data:
        if "field" in data or "value" in data:
            raise ServiceValidationError("Use either values or field and value")
        source = data["values"]
    else:
        if "value" not in data:
            raise ServiceValidationError("Provide a value or values")
        if "field" not in data and len(fields) != 1:
            raise ServiceValidationError("Specify the field to record")
        source = {data.get("field", fields[0]["key"] if fields else ""): data["value"]}
    result = {}
    for name, value in source.items():
        if not isinstance(name, str):
            raise ServiceValidationError("Field names must be text")
        field = resolve(fields, name, "label", "key")
        if field["key"] in result:
            raise ServiceValidationError("A field was provided more than once")
        if field["type"] in ("select", "multiselect"):

            def option(item, options=field["options"]):
                if not isinstance(item, str):
                    raise ServiceValidationError("Choice values must be names or IDs")
                return resolve(options, item, "label")["id"]

            if field["type"] == "multiselect":
                if not isinstance(value, list):
                    raise ServiceValidationError("Multiple choices must be a list")
                value = [option(item) for item in value]
            else:
                value = option(value)
        result[field["key"]] = value
    return result


async def record_entry(hass, entry, data):
    catalog = await recording_options(entry)
    tracker = resolve(catalog["trackers"], data["tracker"])
    subject = resolve(tracker["subjects"], data["subject"])
    values = named_values(tracker["fields"], data)
    occurred_at = data.get("occurred_at")
    if data.get("request_id") and occurred_at is None:
        raise ServiceValidationError("Retries require the original occurred_at timestamp")
    occurred_at = occurred_at or datetime.now(UTC).isoformat()
    try:
        result = await async_create_entry(
            hass,
            entry,
            {
                "trackerId": tracker["id"],
                "subjectId": subject["id"],
                "values": values,
                "occurredAt": occurred_at,
                **({"request_id": data["request_id"]} if "request_id" in data else {}),
            },
        )
    except ServiceValidationError:
        raise
    except HomeAssistantError as err:
        raise HomeAssistantError(f"{err}. Original occurred_at={occurred_at}") from None
    return {
        **result,
        "occurred_at": occurred_at,
        "summary": f"Recorded {tracker['name']} for {subject['name']}.",
        "tracker": tracker["name"],
        "subject": subject["name"],
    }
