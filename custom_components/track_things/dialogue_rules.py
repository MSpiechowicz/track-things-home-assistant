"""Pure resource eligibility, field proposals, and occurrence serialization."""

from copy import deepcopy
from datetime import UTC, date, datetime, time
from typing import Any

from .dialogue_models import Descriptor, DraftError, DraftMetadata, DraftPatch
from .schema import normalize_draft_values, resolve_field_visibility, validate_entry_values


def eligible_trackers(metadata: DraftMetadata) -> tuple[str, ...]:
    return tuple(
        key
        for key, tracker in metadata.trackers.items()
        if tracker["id"] == key
        and tracker["workspaceId"] == metadata.workspace_id
        and tracker["archivedAt"] is None
        and tracker["kind"] == "manual"
    )


def tracker_schema(metadata: DraftMetadata, tracker_id: str) -> dict[str, Any]:
    if tracker_id not in eligible_trackers(metadata):
        raise DraftError("tracker_unavailable")
    version_id = metadata.trackers[tracker_id]["currentSchemaVersionId"]
    version = metadata.schemas.get(version_id)
    if not version or version["id"] != version_id or version["trackerId"] != tracker_id:
        raise DraftError("schema_unavailable")
    # Validate the complete schema even when no draft values exist yet.
    validate_entry_values({}, version["schema"], partial=True)
    return version["schema"]


def eligible_subjects(metadata: DraftMetadata, tracker_id: str) -> tuple[str, ...]:
    assigned = metadata.trackers[tracker_id]["subjectIds"]
    return tuple(
        key
        for key, subject in metadata.subjects.items()
        if key in assigned
        and subject["id"] == key
        and subject["workspaceId"] == metadata.workspace_id
        and subject["archivedAt"] is None
    )


def patch_values(schema, values, skipped, patch: DraftPatch):
    fields = {item["key"]: item for item in schema["fields"]}
    touched = set(patch.values) | patch.remove | patch.accept_defaults | patch.skip_optional
    if touched - fields.keys():
        raise DraftError("unknown_field")
    operations = [set(patch.values), patch.remove, patch.accept_defaults, patch.skip_optional]
    if sum(map(len, operations)) != len(touched):
        raise DraftError("conflicting_patch")
    values = deepcopy(values)
    skipped = set(skipped) - touched
    for key in patch.remove | patch.skip_optional:
        values.pop(key, None)
    values.update(deepcopy(patch.values))
    # Schema order resolves defaulted controllers before their dependents.
    for key, definition in fields.items():
        if key in patch.accept_defaults:
            if key in values or "defaultValue" not in definition:
                raise DraftError("default_unavailable")
            values[key] = deepcopy(definition["defaultValue"])
    visible = resolve_field_visibility(schema, values)
    for key in patch.skip_optional:
        if fields[key].get("required", False) or not visible[fields[key]["id"]]:
            raise DraftError("cannot_skip_field")
        skipped.add(key)
    if any(not visible[fields[key]["id"]] for key in set(patch.values) | patch.accept_defaults):
        raise DraftError("hidden_field")
    values = normalize_draft_values(schema, values)
    skipped = {key for key in skipped if visible[fields[key]["id"]]}
    validate_entry_values(values, schema, partial=True)
    return values, skipped


def field_descriptors(schema, values, skipped) -> tuple[Descriptor, ...]:
    visible = resolve_field_visibility(schema, values)
    return tuple(
        Descriptor(
            "required" if definition.get("required", False) else "optional",
            key=definition["key"],
            definition=deepcopy(definition),
        )
        for definition in schema["fields"]
        if visible[definition["id"]]
        and definition["key"] not in values
        and definition["key"] not in skipped
    )


def occurrence_payload(occurrence: date | datetime) -> dict[str, str]:
    if isinstance(occurrence, datetime):
        if occurrence.utcoffset() is None:
            raise DraftError("timezone_required")
        return {"occurredAt": occurrence.astimezone(UTC).isoformat()}
    if isinstance(occurrence, date):
        # Backend period dates use UTC serialization, not local midnight conversion.
        stamp = datetime.combine(occurrence, time(), UTC).isoformat()
        return {"occurredAt": stamp, "periodStart": stamp, "periodEnd": stamp}
    raise DraftError("invalid_occurrence")
