"""Revision-bound voice writes and ephemeral recovery of uncertain submissions."""

from copy import deepcopy
from dataclasses import dataclass

from homeassistant.exceptions import ServiceValidationError

from .api_errors import (
    ApiError,
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from .create_entry import async_prepare_entry, async_write_entry
from .dialogue import DraftError, SubmissionIntent
from .schema import EntryValueError, SchemaUnavailableError


@dataclass(repr=False)
class PendingWrite:
    submission: SubmissionIntent


class VoiceEntryWriter:
    """Called under the agent's turn lock; never retries in the background."""

    def __init__(self, agent):
        self.agent = agent

    async def _fresh(self):
        await self.agent.entry.runtime_data.coordinator.store.async_refresh()
        return await self.agent._metadata()

    async def _review_again(self, session):
        # Clear the confirmation before awaiting anything: recovery failure must
        # never leave an old confirmation usable for a new schema.
        session.pending = None
        current = self.agent.drafts.view(session.draft_id).metadata
        self.agent.drafts.refresh(session.draft_id, current)
        metadata = await self._fresh()
        self.agent.drafts.refresh(session.draft_id, metadata)
        return "changed"

    async def confirm(self, session):
        agent = self.agent
        entry = agent.entry
        try:
            if session.pending is None:
                result = agent.drafts.inspect(session.draft_id)
                if result.state != "review" or session.reviewed_revision != result.revision:
                    raise DraftError("review_required")
                metadata = await self._fresh()
                if metadata != agent.drafts.view(session.draft_id).metadata:
                    agent.drafts.refresh(session.draft_id, metadata)
                    return "changed"
                prepared, tracker, subject, schema = await async_prepare_entry(
                    entry, result.payload
                )
                if (
                    tracker != metadata.trackers[tracker["id"]]
                    or subject != metadata.subjects[subject["id"]]
                    or schema != metadata.schemas.get(schema["id"])
                ):
                    return await self._review_again(session)
                # Recheck expiry/revision after HTTP awaits, before granting permission.
                submission = agent.drafts.confirm(
                    session.draft_id, session.reviewed_revision, consume=False
                )
                if prepared != submission.payload:
                    return await self._review_again(session)
                session.pending = PendingWrite(submission)
            submission = session.pending.submission
            if agent._closed:
                raise DraftError("draft_unavailable")
            await async_write_entry(entry, deepcopy(submission.payload), submission.revision)
        except AuthenticationError:
            entry.async_start_reauth(agent.hass)
            return "auth"
        except PermissionDeniedError:
            return "denied"
        except ConflictError as err:
            if err.code == "idempotency_conflict":
                return "uncertain"
            return await self._review_again(session)
        except ServiceValidationError, EntryValueError, SchemaUnavailableError, NotFoundError:
            return await self._review_again(session)
        except ApiError as err:
            if session.pending is None:
                return "unavailable"
            if err.status == 400:
                session.pending = None
                agent.drafts.refresh(session.draft_id, agent.drafts.view(session.draft_id).metadata)
                return "rejected"
            return "uncertain"
        # The draft may have expired during the request. Success remains acknowledged.
        try:
            agent.drafts.cancel(session.draft_id)
        except DraftError:
            pass
        session.pending = None
        return "saved"
