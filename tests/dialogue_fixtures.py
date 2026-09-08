"""Synthetic typed conversation inputs, shared by the offline replay tests."""

from datetime import UTC, datetime

from custom_components.track_things.dialogue import DraftMetadata, DraftPatch, DraftStore

NOW = datetime(2026, 9, 8, 12, 30, tzinfo=UTC)


def metadata(subject_ids=("anna", "ben")):
    return DraftMetadata(
        "workspace",
        {
            "headache": {
                "id": "headache",
                "workspaceId": "workspace",
                "kind": "manual",
                "archivedAt": None,
                "subjectIds": list(subject_ids),
                "currentSchemaVersionId": "schema-1",
            }
        },
        {key: {"id": key, "workspaceId": "workspace", "archivedAt": None} for key in subject_ids},
        {
            "schema-1": {
                "id": "schema-1",
                "trackerId": "headache",
                "schema": {
                    "fields": [
                        {
                            "id": "pain-id",
                            "key": "pain",
                            "label": "Pain",
                            "type": "boolean",
                            "required": True,
                            "defaultValue": True,
                        },
                        {
                            "id": "severity-id",
                            "key": "severity",
                            "label": "Severity",
                            "type": "slider",
                            "required": True,
                            "validation": {"min": 1, "max": 10, "step": 1},
                            "visibleWhen": {
                                "fieldId": "pain-id",
                                "operator": "equals",
                                "value": True,
                            },
                        },
                        {"id": "note-id", "key": "note", "label": "Note", "type": "textarea"},
                    ]
                },
            }
        },
    )


def store():
    return DraftStore(clock=lambda: NOW)


def complete(store, draft_id="one"):
    return store.start(
        draft_id,
        metadata(),
        DraftPatch(
            tracker_id="headache",
            subject_id="anna",
            values={"pain": True, "severity": 7},
        ),
    )
