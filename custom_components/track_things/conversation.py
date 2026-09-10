"""Local Assist agent with ephemeral, authenticated-context-scoped drafts."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from homeassistant.components.conversation import (
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.core import callback
from homeassistant.helpers import intent
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .api_errors import ApiError
from .calendar_conversation import MESSAGES as CALENDAR_MESSAGES
from .calendar_conversation import CalendarConversation
from .calendar_intents import calendar_proposal
from .conversation_adapter import AdapterContext, QuestionAdapter
from .conversation_contract import Clarification, Proposal
from .conversation_language import SENTENCES
from .conversation_questions import questions
from .conversation_responses import MESSAGES, review_speech
from .dialogue import DraftError, DraftMetadata, DraftPatch, DraftStore, SubmissionIntent
from .schema import EntryValueError
from .voice_creation import PendingWrite, VoiceEntryWriter
from .voice_options import alias_mapping, catalog, current_metadata, default_subject
from .voice_responses import VOICE_MESSAGES

# Optional callback seam for alternate runtimes. Production uses VoiceEntryWriter.
ConfirmedDraftCallback = Callable[[SubmissionIntent], Awaitable[str]]
SessionKey = tuple[str, str | None, str | None, str | None, str]


@dataclass(repr=False)
class Session:
    draft_id: str
    last_speech: str = ""
    reviewed_revision: str | None = None
    pending: PendingWrite | None = None


async def async_setup_entry(hass, entry, async_add_entities):
    from .natural_conversation import NaturalConversation  # noqa: PLC0415

    async_add_entities([TrackThingsConversation(entry), NaturalConversation(entry)])


class TrackThingsConversation(ConversationEntity):
    _attr_has_entity_name = True
    _attr_name = "Track Things"

    def __init__(self, entry, *, store=None, confirmed_draft_callback=None):
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_conversation"
        self.drafts = store if store is not None else DraftStore()
        self.confirmed_draft_callback: ConfirmedDraftCallback | None = confirmed_draft_callback
        self.writer = VoiceEntryWriter(self)
        self.calendar = CalendarConversation(self)
        self._sessions: dict[SessionKey, Session] = {}
        self._adapters = {language: QuestionAdapter(language) for language in SENTENCES}
        # Serialize turns, including async submissions. No task can
        # observe a half-applied proposal or confirm the same draft twice.
        self._turn_lock = asyncio.Lock()
        self._closed = False

    @property
    def supported_languages(self):
        return list(SENTENCES)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_interval(self.hass, self._expire, timedelta(seconds=30))
        )

    @callback
    def _expire(self, now=None):
        self.calendar.expire()
        expired = set(self.drafts.expire())
        for key, session in tuple(self._sessions.items()):
            if session.draft_id in expired:
                del self._sessions[key]

    async def async_will_remove_from_hass(self):
        self._closed = True
        async with self._turn_lock:
            self.drafts.clear()
            self._sessions.clear()
            self.calendar.sessions.clear()
        await super().async_will_remove_from_hass()

    async def _metadata(self):
        coordinator = self.entry.runtime_data.coordinator
        if not coordinator.last_update_success:
            raise Clarification("unavailable")
        trackers = coordinator.voice_trackers
        schemas = {}
        for tracker in trackers.values():
            version = tracker["currentSchemaVersionId"]
            schemas[version] = await coordinator.store.async_schema(tracker["id"], version)
        return DraftMetadata(
            self.entry.data["workspace_id"], trackers, coordinator.store.snapshot.subjects, schemas
        )

    async def async_process(self, user_input: ConversationInput) -> ConversationResult:
        """Own session history instead of retaining HA chat logs containing drafts.

        Config entries own separate entity instances. A caller-supplied conversation
        ID alone never provides access to another user/device/satellite's draft.
        """
        return await self._process(user_input)

    async def _process(self, user_input, proposal=None):
        language = user_input.language.lower().replace("_", "-").split("-")[0]
        conversation_id = user_input.conversation_id or str(uuid4())
        key = (
            conversation_id,
            user_input.context.user_id,
            user_input.device_id,
            user_input.satellite_id,
            language,
        )
        # Bind confirmation to the review visible when this turn arrived, not
        # a new review produced by another turn while this one waits for the lock.
        observed_session = self._sessions.get(key)
        confirmation_revision = observed_session.reviewed_revision if observed_session else None
        async with self._turn_lock:
            self._expire()
            if language not in self._adapters:
                speech, follow_up = MESSAGES["en"]["start"], False
            elif self._closed:
                speech, follow_up = MESSAGES[language]["unavailable"], False
            else:
                speech, follow_up = await self._turn(
                    key, user_input.text, language, confirmation_revision, proposal
                )
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(speech)
        return ConversationResult(response, conversation_id, follow_up)

    async def _turn(self, key, text, language, confirmation_revision, supplied_proposal=None):
        words = MESSAGES[language]
        session = self._sessions.get(key)
        try:
            if session and session.pending:
                # A possibly committed payload is immutable. Only literal user
                # confirmation may retry it; proposals cannot mutate or replace it.
                command = text.strip().casefold().removeprefix("/")
                if command in SENTENCES[language]["confirm"]:
                    return await self._save(key, session, language)
                if command in SENTENCES[language]["cancel"]:
                    self.drafts.cancel(session.draft_id)
                    del self._sessions[key]
                    return VOICE_MESSAGES[language]["abandoned"], False
                return VOICE_MESSAGES[language]["uncertain"], True
            calendar_reply = (
                await self.calendar.follow_up(key, text, language)
                if supplied_proposal is None
                else None
            )
            if calendar_reply is not None:
                return calendar_reply
            if not self.entry.runtime_data.coordinator.last_update_success:
                return words["unavailable"], False
            if session is None and supplied_proposal is None:
                # Read-only queries must not depend on current write schemas.
                context = AdapterContext(
                    DraftMetadata(self.entry.data["workspace_id"], {}, {}, {}),
                    language,
                    dt_util.utcnow(),
                    self.hass.config.time_zone,
                )
                calendar = calendar_proposal(text.removeprefix("/"), context)
                if calendar is not None:
                    return await self.calendar.start(key, calendar, language)
            live_metadata = await current_metadata(self.entry)
            aliases = alias_mapping(self.entry.options, catalog(live_metadata))
            if session:
                result = self.drafts.inspect(session.draft_id)
                view = self.drafts.view(session.draft_id)
                metadata = view.metadata
                descriptor = (
                    result.descriptors[0]
                    if result.descriptors and result.state != "review"
                    else None
                )
                if key in self.calendar.sessions:
                    descriptor = None
                context = AdapterContext(
                    metadata,
                    language,
                    dt_util.utcnow(),
                    self.hass.config.time_zone,
                    tracker_id=view.tracker_id,
                    descriptor=descriptor,
                    values=view.values,
                    aliases=aliases,
                    default_subject_id=default_subject(
                        self.entry.options,
                        live_metadata,
                        view.tracker_id
                        if view.tracker_id in self.entry.runtime_data.coordinator.voice_trackers
                        else None,
                    ),
                )
            else:
                metadata = await self._metadata()
                context = AdapterContext(
                    metadata,
                    language,
                    dt_util.utcnow(),
                    self.hass.config.time_zone,
                    aliases=aliases,
                )
            proposal = supplied_proposal or self._adapters[language].parse(text, context)
            if not isinstance(proposal, Proposal) or not isinstance(proposal.patch, DraftPatch):
                raise Clarification("invalid_proposal")
            if proposal.action == "calendar":
                return await self.calendar.start(key, proposal, language)
            if proposal.action == "create":
                self.calendar.sessions.pop(key, None)
                # Validate a replacement before discarding any existing draft.
                draft_id = str(uuid4())
                self.drafts.start(draft_id, metadata, proposal.patch)
                if session:
                    self.drafts.cancel(session.draft_id)
                session = self._sessions[key] = Session(draft_id)
            elif session is None:
                if proposal.action == "more":
                    return CALENDAR_MESSAGES[language]["missing"], False
                return words["start"], False
            elif proposal.action == "cancel":
                self.drafts.cancel(session.draft_id)
                del self._sessions[key]
                return words["cancel"], False
            elif proposal.action == "repeat":
                return session.last_speech, True
            elif proposal.action == "patch":
                self.drafts.update(session.draft_id, proposal.patch)
            elif proposal.action == "review":
                self.drafts.review(session.draft_id)
            elif proposal.action == "confirm":
                result = self.drafts.inspect(session.draft_id)
                if (
                    result.state != "review"
                    or session.reviewed_revision != result.revision
                    or confirmation_revision != result.revision
                    or text.strip().casefold().removeprefix("/")
                    not in SENTENCES[language]["confirm"]
                ):
                    raise DraftError("review_required")
                if self.confirmed_draft_callback is None:
                    if self.writer is not None:
                        return await self._save(key, session, language)
                    return words["saving"], True
                submission = self.drafts.confirm(session.draft_id, result.revision)
                del self._sessions[key]
                return await self.confirmed_draft_callback(submission), False
            elif proposal.action != "more":
                raise Clarification("invalid_proposal")
            speech = self._prompt(session, language)
            session.last_speech = speech
            return speech, True
        except Clarification as error:
            if error.code == "ambiguous_name" and error.candidates:
                if session is None and all(key in metadata.trackers for key in error.candidates):
                    draft_id = str(uuid4())
                    self.drafts.start(draft_id, metadata, DraftPatch())
                    session = self._sessions[key] = Session(draft_id)
                choices = ", ".join(error.candidates)
                if session:
                    session.last_speech = self._prompt(session, language)
                    return words["recovery"] + " " + choices + ". " + session.last_speech, True
            if session:
                return words["recovery"] + " " + session.last_speech, True
            return words["recovery"] + " " + words["start"], False
        except (
            ApiError,
            DraftError,
            EntryValueError,
            ValueError,
            TypeError,
            KeyError,
        ):
            # Never speak raw exceptions, schema payloads, credentials or model data.
            if session:
                try:
                    self.drafts.inspect(session.draft_id)
                except DraftError:
                    self._sessions.pop(key, None)
                    return words["start"], False
                return words["recovery"] + " " + session.last_speech, True
            return words["recovery"] + " " + words["start"], False

    async def _save(self, key, session, language):
        outcome = await self.writer.confirm(session)
        speech = VOICE_MESSAGES[language][outcome]
        if outcome == "saved":
            self._sessions.pop(key, None)
            return speech, False
        if outcome in ("changed", "rejected"):
            speech += " " + self._prompt(session, language)
        session.last_speech = speech
        return speech, True

    def _prompt(self, session, language):
        result = self.drafts.inspect(session.draft_id)
        view = self.drafts.view(session.draft_id)
        if result.state == "review" or not result.descriptors:
            result = self.drafts.review(session.draft_id)
            session.reviewed_revision = result.revision
            return review_speech(
                result,
                view.metadata,
                language,
                self.hass.config.time_zone if getattr(self, "natural_review", False) else None,
            )
        prompt = questions(result, view.metadata, language)[0].text
        definition = result.descriptors[0].definition
        if definition and definition["type"] in ("text", "textarea"):
            prompt += " " + MESSAGES[language]["text"]
        return prompt
