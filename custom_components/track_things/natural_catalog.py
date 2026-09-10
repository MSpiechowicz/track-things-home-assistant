"""Explicit, minimal metadata projection for the external wording interpreter."""

from .dialogue_rules import eligible_subjects, eligible_trackers


def _scalars(value, keys):
    """Never pass arbitrary nested metadata through a selected property."""
    return {
        key: value[key]
        for key in keys
        if key in value and type(value[key]) in (str, bool, int, float)
    }


def _field(field):
    result = _scalars(field, ("id", "key", "label", "type", "required"))
    if "options" in field:
        result["options"] = [_scalars(option, ("id", "label")) for option in field["options"]]
    if "validation" in field:
        result["validation"] = _scalars(
            field["validation"], ("min", "max", "step", "minLength", "maxLength")
        )
    if "visibleWhen" in field:
        result["visibleWhen"] = _scalars(field["visibleWhen"], ("fieldId", "operator", "value"))
    return result


def interpreter_catalog(metadata):
    """Only eligible assignments and interpretation fields may leave HA."""
    trackers, subjects, schemas = {}, {}, {}
    for tracker_id in eligible_trackers(metadata):
        tracker = metadata.trackers[tracker_id]
        assigned = eligible_subjects(metadata, tracker_id)
        trackers[tracker_id] = {
            **_scalars(tracker, ("id", "name", "currentSchemaVersionId")),
            "subjectIds": list(assigned),
        }
        for subject_id in assigned:
            subjects[subject_id] = _scalars(metadata.subjects[subject_id], ("id", "name"))
        version_id = tracker["currentSchemaVersionId"]
        version = metadata.schemas[version_id]
        schemas[version_id] = {
            **_scalars(version, ("id", "trackerId")),
            "schema": {"fields": [_field(field) for field in version["schema"]["fields"]]},
        }
    return {"trackers": trackers, "subjects": subjects, "schemas": schemas}
