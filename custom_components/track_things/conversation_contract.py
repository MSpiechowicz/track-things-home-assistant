"""Shared proposals for local questions and a future experimental model adapter."""

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from .dialogue_models import DraftPatch


@dataclass(frozen=True, repr=False)
class Question:
    kind: str
    text: str
    key: str | None = None
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True, repr=False)
class Proposal:
    """Never a write authorization; the runtime must validate against its draft.

    A confirm proposal requires an explicit user utterance and the runtime's
    current reviewed revision. Model-produced confirmation is not sufficient.
    """

    action: Literal["create", "patch", "calendar", "review", "confirm", "cancel", "repeat", "more"]
    patch: DraftPatch = field(default_factory=DraftPatch)
    day: date | None = None


class Clarification(ValueError):
    def __init__(self, code: str, candidates: tuple[str, ...] = ()) -> None:
        self.code = code
        self.candidates = candidates
        super().__init__(code)
