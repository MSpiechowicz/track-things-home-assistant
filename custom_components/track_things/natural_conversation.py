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

_LOGGER = logging.getLogger(__name__)


class NaturalConversation(TrackThingsConversation):
    """Separate, explicitly selected POC agent with its own isolated drafts."""

    natural_review = True
    _attr_name = "Track Things natural (Gemini POC)"

    def __init__(self, entry):
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_natural_conversation"
        self._natural_lock = asyncio.Lock()

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
            session = self._sessions.get(key)
            literal = control(user_input.text)
            # Original confirmation is never generated or paraphrased by Gemini.
            if literal in {"confirm", "save", "cancel", "repeat", "review"} or (
                session and session.pending
            ):
                return await super().async_process(
                    replace(
                        user_input,
                        text=("/" if user_input.text.strip().startswith("/") else "") + literal,
                    )
                )
            stage = "interpreter_setup"
            try:
                gemini_id = self._gemini()
                stage = "metadata"
                metadata = await self._metadata()
                catalog = {
                    "trackers": metadata.trackers,
                    "subjects": metadata.subjects,
                    "schemas": metadata.schemas,
                    "current_question": session.last_speech if session else None,
                    "utterance": user_input.text,
                    "now": dt_util.now().isoformat(),
                    "timezone": self.hass.config.time_zone,
                    "draft": None
                    if session is None
                    else {
                        "tracker_id": self.drafts.view(session.draft_id).tracker_id,
                        "values": self.drafts.view(session.draft_id).values,
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
                proposal, request_review = decode_proposal(
                    result.response.speech["plain"]["speech"],
                    metadata,
                    self.drafts.view(session.draft_id).tracker_id if session else None,
                )
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
            result = await self._process(user_input, proposal)
            spoken = result.response.speech["plain"]["speech"]
            if request_review and not spoken.startswith(MESSAGES["en"]["recovery"]):
                result = await self._process(user_input, Proposal("review"))
            return result
