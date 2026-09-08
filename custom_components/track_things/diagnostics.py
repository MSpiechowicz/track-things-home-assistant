"""Local diagnostics containing only explicitly selected health facts and counts."""

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from . import TrackThingsConfigEntry
from .coordinator import CONF_TRACKER_IDS
from .voice_options import CONF_ALIASES, CONF_DEFAULT_SUBJECT


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TrackThingsConfigEntry
) -> dict[str, Any]:
    """Never serialize config, resources, exceptions, caches, or conversation state.

    Reading this snapshot does not refresh credentials or make any network request.
    An unloaded entry may still reference its old runtime; do not report it as live.
    """
    loaded = entry.state is ConfigEntryState.LOADED
    result: dict[str, Any] = {
        "configuration": {
            "state": entry.state.value,
            "account_configured": bool(entry.data.get("user_id")),
            "workspace_configured": bool(entry.data.get("workspace_id")),
            "local_http_enabled": entry.data.get("allow_local_http") is True,
            "tracker_selection_explicit": CONF_TRACKER_IDS in entry.options,
            "voice_aliases_configured": bool(entry.options.get(CONF_ALIASES)),
            "default_subject_configured": bool(entry.options.get(CONF_DEFAULT_SUBJECT)),
        },
        "runtime": None,
    }
    if not loaded or not hasattr(entry, "runtime_data"):
        return result
    coordinator = entry.runtime_data.coordinator
    snapshot = coordinator.store.snapshot
    refreshed = coordinator.last_successful_refresh
    result["runtime"] = {
        "metadata_available": coordinator.last_update_success,
        "reauth_required": isinstance(coordinator.last_exception, ConfigEntryAuthFailed),
        "last_successful_metadata_refresh": refreshed.isoformat() if refreshed else None,
        "counts": {
            "trackers": len(snapshot.trackers),
            "subjects": len(snapshot.subjects),
            "missing_schemas": len(snapshot.missing_schema_ids),
            "calendar_trackers": len(coordinator.calendar_trackers),
            "voice_trackers": len(coordinator.voice_trackers),
        },
    }
    return result
