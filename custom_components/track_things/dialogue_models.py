"""Transport-independent inputs and outputs for ephemeral entry drafts."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from .api_models import EntryCreate, SchemaVersion, Subject, Tracker


@dataclass(frozen=True, repr=False)
class DraftMetadata:
    """An adapter supplies authorized resources and resolved immutable schemas."""

    workspace_id: str
    trackers: dict[str, Tracker]
    subjects: dict[str, Subject]
    schemas: dict[str, SchemaVersion]


@dataclass(frozen=True, repr=False)
class DraftPatch:
    """IDs are explicit choices; values use schema keys, never labels.

    occurrence=None leaves the current occurrence unchanged; reset_occurrence
    explicitly selects now. A date is an inclusive one-day all-day period.
    """

    tracker_id: str | None = None
    subject_id: str | None = None
    values: dict[str, Any] = field(default_factory=dict)
    remove: frozenset[str] = frozenset()
    accept_defaults: frozenset[str] = frozenset()
    skip_optional: frozenset[str] = frozenset()
    occurrence: date | datetime | None = None
    reset_occurrence: bool = False


@dataclass(frozen=True, repr=False)
class Descriptor:
    """Semantic prompts; adapters own wording, translations, and ordering."""

    kind: Literal["tracker", "subject", "required", "optional"]
    candidates: tuple[str, ...] = ()
    key: str | None = None
    definition: dict[str, Any] | None = None


@dataclass(frozen=True, repr=False)
class DraftResult:
    draft_id: str
    revision: str
    state: Literal["collecting", "ready", "review"]
    descriptors: tuple[Descriptor, ...]
    payload: EntryCreate | None = None


@dataclass(frozen=True, repr=False)
class DraftView:
    """Detached parsing context; callers cannot mutate the stored draft."""

    metadata: DraftMetadata
    tracker_id: str | None
    values: dict[str, Any]


@dataclass(frozen=True, repr=False)
class SubmissionIntent:
    """A single confirmed handoff. The consumer still owns safe backend saving."""

    draft_id: str
    revision: str
    workspace_id: str
    payload: EntryCreate


class DraftError(ValueError):
    """Stable recovery code with no user content in the exception."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
