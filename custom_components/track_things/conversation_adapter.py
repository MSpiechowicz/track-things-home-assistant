"""Stateless four-language Hassil adapter producing shared draft proposals."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from hassil import Intents, recognize_all

from .conversation_contract import Clarification, Proposal
from .conversation_language import SENTENCES, WORDS
from .conversation_questions import default_patch
from .conversation_values import normalized, occurrence, resolve, value
from .dialogue_models import Descriptor, DraftMetadata, DraftPatch
from .dialogue_rules import eligible_subjects, eligible_trackers, tracker_schema
from .schema import normalize_draft_values, validate_entry_values


@dataclass(frozen=True, repr=False)
class AdapterContext:
    metadata: DraftMetadata
    language: str
    now: datetime
    time_zone: str
    tracker_id: str | None = None
    descriptor: Descriptor | None = None
    # Explicit runtime mode after presenting defaults_question; never confirmation.
    offering_defaults: bool = False
    values: dict[str, Any] = field(default_factory=dict)
    # Language is selected before lookup; tracker/field scopes prevent collisions.
    aliases: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)

    def names(self, scope):
        return self.aliases.get(f"{self.language}:{scope}", {})


class QuestionAdapter:
    def __init__(self, language):
        if language not in SENTENCES:
            raise Clarification("unsupported_language")
        self.language = language
        self.intents = Intents.from_dict(
            {
                "language": language,
                "intents": {
                    name: {"data": [{"sentences": sentences}]}
                    for name, sentences in SENTENCES[language].items()
                },
                "lists": {name: {"wildcard": True} for name in ("answer", "detail")},
            }
        )

    def parse(self, text: str, context: AdapterContext) -> Proposal:
        if context.language != self.language:
            raise Clarification("unsupported_language")
        if context.offering_defaults:
            answer = WORDS[self.language]["booleans"].get(normalized(text))
            if answer is not None:
                if not answer:
                    return Proposal("more")
                if not context.tracker_id:
                    raise Clarification("tracker_required")
                return Proposal(
                    "patch", default_patch(context.metadata, context.tracker_id, context.values)
                )
        # Free text is data, even when it says "confirm" or contains instructions.
        descriptor = context.descriptor
        if (
            not text.startswith("/")
            and descriptor
            and descriptor.definition
            and descriptor.definition["type"] in ("text", "textarea")
        ):
            return self._answer(text, context)
        matches = list(recognize_all(text.removeprefix("/"), self.intents))
        if not matches:
            if descriptor:
                return self._answer(text, context)
            raise Clarification("unsupported_input")
        # Fixed control phrases outrank wildcard create patterns.
        fixed = [match for match in matches if not match.entities]
        if fixed:
            matches = fixed
        signatures = {
            (
                match.intent.name,
                tuple((key, entity.value) for key, entity in match.entities.items()),
            )
            for match in matches
        }
        if len(signatures) != 1:
            raise Clarification("ambiguous_command")
        match = matches[0]
        action = match.intent.name
        answer = match.entities.get("answer")
        if action in ("review", "confirm", "cancel", "repeat", "more"):
            return Proposal(action)
        if action == "create":
            if answer is None:
                return Proposal("create")
            ids = eligible_trackers(context.metadata)
            key = resolve(
                answer.value,
                {key: context.metadata.trackers[key].get("name", key) for key in ids},
                context.names("trackers"),
            )
            return Proposal("create", DraftPatch(tracker_id=key))
        if action in ("when", "calendar"):
            parsed = occurrence(
                answer.value if answer else WORDS[self.language]["today"],
                self.language,
                context.now,
                context.time_zone,
            )
            if action == "calendar":
                day = (
                    parsed.astimezone(ZoneInfo(context.time_zone)).date()
                    if isinstance(parsed, datetime)
                    else parsed
                )
                return Proposal("calendar", day=day)
            return Proposal("patch", DraftPatch(occurrence=parsed))
        if not context.tracker_id:
            raise Clarification("tracker_required")
        if action == "defaults":
            return Proposal(
                "patch", default_patch(context.metadata, context.tracker_id, context.values)
            )
        if action == "skip":
            if not descriptor or descriptor.kind != "optional":
                raise Clarification("cannot_skip_field")
            return Proposal("patch", DraftPatch(skip_optional=frozenset({descriptor.key})))
        schema = tracker_schema(context.metadata, context.tracker_id)
        field_id = resolve(
            match.entities["detail"].value,
            {item["id"]: item["label"] for item in schema["fields"]},
            context.names(f"{context.tracker_id}:fields"),
        )
        definition = next(item for item in schema["fields"] if item["id"] == field_id)
        return self._field(answer.value, definition, context)

    def _answer(self, text, context):
        descriptor = context.descriptor
        if descriptor.kind == "tracker":
            allowed = set(descriptor.candidates) & set(eligible_trackers(context.metadata))
            key = resolve(
                text,
                {key: context.metadata.trackers[key].get("name", key) for key in allowed},
                context.names("trackers"),
            )
            return Proposal("patch", DraftPatch(tracker_id=key))
        if not context.tracker_id:
            raise Clarification("tracker_required")
        if descriptor.kind == "subject":
            allowed = set(descriptor.candidates) & set(
                eligible_subjects(context.metadata, context.tracker_id)
            )
            key = resolve(
                text,
                {key: context.metadata.subjects[key].get("name", key) for key in allowed},
                context.names("subjects"),
            )
            return Proposal("patch", DraftPatch(subject_id=key))
        # Resolve the authoritative definition instead of trusting a supplied prompt.
        schema = tracker_schema(context.metadata, context.tracker_id)
        definition = next(
            (item for item in schema["fields"] if item["key"] == descriptor.key), None
        )
        if definition is None:
            raise Clarification("unknown_field")
        return self._field(text, definition, context)

    def _field(self, text, definition, context):
        parsed = value(
            text,
            definition,
            self.language,
            context.now,
            context.time_zone,
            context.names(f"{context.tracker_id}:{definition['id']}:options"),
        )
        values = {**context.values, definition["key"]: parsed}
        schema = tracker_schema(context.metadata, context.tracker_id)
        # DraftStore also normalizes values hidden by a correction.
        normalized = normalize_draft_values(schema, values)
        if definition["key"] not in normalized:
            raise Clarification("hidden_field")
        validate_entry_values(normalized, schema, partial=True)
        return Proposal("patch", DraftPatch(values={definition["key"]: parsed}))
