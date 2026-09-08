"""Explicit, schema-guarded manual writes through the response action."""

from copy import deepcopy
from uuid import uuid4

import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api_errors import (
    ApiError,
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from .schema import EntryValueError, SchemaUnavailableError, validate_entry_values


def _timestamp(value):
    value = vol.All(str, vol.Length(min=1))(value)
    if cv.datetime(value).utcoffset() is None:
        raise vol.Invalid("Timestamp must include a timezone")
    return value


def _tags(value):
    value = vol.All(
        [
            vol.All(
                str,
                vol.Match(
                    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
                    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\Z"
                ),
            )
        ],
        vol.Length(max=50),
    )(value)
    if len(set(value)) != len(value):
        raise vol.Invalid("Tag IDs must be unique")
    return value


CREATE_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Required("trackerId"): vol.All(str, vol.Length(min=1)),
        vol.Required("subjectId"): vol.All(str, vol.Length(min=1)),
        vol.Required("occurredAt"): _timestamp,
        vol.Required("values"): dict,
        vol.Optional("periodStart"): vol.Any(None, _timestamp),
        vol.Optional("periodEnd"): vol.Any(None, _timestamp),
        vol.Optional("title"): vol.Any(None, str),
        vol.Optional("note"): vol.Any(None, str),
        vol.Optional("tagIds"): _tags,
        vol.Optional("request_id"): vol.All(str, vol.Match(r"^[\x21-\x7e]{1,255}\Z")),
    }
)


async def async_create_entry(hass, entry, data):
    """Refresh authoritative resources, validate, and submit exactly once.

    Backend authorization, tag ownership and durable idempotency remain authoritative.
    No local successful-result cache can bypass permission checks on a replay.
    """
    runtime = entry.runtime_data
    store = runtime.coordinator.store
    request_id = data.get("request_id") or str(uuid4())
    payload = deepcopy(
        {k: v for k, v in data.items() if k not in {"config_entry_id", "request_id"}}
    )
    payload["source"] = "manual"
    start, end = payload.get("periodStart"), payload.get("periodEnd")
    if start and end and cv.datetime(end) < cv.datetime(start):
        raise ServiceValidationError("periodEnd cannot be before periodStart")
    try:
        # Historical caches are deliberately bypassed for mutable write eligibility.
        tracker = await runtime.api.get_tracker(store.workspace_id, payload["trackerId"])
        subject = await runtime.api.get_subject(store.workspace_id, payload["subjectId"])
        if (
            tracker["id"] != payload["trackerId"]
            or tracker["workspaceId"] != store.workspace_id
            or tracker["kind"] != "manual"
            or tracker["archivedAt"] is not None
        ):
            raise ServiceValidationError(
                "Tracker must be an active manual tracker in this workspace"
            )
        if (
            subject["id"] != payload["subjectId"]
            or subject["workspaceId"] != store.workspace_id
            or subject["archivedAt"] is not None
            or subject["id"] not in tracker["subjectIds"]
        ):
            raise ServiceValidationError(
                "Subject must be active and currently assigned to the tracker"
            )
        version_id = tracker["currentSchemaVersionId"]
        if version_id is None:
            raise ServiceValidationError("Tracker schema is unavailable")
        schema = await store.async_schema(tracker["id"], version_id)
        validate_entry_values(payload["values"], schema["schema"])
        # Options may change while metadata requests are awaiting HTTP responses.
        selected = entry.options.get("tracker_ids")
        if selected is not None and tracker["id"] not in selected:
            raise ServiceValidationError("Tracker is not selected for this instance")
        payload["expectedSchemaVersionId"] = version_id
        created = await runtime.api.create_entry(
            store.workspace_id, payload, idempotency_key=request_id
        )
    except EntryValueError, SchemaUnavailableError:
        raise ServiceValidationError("Entry values or tracker schema are invalid") from None
    except AuthenticationError:
        entry.async_start_reauth(hass)
        raise HomeAssistantError("Track Things authentication must be restored") from None
    except PermissionDeniedError:
        raise ServiceValidationError(
            "Track Things account is not allowed to create this entry"
        ) from None
    except NotFoundError:
        raise ServiceValidationError("A required workspace resource is unavailable") from None
    except ConflictError as err:
        message = (
            "Request ID conflicts with an earlier submission; do not retry with changed content"
            if err.code == "idempotency_conflict"
            else "Tracker schema changed or is unavailable; refresh and review the entry"
        )
        raise ServiceValidationError(message) from None
    except ApiError as err:
        if err.status == 400:
            raise ServiceValidationError("Backend rejected the entry or its tags") from None
        # A generated key must remain recoverable even when the write response is lost.
        raise HomeAssistantError(
            "Entry creation could not be confirmed. "
            f"Retry identical data with request_id={request_id}"
        ) from None
    runtime.coordinator.async_entries_changed()
    return {"request_id": request_id, "entry": created}
