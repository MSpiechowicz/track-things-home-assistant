"""Ordered readable prompts and explicit default proposals from draft descriptors."""

from .conversation_contract import Clarification, Question
from .conversation_language import WORDS
from .dialogue_models import DraftPatch
from .dialogue_rules import patch_values, tracker_schema
from .schema import EntryValueError, resolve_field_visibility


def questions(result, metadata, language):
    if language not in WORDS:
        raise Clarification("unsupported_language")
    words = WORDS[language]
    prompts = []
    for descriptor in result.descriptors:
        if descriptor.kind in ("tracker", "subject"):
            resources = metadata.trackers if descriptor.kind == "tracker" else metadata.subjects
            names = ", ".join(resources[key].get("name", key) for key in descriptor.candidates)
            wording = words[descriptor.kind]
            prompts.append(
                Question(descriptor.kind, f"{wording} {names}", candidates=descriptor.candidates)
            )
            continue
        definition = descriptor.definition
        text = f"{definition['label']}?"
        if definition["type"] in ("select", "multiselect"):
            text += " " + ", ".join(item["label"] for item in definition["options"])
        if definition["type"] == "boolean":
            text += " " + words["boolean"]
        if definition["type"] in ("number", "slider"):
            rules = definition.get("validation", {})
            if "min" in rules and "max" in rules:
                text += f" {rules['min']}–{rules['max']}."
        if descriptor.kind == "optional":
            text += " " + words["optional"]
        prompts.append(Question(descriptor.kind, text, descriptor.key))
    return tuple(prompts)


def default_patch(metadata, tracker_id, current_values):
    """Propose only validated defaults, in schema order, including revealed fields.

    Missing required values are still asked by DraftStore. Existing answers are
    preserved. Invalid defaults are ignored and remain ordinary questions.
    """
    schema = tracker_schema(metadata, tracker_id)
    values = dict(current_values)
    selected = set()
    for definition in schema["fields"]:
        key = definition["key"]
        if key in values or "defaultValue" not in definition:
            continue
        if not resolve_field_visibility(schema, values)[definition["id"]]:
            continue
        try:
            values, _ = patch_values(
                schema, values, set(), DraftPatch(accept_defaults=frozenset({key}))
            )
        except EntryValueError:
            continue
        selected.add(key)
    if not selected:
        raise Clarification("defaults_unavailable")
    return DraftPatch(accept_defaults=frozenset(selected))


def defaults_question(metadata, tracker_id, current_values, language):
    if language not in WORDS:
        raise Clarification("unsupported_language")
    patch = default_patch(metadata, tracker_id, current_values)
    fields = tracker_schema(metadata, tracker_id)["fields"]
    details = "; ".join(
        f"{item['label']}: {_readable(item, language)}"
        for item in fields
        if item["key"] in patch.accept_defaults
    )
    return Question("defaults", f"{WORDS[language]['defaults']} {details}")


def _readable(definition, language):
    value = definition["defaultValue"]
    if definition["type"] == "boolean":
        return next(key for key, item in WORDS[language]["booleans"].items() if item == value)
    if definition["type"] in ("select", "multiselect"):
        labels = {item["id"]: item["label"] for item in definition["options"]}
        return (
            ", ".join(labels[item] for item in value) if isinstance(value, list) else labels[value]
        )
    return str(value)
