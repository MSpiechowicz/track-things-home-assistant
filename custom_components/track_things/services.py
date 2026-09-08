"""Explicitly targeted calendar reads, entry writes, and metadata refresh actions."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .api_errors import ApiError, AuthenticationError, NotFoundError, PermissionDeniedError
from .const import DOMAIN
from .create_entry import CREATE_SCHEMA, async_create_entry
from .named_actions import RECORD_SCHEMA, record_entry, recording_options

TARGET_SCHEMA = {vol.Required("config_entry_id"): cv.string}
DAILY_SCHEMA = vol.Schema(
    {
        **TARGET_SCHEMA,
        vol.Optional("date"): cv.date,
        vol.Optional("trackerId"): cv.string,
        vol.Optional("subjectId"): cv.string,
        vol.Optional("language", default="en"): vol.In(("en", "pl")),
    }
)


def _target(hass, call):
    entry = hass.config_entries.async_get_entry(call.data["config_entry_id"])
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError("Unknown Track Things config entry")
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError("Track Things config entry is not loaded")
    return entry


def _summary(day, records, language):
    count = len(records)
    if language == "pl":
        noun = (
            "wpis"
            if count == 1
            else (
                "wpisy" if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14) else "wpisów"
            )
        )
        heading = f"{day.isoformat()}: {count} {noun}."
    else:
        heading = f"{day.isoformat()}: {count} {'entry' if count == 1 else 'entries'}."
    return " ".join([heading, *(event.summary for _, event in records)])


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register once, including when there are no loaded account instances."""

    async def options(call: ServiceCall) -> ServiceResponse:
        return await recording_options(_target(hass, call))

    async def record(call: ServiceCall) -> ServiceResponse:
        return await record_entry(hass, _target(hass, call), call.data)

    hass.services.async_register(
        DOMAIN,
        "get_recording_options",
        options,
        schema=vol.Schema(TARGET_SCHEMA),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "record_entry",
        record,
        schema=RECORD_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    async def create(call: ServiceCall) -> ServiceResponse:
        return await async_create_entry(hass, _target(hass, call), call.data)

    hass.services.async_register(
        DOMAIN,
        "create_entry",
        create,
        schema=CREATE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    async def daily(call: ServiceCall) -> ServiceResponse:
        entry = _target(hass, call)
        runtime = entry.runtime_data
        coordinator = runtime.coordinator
        zone = ZoneInfo(hass.config.time_zone)
        day = call.data.get("date", dt_util.now(zone).date())
        try:
            end = datetime.combine(day + timedelta(days=1), time.min, zone)
        except OverflowError as err:
            raise ServiceValidationError("Date must allow a following calendar day") from err
        tracker_id = call.data.get("trackerId")
        subject_id = call.data.get("subjectId")
        try:
            if not coordinator.last_update_success:
                raise HomeAssistantError("Track Things metadata is unavailable")
            if tracker_id is not None:
                tracker = await coordinator.store.async_tracker(tracker_id)
                selection = coordinator.entry.options.get("tracker_ids")
                if (
                    tracker["id"] != tracker_id
                    or tracker["workspaceId"] != coordinator.store.workspace_id
                ):
                    raise ServiceValidationError("Tracker does not belong to this instance")
                if selection is not None and tracker_id not in selection:
                    raise ServiceValidationError("Tracker is not selected for this instance")
            if subject_id is not None:
                subject = await coordinator.store.async_subject(subject_id)
                if (
                    subject["id"] != subject_id
                    or subject["workspaceId"] != coordinator.store.workspace_id
                ):
                    raise ServiceValidationError("Subject does not belong to this instance")
            records = await runtime.calendar.async_get_records(
                datetime.combine(day, time.min, zone), end, hass.config.time_zone
            )
        except NotFoundError as err:
            raise ServiceValidationError("Unknown tracker or subject for this instance") from err
        except (AuthenticationError, PermissionDeniedError) as err:
            runtime.calendar.invalidate()
            entry.async_start_reauth(hass)
            raise HomeAssistantError("Track Things access must be restored") from err
        except ApiError as err:
            runtime.calendar.invalidate()
            raise HomeAssistantError("Track Things calendar is temporarily unavailable") from err
        records = [
            (item, event)
            for item, event in records
            if (tracker_id is None or item["trackerId"] == tracker_id)
            and (subject_id is None or item["subjectId"] == subject_id)
        ]
        return {
            "date": day.isoformat(),
            "time_zone": hass.config.time_zone,
            "language": call.data["language"],
            "total": len(records),
            "entries": [item for item, _ in records],
            "summary": _summary(day, records, call.data["language"]),
        }

    async def refresh(call: ServiceCall) -> ServiceResponse:
        runtime = _target(hass, call).runtime_data
        runtime.calendar.invalidate()
        await runtime.coordinator.async_refresh()
        if not runtime.coordinator.last_update_success:
            raise HomeAssistantError("Track Things metadata refresh failed")
        return {"refreshed": True} if call.return_response else None

    hass.services.async_register(
        DOMAIN,
        "get_daily_calendar",
        daily,
        schema=DAILY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "refresh",
        refresh,
        schema=vol.Schema(TARGET_SCHEMA),
        supports_response=SupportsResponse.OPTIONAL,
    )
