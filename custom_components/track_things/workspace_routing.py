"""Explicit workspace scope and deterministic proposal routing."""

import json
from dataclasses import dataclass
from time import monotonic

from homeassistant.config_entries import ConfigEntryState

from .natural_proposal import decode_proposal

CONF_WORKSPACES = "voice_workspace_entries"
CONF_PREFERRED = "voice_preferred_workspace"


def connected(hass, owner):
    """Only explicitly enabled entries from the same backend/account are eligible."""
    selected = owner.options.get(CONF_WORKSPACES, [owner.entry_id])
    return {
        entry.entry_id: entry
        for entry in hass.config_entries.async_entries("track_things")
        if entry.entry_id in selected
        and entry.state == ConfigEntryState.LOADED
        and entry.data["backend_url"] == owner.data["backend_url"]
        and entry.data["user_id"] == owner.data["user_id"]
    }


def unpack(text):
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4]
    if len(text) > 12000:
        raise ValueError("oversized")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("shape")
    workspace = data.pop("workspace_name", None)
    if workspace is not None and (not isinstance(workspace, str) or not workspace.strip()):
        raise ValueError("workspace")
    return data, workspace


def matches(data, workspace, entries, metadata, preferred=None, current=None):
    """Explicit name > unique resource match > configured preference > clarification."""
    candidates = {}
    for entry_id, entry in entries.items():
        if workspace and entry.title.casefold() != workspace.strip().casefold():
            continue
        if current and entry_id != current:
            continue
        try:
            proposal, review = decode_proposal(json.dumps(data), metadata[entry_id])
            if proposal.action == "create" and not proposal.patch.tracker_id:
                continue
            candidates[entry_id] = (proposal, review)
        except ValueError, TypeError, KeyError:
            continue
    if len(candidates) > 1 and not workspace and preferred in candidates:
        return {preferred: candidates[preferred]}
    return candidates


@dataclass
class WorkspaceChoice:
    data: dict
    candidates: tuple[str, ...]
    created: float

    @classmethod
    def new(cls, data, candidates):
        return cls(data, tuple(candidates), monotonic())

    def expired(self):
        return monotonic() - self.created > 300
