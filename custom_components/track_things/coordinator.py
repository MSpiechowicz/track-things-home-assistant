"""Five-minute metadata polling and cached read/write tracker selections."""

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_errors import ApiError, AuthenticationError, PermissionDeniedError
from .api_models import Tracker
from .auth import AuthenticatedApi
from .metadata import MetadataSnapshot, MetadataStore

if TYPE_CHECKING:
    from .calendar_query import CalendarQuery

CONF_TRACKER_IDS = "tracker_ids"


class MetadataCoordinator(DataUpdateCoordinator[MetadataSnapshot]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: AuthenticatedApi) -> None:
        super().__init__(
            hass,
            logging.getLogger(__name__),
            name="Track Things metadata",
            config_entry=entry,
            update_interval=timedelta(minutes=5),
        )
        self.store = MetadataStore(api, entry.data["workspace_id"])
        self.entry = entry

    async def _async_update_data(self) -> MetadataSnapshot:
        try:
            return await self.store.async_refresh()
        except (AuthenticationError, PermissionDeniedError) as err:
            raise ConfigEntryAuthFailed("Track Things access must be restored") from err
        except ApiError as err:
            raise UpdateFailed("Track Things metadata is temporarily unavailable") from err

    @callback
    def async_entries_changed(self) -> None:
        """Notify cache subscribers after an acknowledged write, without a platform dependency."""
        self.async_update_listeners()

    @property
    def calendar_trackers(self) -> dict[str, Tracker]:
        """Absent selection means all; an explicit empty selection means none."""
        trackers = self.store.snapshot.trackers
        selected = self.entry.options.get(CONF_TRACKER_IDS)
        return {key: item for key, item in trackers.items() if selected is None or key in selected}

    @property
    def voice_trackers(self) -> dict[str, Tracker]:
        """Only selected active manual trackers with a resolvable schema can write."""
        return {
            key: item
            for key, item in self.calendar_trackers.items()
            if item["kind"] == "manual"
            and item["archivedAt"] is None
            and item["currentSchemaVersionId"] is not None
            and item["currentSchemaVersionId"] not in self.store.snapshot.missing_schema_ids
        }


@dataclass
class TrackThingsRuntime:
    api: AuthenticatedApi
    coordinator: MetadataCoordinator
    calendar: CalendarQuery
