"""Engine-independent, in-memory drafts with revision-bound explicit confirmation."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from time import monotonic
from typing import Any
from uuid import uuid4

from .api_models import EntryCreate
from .dialogue_models import (
    Descriptor,
    DraftError,
    DraftMetadata,
    DraftPatch,
    DraftResult,
    SubmissionIntent,
)
from .dialogue_rules import (
    eligible_subjects,
    eligible_trackers,
    field_descriptors,
    occurrence_payload,
    patch_values,
    tracker_schema,
)
from .schema import validate_entry_values

__all__ = [
    "Descriptor",
    "DraftError",
    "DraftMetadata",
    "DraftPatch",
    "DraftResult",
    "DraftStore",
    "SubmissionIntent",
]


@dataclass(repr=False)
class _Draft:
    metadata: DraftMetadata
    occurrence: date | datetime
    touched: float
    revision: str = field(default_factory=lambda: str(uuid4()))
    tracker_id: str | None = None
    subject_id: str | None = None
    values: dict[str, Any] = field(default_factory=dict)
    skipped: set[str] = field(default_factory=set)
    reviewed: EntryCreate | None = None


class DraftStore:
    """Synchronous transitions; no persistence, network, model, or HA collaborators.

    IDs must be scoped by the runtime to its authenticated conversation context.
    Call expire periodically for physical idle cleanup, and clear on unload.
    Every lookup also expires stale drafts. Returned data never aliases storage.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        idle_clock: Callable[[], float] = monotonic,
    ) -> None:
        self._clock = clock
        self._idle_clock = idle_clock
        self._drafts: dict[str, _Draft] = {}

    def expire(self) -> tuple[str, ...]:
        now = self._idle_clock()
        expired = tuple(key for key, draft in self._drafts.items() if now - draft.touched >= 300)
        for key in expired:
            del self._drafts[key]
        return expired

    def clear(self) -> None:
        self._drafts.clear()

    def _get(self, draft_id: str) -> _Draft:
        self.expire()
        if draft_id not in self._drafts:
            raise DraftError("draft_unavailable")
        return self._drafts[draft_id]

    def start(
        self, draft_id: str, metadata: DraftMetadata, patch: DraftPatch | None = None
    ) -> DraftResult:
        self.expire()
        if not draft_id or draft_id in self._drafts:
            raise DraftError("draft_id_unavailable")
        occurrence = self._clock()
        occurrence_payload(occurrence)
        draft = _Draft(deepcopy(metadata), occurrence, self._idle_clock())
        self._apply(draft, patch or DraftPatch())
        self._drafts[draft_id] = draft
        return self._result(draft_id, draft)

    def update(self, draft_id: str, patch: DraftPatch) -> DraftResult:
        # Invalid proposals are atomic: keep the preceding values and review intact.
        draft = deepcopy(self._get(draft_id))
        self._apply(draft, patch)
        draft.revision = str(uuid4())
        draft.reviewed = None
        draft.touched = self._idle_clock()
        self._drafts[draft_id] = draft
        return self._result(draft_id, draft)

    def _apply(self, draft: _Draft, patch: DraftPatch) -> None:
        if patch.tracker_id is not None and patch.tracker_id != draft.tracker_id:
            tracker_schema(draft.metadata, patch.tracker_id)
            draft.tracker_id = patch.tracker_id
            draft.subject_id = None
            draft.values = {}
            draft.skipped = set()
        if patch.reset_occurrence and patch.occurrence is not None:
            raise DraftError("conflicting_occurrence")
        if patch.reset_occurrence or patch.occurrence is not None:
            draft.occurrence = self._clock() if patch.reset_occurrence else patch.occurrence
            occurrence_payload(draft.occurrence)
        if draft.tracker_id is None:
            if patch.subject_id is not None or any(
                (patch.values, patch.remove, patch.accept_defaults, patch.skip_optional)
            ):
                raise DraftError("tracker_required")
            return
        schema = tracker_schema(draft.metadata, draft.tracker_id)
        subjects = eligible_subjects(draft.metadata, draft.tracker_id)
        if patch.subject_id is not None:
            if patch.subject_id not in subjects:
                raise DraftError("subject_unavailable")
            draft.subject_id = patch.subject_id
        elif draft.subject_id is None and len(subjects) == 1:
            draft.subject_id = subjects[0]
        draft.values, draft.skipped = patch_values(schema, draft.values, draft.skipped, patch)

    def _result(self, draft_id: str, draft: _Draft) -> DraftResult:
        descriptors = []
        if draft.tracker_id is None:
            descriptors.append(Descriptor("tracker", eligible_trackers(draft.metadata)))
        else:
            if draft.subject_id is None:
                descriptors.append(
                    Descriptor("subject", eligible_subjects(draft.metadata, draft.tracker_id))
                )
            descriptors.extend(
                field_descriptors(
                    tracker_schema(draft.metadata, draft.tracker_id), draft.values, draft.skipped
                )
            )
        state = "collecting" if any(d.kind != "optional" for d in descriptors) else "ready"
        return DraftResult(
            draft_id,
            draft.revision,
            "review" if draft.reviewed is not None else state,
            tuple(descriptors),
            deepcopy(draft.reviewed),
        )

    def inspect(self, draft_id: str) -> DraftResult:
        """Read without extending inactivity (polling must not keep drafts alive)."""
        return self._result(draft_id, self._get(draft_id))

    def review(self, draft_id: str) -> DraftResult:
        """Explicit review may omit unanswered optional fields, never required ones."""
        draft = self._get(draft_id)
        if self._result(draft_id, draft).state == "collecting":
            raise DraftError("draft_incomplete")
        validate_entry_values(draft.values, tracker_schema(draft.metadata, draft.tracker_id))
        draft.reviewed = {
            "trackerId": draft.tracker_id,
            "subjectId": draft.subject_id,
            "expectedSchemaVersionId": draft.metadata.trackers[draft.tracker_id][
                "currentSchemaVersionId"
            ],
            "values": deepcopy(draft.values),
            "source": "manual",
            **occurrence_payload(draft.occurrence),
        }
        draft.touched = self._idle_clock()
        return self._result(draft_id, draft)

    def confirm(self, draft_id: str, revision: str) -> SubmissionIntent:
        draft = self._get(draft_id)
        if draft.reviewed is None or revision != draft.revision:
            raise DraftError("review_required")
        intent = SubmissionIntent(
            draft_id, revision, draft.metadata.workspace_id, deepcopy(draft.reviewed)
        )
        del self._drafts[draft_id]
        return intent

    def cancel(self, draft_id: str) -> None:
        self._get(draft_id)
        del self._drafts[draft_id]
