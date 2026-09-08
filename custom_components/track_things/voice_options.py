"""Stable, language-scoped voice references shared by configuration and recognition."""

import json

from .api_errors import ApiError
from .conversation_language import SENTENCES
from .conversation_values import normalized
from .dialogue_models import DraftMetadata
from .dialogue_rules import eligible_subjects, eligible_trackers

CONF_ALIASES = "voice_aliases"
CONF_DEFAULT_SUBJECT = "voice_default_subject"
ME = {"en": {"me"}, "pl": {"ja", "mnie", "dla mnie"}, "de": {"ich", "mich"}, "fr": {"moi"}}


def target_key(scope, resource_id):
    return json.dumps([scope, resource_id], ensure_ascii=False)


def catalog(metadata):
    """Catalog current IDs, including tracker-scoped schema field and option IDs."""
    result = {}
    for key, subject in metadata.subjects.items():
        if subject["workspaceId"] == metadata.workspace_id and subject["archivedAt"] is None:
            result[target_key("subjects", key)] = f"{subject['name']} · subject ({key})"
    for key in eligible_trackers(metadata):
        tracker = metadata.trackers[key]
        label = tracker["name"]
        result[target_key("trackers", key)] = f"{label} · tracker ({key})"
        version = metadata.schemas.get(tracker["currentSchemaVersionId"])
        if not version or version["trackerId"] != key:
            continue
        for definition in version["schema"]["fields"]:
            field_id = definition["id"]
            field_label = f"{label} / {definition['label']}"
            result[target_key(f"{key}:fields", field_id)] = f"{field_label} ({field_id})"
            for option in definition.get("options", []):
                result[target_key(f"{key}:{field_id}:options", option["id"])] = (
                    f"{field_label} / {option['label']} ({option['id']})"
                )
    return result


async def current_metadata(entry):
    coordinator = entry.runtime_data.coordinator
    if not coordinator.last_update_success:
        raise ApiError(code="metadata_unavailable")
    snapshot = coordinator.store.snapshot
    schemas = {}
    for tracker in snapshot.trackers.values():
        version = tracker["currentSchemaVersionId"]
        if version and version not in snapshot.missing_schema_ids:
            schemas[version] = await coordinator.store.async_schema(tracker["id"], version)
    return DraftMetadata(entry.data["workspace_id"], snapshot.trackers, snapshot.subjects, schemas)


def alias_mapping(options, resources):
    """Rebuild literal recognition inputs; unavailable references never match."""
    result = {}
    for language, targets in options.get(CONF_ALIASES, {}).items():
        if language not in SENTENCES:
            continue
        for target, aliases in targets.items():
            if target not in resources:
                continue
            scope, resource_id = json.loads(target)
            if isinstance(aliases, list) and all(isinstance(alias, str) for alias in aliases):
                result.setdefault(f"{language}:{scope}", {})[resource_id] = tuple(aliases)
    return result


def default_subject(options, metadata, tracker_id):
    key = options.get(CONF_DEFAULT_SUBJECT)
    if tracker_id not in eligible_trackers(metadata):
        return None
    return key if key in eligible_subjects(metadata, tracker_id) else None


def parse_aliases(text):
    if not isinstance(text, str):
        raise ValueError("invalid_alias")
    aliases = list(dict.fromkeys(line.strip() for line in text.splitlines() if line.strip()))
    if len(aliases) > 30 or any(len(alias) > 100 or not normalized(alias) for alias in aliases):
        raise ValueError("invalid_alias")
    return aliases
