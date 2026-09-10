"""Opt-in Gemini wording adapter; deterministic engine alone owns writes."""

import asyncio
import json
import logging
from dataclasses import replace
from uuid import uuid4

from homeassistant.components import conversation
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import intent
from homeassistant.util import dt as dt_util

from .api_errors import ApiError
from .conversation import TrackThingsConversation
from .conversation_contract import Clarification, Proposal
from .conversation_responses import MESSAGES
from .natural_proposal import INSTRUCTIONS, control, decode_proposal
from .workspace_routing import CONF_PREFERRED, WorkspaceChoice, connected, matches, unpack

_LOGGER = logging.getLogger(__name__)


class NaturalConversation(TrackThingsConversation):
    """Separate, explicitly selected POC agent with its own isolated drafts."""

    natural_review = True
    _attr_name = "Track Things natural (Gemini POC)"

    def __init__(self, entry):
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_natural_conversation"
        self._natural_lock = asyncio.Lock()
        self._workspace_engines = {}
        self._workspace_routes = {}
        self._workspace_choices = {}

    def _engine(self, entry):
        if entry.entry_id == self.entry.entry_id:
            return self
        if entry.entry_id not in self._workspace_engines:
            engine = TrackThingsConversation(entry)
            engine.hass = self.hass
            engine.natural_review = True
            self._workspace_engines[entry.entry_id] = engine
        return self._workspace_engines[entry.entry_id]

    def _expire(self, now=None):
        super()._expire(now)
        for engine in self._workspace_engines.values():
            engine._expire(now)
        for key, entry_id in tuple(self._workspace_routes.items()):
            engine = (
                self if entry_id == self.entry.entry_id else self._workspace_engines.get(entry_id)
            )
            if engine is None or (
                key not in engine._sessions and key not in engine.calendar.sessions
            ):
                del self._workspace_routes[key]
        for key, choice in tuple(self._workspace_choices.items()):
            if choice.expired():
                del self._workspace_choices[key]

    async def async_will_remove_from_hass(self):
        await super().async_will_remove_from_hass()
        for engine in self._workspace_engines.values():
            engine._closed = True
            engine.drafts.clear()
            engine._sessions.clear()
            engine.calendar.sessions.clear()
        self._workspace_routes.clear()
        self._workspace_choices.clear()

    async def _apply_workspace(self, user_input, key, entry, proposal, review):
        engine = self._engine(entry)
        result = await engine._process(user_input, proposal)
        spoken = result.response.speech["plain"]["speech"]
        if review and not spoken.startswith(MESSAGES["en"]["recovery"]):
            result = await engine._process(user_input, Proposal("review"))
        if key in engine._sessions or key in engine.calendar.sessions:
            self._workspace_routes[key] = entry.entry_id
        else:
            self._workspace_routes.pop(key, None)
        result.response.async_set_speech(
            f"Workspace {entry.title}. " + result.response.speech["plain"]["speech"]
        )
        return result

    @property
    def supported_languages(self):
        return ["en"]

    def _gemini(self):
        """Require one deliberately named, tool-free Gemini agent; never guess."""
        candidates = []
        for entity_id in self.hass.states.async_entity_ids("conversation"):
            agent = conversation.async_get_agent(self.hass, entity_id)
            entry = getattr(agent, "entry", None)
            if not entry or entry.domain != "google_generative_ai_conversation":
                continue
            state = self.hass.states.get(entity_id)
            if state.name.strip().casefold() != "track things interpreter":
                continue
            subentry = getattr(agent, "subentry", None)
            if subentry is None:
                continue
            settings = subentry.data
            # A normalization call must not execute arbitrary HA/Google tools.
            if settings.get("llm_hass_api") or settings.get("enable_google_search_tool"):
                continue
            candidates.append(entity_id)
        if len(candidates) != 1:
            raise ValueError("interpreter_not_configured")
        return candidates[0]

    def _reply(self, user_input, message, follow_up=False):
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(message)
        return conversation.ConversationResult(response, user_input.conversation_id, follow_up)

    async def async_process(self, user_input):
        # English-only first POC; preserve original identity, language and session.
        user_input = replace(user_input, conversation_id=user_input.conversation_id or str(uuid4()))
        async with self._natural_lock:
            if user_input.language.lower().split("-")[0] != "en":
                return self._reply(user_input, "This POC currently supports English only.")
            if self._closed:
                return self._reply(user_input, "Track Things is unavailable.")
            self._expire()
            key = (
                user_input.conversation_id,
                user_input.context.user_id,
                user_input.device_id,
                user_input.satellite_id,
                "en",
            )
            entries = connected(self.hass, self.entry)
            current = self._workspace_routes.get(key)
            if current and current not in entries:
                return self._reply(
                    user_input,
                    "The draft workspace is unavailable. Restore its connection before continuing.",
                )
            engine = self._engine(entries[current]) if current else self
            session = engine._sessions.get(key)
            if current and not session and key not in engine.calendar.sessions:
                self._workspace_routes.pop(key, None)
                current = None
                engine = self
            choice = self._workspace_choices.get(key)
            literal = control(user_input.text)
            if choice:
                if literal == "cancel":
                    del self._workspace_choices[key]
                    return self._reply(user_input, "Cancelled. Nothing was saved.")
                selected = [
                    entry
                    for entry_id, entry in entries.items()
                    if entry_id in choice.candidates and entry.title.casefold() == literal
                ]
                if len(selected) != 1:
                    return self._reply(
                        user_input,
                        "Choose a workspace: "
                        + ", ".join(entries[k].title for k in choice.candidates if k in entries),
                        True,
                    )
                try:
                    metadata = await self._engine(selected[0])._metadata()
                    proposal, review = decode_proposal(json.dumps(choice.data), metadata)
                except ApiError, Clarification, ValueError, KeyError, TypeError:
                    del self._workspace_choices[key]
                    return self._reply(
                        user_input, "The workspace or tracker changed. Please start again."
                    )
                del self._workspace_choices[key]
                return await self._apply_workspace(user_input, key, selected[0], proposal, review)
            # Original confirmation is never generated or paraphrased by Gemini.
            if literal in {"confirm", "save", "cancel", "repeat", "review"} or (
                session and session.pending
            ):
                normalized = replace(
                    user_input,
                    text=("/" if user_input.text.strip().startswith("/") else "") + literal,
                )
                result = await engine._process(normalized)
                if current and key not in engine._sessions and key not in engine.calendar.sessions:
                    self._workspace_routes.pop(key, None)
                if current:
                    result.response.async_set_speech(
                        f"Workspace {entries[current].title}. "
                        + result.response.speech["plain"]["speech"]
                    )
                return result
            stage = "interpreter_setup"
            try:
                gemini_id = self._gemini()
                stage = "metadata"
                if not entries:
                    raise ValueError("no_workspaces")
                catalogs = {
                    entry_id: await self._engine(entry)._metadata()
                    for entry_id, entry in entries.items()
                    if not current or entry_id == current
                }
                metadata = catalogs[current] if current else next(iter(catalogs.values()))
                catalog = {
                    "workspaces": [
                        {
                            "workspace_name": entries[k].title,
                            "trackers": m.trackers,
                            "subjects": m.subjects,
                            "schemas": m.schemas,
                        }
                        for k, m in catalogs.items()
                    ],
                    "active_workspace": entries[current].title if current else None,
                    "trackers": metadata.trackers if len(catalogs) == 1 else {},
                    "subjects": metadata.subjects if len(catalogs) == 1 else {},
                    "schemas": metadata.schemas if len(catalogs) == 1 else {},
                    "current_question": session.last_speech if session else None,
                    "utterance": user_input.text,
                    "now": dt_util.now().isoformat(),
                    "timezone": self.hass.config.time_zone,
                    "draft": None
                    if session is None
                    else {
                        "tracker_id": engine.drafts.view(session.draft_id).tracker_id,
                        "values": engine.drafts.view(session.draft_id).values,
                    },
                }
                stage = "provider"
                async with asyncio.timeout(45):
                    result = await conversation.async_converse(
                        self.hass,
                        agent_id=gemini_id,
                        text=INSTRUCTIONS + "\nINPUT DATA:\n" + json.dumps(catalog),
                        conversation_id=None,
                        context=user_input.context,
                        device_id=user_input.device_id,
                        language="en",
                    )
                if result.response.error_code:
                    raise ValueError("model_error")
                stage = "proposal"
                data, workspace = unpack(result.response.speech["plain"]["speech"])
                if current:
                    if workspace and workspace.casefold() != entries[current].title.casefold():
                        return self._reply(
                            user_input, "Cancel the current draft before changing workspace.", True
                        )
                    proposal, request_review = decode_proposal(
                        json.dumps(data),
                        metadata,
                        engine.drafts.view(session.draft_id).tracker_id if session else None,
                    )
                    selected_entry = entries[current]
                else:
                    decode_proposal(json.dumps(data))  # Validate structure before routing.
                    candidates = matches(
                        data, workspace, entries, catalogs, self.entry.options.get(CONF_PREFERRED)
                    )
                    if not candidates:
                        raise ValueError("clarify")
                    if len(candidates) > 1:
                        self._workspace_choices[key] = WorkspaceChoice.new(data, candidates)
                        return self._reply(
                            user_input,
                            "Which workspace: "
                            + ", ".join(entries[k].title for k in candidates)
                            + "?",
                            True,
                        )
                    selected_id = next(iter(candidates))
                    selected_entry = entries[selected_id]
                    proposal, request_review = candidates[selected_id]
            except (
                ApiError,
                Clarification,
                HomeAssistantError,
                ValueError,
                KeyError,
                TypeError,
                TimeoutError,
            ) as error:
                # Only fixed categories are logged; never model text or user data.
                code = "clarify" if stage == "proposal" and str(error) == "clarify" else stage
                _LOGGER.warning("Natural conversation stopped: %s", code)
                messages = {
                    "interpreter_setup": "Check the Track Things interpreter configuration.",
                    "metadata": "Track Things metadata is unavailable. Please try again later.",
                    "provider": "Gemini is unavailable or timed out. Nothing was saved. Try later.",
                    "proposal": "Gemini returned an invalid response. Nothing was saved.",
                    "clarify": "I could not match that request to an available tracker or subject. "
                    "Please check the tracker name and who it is assigned to.",
                }
                return self._reply(user_input, messages[code], bool(session))
            return await self._apply_workspace(
                user_input, key, selected_entry, proposal, request_review
            )
