"""One read-only recorded-entry calendar per configured workspace."""

from datetime import UTC, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TrackThingsConfigEntry
from .api_errors import ApiError, AuthenticationError, PermissionDeniedError

SCAN_INTERVAL = timedelta(seconds=60)


async def async_setup_entry(
    hass: HomeAssistant, entry: TrackThingsConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([WorkspaceCalendar(entry)], update_before_add=True)


class WorkspaceCalendar(CalendarEntity):
    _attr_supported_features = 0
    _attr_icon = "mdi:calendar"

    def __init__(self, entry: TrackThingsConfigEntry) -> None:
        self._entry = entry
        self._coordinator = entry.runtime_data.coordinator
        self._query = entry.runtime_data.calendar
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_name = entry.title
        self._events: list[CalendarEvent] = []
        self._read_ok = False

    @property
    def available(self) -> bool:
        return self._read_ok and self._coordinator.last_update_success

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.utcnow()
        return next(
            (event for event in self._events if event.end_datetime_local.astimezone(UTC) > now),
            None,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._coordinator.async_add_listener(self._metadata_updated))

    @callback
    def _metadata_updated(self) -> None:
        self._query.invalidate()
        self._events = []
        self._read_ok = False
        self.async_write_ha_state()
        self.async_schedule_update_ha_state(force_refresh=True)

    async def async_update(self) -> None:
        """Fetch ongoing and future records; properties only inspect memory.

        The backend has no next-event endpoint. Read the remaining supported date
        domain so a sparse calendar does not lose its next event at a lookahead cutoff.
        Past overlapping periods are included by the backend's date-range filter.
        """
        try:
            self._events = await self.async_get_events(
                self.hass,
                dt_util.start_of_local_day(),
                datetime(9999, 12, 30, tzinfo=dt_util.DEFAULT_TIME_ZONE),
            )
        except HomeAssistantError:
            self._events = []

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        try:
            if not self._coordinator.last_update_success:
                raise HomeAssistantError("Track Things metadata is unavailable")
            events = await self._query.async_get_events(start_date, end_date, hass.config.time_zone)
        except (ApiError, ValueError, HomeAssistantError) as err:
            self._query.invalidate()
            self._read_ok = False
            self._events = []
            if isinstance(err, (AuthenticationError, PermissionDeniedError)):
                self._entry.async_start_reauth(hass)
            if self.entity_id is not None:
                self.async_write_ha_state()
            raise HomeAssistantError("Track Things calendar is temporarily unavailable") from err
        recovered = not self._read_ok
        self._read_ok = True
        if recovered and self.entity_id is not None:
            self.async_write_ha_state()
        return events
