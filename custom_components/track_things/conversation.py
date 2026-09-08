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
from .conversation_adapter import AdapterContext, QuestionAdapter
from .conversation_contract import Clarification, Proposal
from .conversation_language import SENTENCES
from .conversation_questions import questions
from .conversation_responses import MESSAGES, review_speech
from .dialogue import DraftError, DraftMetadata, DraftPatch, DraftStore, SubmissionIntent
from .schema import EntryValueError

# The callback owns refreshing metadata and safe backend submission (issue #17).
# No callback is installed by this increment. It receives only confirmed drafts.
ConfirmedDraftCallback = Callable[[SubmissionIntent], Awaitable[str]]
SessionKey = tuple[str, str | None, str | None, str | None, str]


@dataclass(repr=False)
class Session:
    draft_id: str
    last_speech: str = ""


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([TrackThingsConversation(entry)])


class TrackThingsConversation(ConversationEntity):
    _attr_has_entity_name = True
    _attr_name = "Track Things"

    def __init__(self, entry, *, store=None, confirmed_draft_callback=None):
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_conversation"
        self.drafts = store if store is not None else DraftStore()
        self.confirmed_draft_callback: ConfirmedDraftCallback | None = confirmed_draft_callback
        self._sessions: dict[SessionKey, Session] = {}
        self._adapters = {language: QuestionAdapter(language) for language in SENTENCES}
        # Serialize turns, including a future async submission callback. No task can
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
        expired = set(self.drafts.expire())
        for key, session in tuple(self._sessions.items()):
            if session.draft_id in expired:
                del self._sessions[key]

    async def async_will_remove_from_hass(self):
        self._closed = True
        async with self._turn_lock:
            self.drafts.clear()
            self._sessions.clear()
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
        language = user_input.language.lower().replace("_", "-").split("-")[0]
        conversation_id = user_input.conversation_id or str(uuid4())
        key = (
            conversation_id,
            user_input.context.user_id,
            user_input.device_id,
            user_input.satellite_id,
            language,
        )
        async with self._turn_lock:
            self._expire()
            if language not in self._adapters:
                speech, follow_up = MESSAGES["en"]["start"], False
            elif self._closed:
                speech, follow_up = MESSAGES[language]["unavailable"], False
            else:
                speech, follow_up = await self._turn(key, user_input.text, language)
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(speech)
        return ConversationResult(response, conversation_id, follow_up)

    async def _turn(self, key, text, language):
        words = MESSAGES[language]
        session = self._sessions.get(key)
        try:
            if not self.entry.runtime_data.coordinator.last_update_success:
                return words["unavailable"], False
            if session:
                result = self.drafts.inspect(session.draft_id)
                view = self.drafts.view(session.draft_id)
                metadata = view.metadata
                descriptor = (
                    result.descriptors[0]
                    if result.descriptors and result.state != "review"
                    else None
                )
                context = AdapterContext(
                    metadata,
                    language,
                    dt_util.utcnow(),
                    self.hass.config.time_zone,
                    tracker_id=view.tracker_id,
                    descriptor=descriptor,
                    values=view.values,
                )
            else:
                metadata = await self._metadata()
                context = AdapterContext(
                    metadata, language, dt_util.utcnow(), self.hass.config.time_zone
                )
            proposal = self._adapters[language].parse(text, context)
            if not isinstance(proposal, Proposal) or not isinstance(proposal.patch, DraftPatch):
                raise Clarification("invalid_proposal")
            if proposal.action == "calendar":
                return words["calendar"], bool(session)
            if proposal.action == "create":
                # Validate a replacement before discarding any existing draft.
                draft_id = str(uuid4())
                self.drafts.start(draft_id, metadata, proposal.patch)
                if session:
                    self.drafts.cancel(session.draft_id)
                session = self._sessions[key] = Session(draft_id)
            elif session is None:
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
                if result.state != "review":
                    raise DraftError("review_required")
                if self.confirmed_draft_callback is None:
                    return words["saving"], True
                submission = self.drafts.confirm(session.draft_id, result.revision)
                del self._sessions[key]
                return await self.confirmed_draft_callback(submission), False
            elif proposal.action != "more":
                raise Clarification("invalid_proposal")
            speech = self._prompt(session, language)
            session.last_speech = speech
            return speech, True
        except (
            ApiError,
            Clarification,
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

    def _prompt(self, session, language):
        result = self.drafts.inspect(session.draft_id)
        view = self.drafts.view(session.draft_id)
        if result.state == "review" or not result.descriptors:
            result = self.drafts.review(session.draft_id)
            return review_speech(result, view.metadata, language)
        prompt = questions(result, view.metadata, language)[0].text
        definition = result.descriptors[0].definition
        if definition and definition["type"] in ("text", "textarea"):
            prompt += " " + MESSAGES[language]["text"]
        return prompt
