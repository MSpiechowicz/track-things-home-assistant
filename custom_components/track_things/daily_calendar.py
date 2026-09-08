"""Shared validated daily records for actions and conversation pagination."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .api_errors import ApiError, AuthenticationError, NotFoundError, PermissionDeniedError


async def async_daily_records(hass, entry, day, tracker_id=None, subject_id=None):
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    zone = ZoneInfo(hass.config.time_zone)
    try:
        end = datetime.combine(day + timedelta(days=1), time.min, zone)
    except OverflowError as err:
        raise ServiceValidationError("Date must allow a following calendar day") from err
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
    return records
