"""Write eligibility, schema guards and failures through HA's service registry."""

from unittest.mock import Mock
from uuid import UUID

import pytest
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .api_fixtures import ENTRY, SCHEMA, SUBJECT, TRACKER
from .create_entry_fixtures import DATA, create, fresh_metadata, setup_writer

pytestmark = pytest.mark.usefixtures("freezer")


async def test_success_payload_generated_id_and_hook_without_calendar(
    hass, config_entry, auth_http
):
    await setup_writer(hass, config_entry, auth_http)
    notified = Mock()
    remove = config_entry.runtime_data.coordinator.async_add_listener(notified)
    fresh_metadata(auth_http)
    auth_http.respond(ENTRY, status=201)
    data = {k: v for k, v in DATA.items() if k != "request_id"}
    data.update(
        title="Headache",
        note="Synthetic",
        tagIds=["00000000-0000-4000-8000-000000000001"],
        periodStart=DATA["occurredAt"],
        periodEnd=DATA["occurredAt"],
    )
    result = await create(hass, config_entry, data)
    assert UUID(result["request_id"]).version == 4
    assert result["entry"] == ENTRY
    request = auth_http.request.call_args
    assert request.args == (
        "POST",
        "https://backend.example.test/api/workspaces/workspace-1/entries",
    )
    assert request.kwargs["headers"]["Idempotency-Key"] == result["request_id"]
    assert request.kwargs["json"] == {
        **data,
        "source": "manual",
        "expectedSchemaVersionId": SCHEMA["id"],
    }
    notified.assert_called_once_with()
    remove()


@pytest.mark.parametrize(
    "change",
    [
        {"archivedAt": "2026-09-08T00:00:00Z"},
        {"kind": "integration"},
        {"kind": "computed"},
        {"workspaceId": "foreign"},
        {"id": "different"},
        {"currentSchemaVersionId": None},
    ],
)
async def test_fresh_tracker_eligibility(hass, config_entry, auth_http, change):
    await setup_writer(hass, config_entry, auth_http)
    fresh_metadata(auth_http, tracker={**TRACKER, **change})
    with pytest.raises(ServiceValidationError):
        await create(hass, config_entry)
    assert all(c.args[0] == "GET" for c in auth_http.request.call_args_list)


@pytest.mark.parametrize(
    "change",
    [
        {"archivedAt": "2026-09-08T00:00:00Z"},
        {"workspaceId": "foreign"},
        {"id": "different"},
    ],
)
async def test_fresh_subject_eligibility(hass, config_entry, auth_http, change):
    await setup_writer(hass, config_entry, auth_http)
    fresh_metadata(auth_http, subject={**SUBJECT, **change})
    with pytest.raises(ServiceValidationError):
        await create(hass, config_entry)
    assert all(c.args[0] == "GET" for c in auth_http.request.call_args_list)


async def test_current_assignments_ignore_legacy_subject_and_selection(
    hass, config_entry, auth_http
):
    await setup_writer(hass, config_entry, auth_http)
    fresh_metadata(auth_http, tracker={**TRACKER, "subjectIds": []})
    with pytest.raises(ServiceValidationError, match="assigned"):
        await create(hass, config_entry)
    hass.config_entries.async_update_entry(config_entry, options={"tracker_ids": []})
    await hass.async_block_till_done()
    fresh_metadata(auth_http)
    with pytest.raises(ServiceValidationError, match="not selected"):
        await create(hass, config_entry)
    assert all(c.args[0] == "GET" for c in auth_http.request.call_args_list)


@pytest.mark.parametrize("values", [{}, {"severity": 11}, {"severity": True}, {"unknown": 6}])
async def test_invalid_values_never_post(hass, config_entry, auth_http, values):
    await setup_writer(hass, config_entry, auth_http)
    fresh_metadata(auth_http)
    with pytest.raises(ServiceValidationError, match="values"):
        await create(hass, config_entry, {**DATA, "values": values})
    assert all(c.args[0] == "GET" for c in auth_http.request.call_args_list)


@pytest.mark.parametrize(
    "status,code,match",
    [
        (403, "request_failed", "not allowed"),
        (400, "invalid_request", "tags"),
        (409, "tracker_schema_changed", "schema changed"),
        (409, "tracker_schema_unavailable", "schema changed"),
        (409, "idempotency_conflict", "conflicts"),
        (404, "request_failed", "unavailable"),
        (503, "request_failed", "could not be confirmed"),
        (429, "rate_limited", "could not be confirmed"),
    ],
)
async def test_backend_failures_do_not_notify(hass, config_entry, auth_http, status, code, match):
    await setup_writer(hass, config_entry, auth_http)
    notified = Mock()
    remove = config_entry.runtime_data.coordinator.async_add_listener(notified)
    fresh_metadata(auth_http)
    auth_http.respond({"error": {"code": code, "message": "sentinel-private"}}, status=status)
    with pytest.raises(HomeAssistantError, match=match) as error:
        await create(hass, config_entry)
    assert "sentinel-private" not in str(error.value)
    notified.assert_not_called()
    assert len([c for c in auth_http.request.call_args_list if c.args[0] == "POST"]) == 1
    remove()


async def test_new_schema_is_fetched_and_guarded(hass, config_entry, auth_http):
    await setup_writer(hass, config_entry, auth_http)
    fresh_metadata(auth_http, tracker={**TRACKER, "currentSchemaVersionId": "schema-2"})
    auth_http.respond({**SCHEMA, "id": "schema-2", "version": 2})
    auth_http.respond(ENTRY)
    await create(hass, config_entry)
    assert auth_http.request.call_args.kwargs["json"]["expectedSchemaVersionId"] == "schema-2"


@pytest.mark.parametrize(
    "data",
    [
        {"request_id": "bad\n"},
        {"request_id": ""},
        {"request_id": "x" * 256},
        {"tagIds": ["invalid"]},
        {"tagIds": ["00000000-0000-4000-8000-000000000001"] * 2},
        {"occurredAt": "2026-09-08T12:00:00"},
        {"source": "integration"},
        {"expectedSchemaVersionId": "forged"},
        {"values": []},
    ],
)
async def test_invalid_action_inputs(hass, config_entry, auth_http, data):
    await setup_writer(hass, config_entry, auth_http)
    count = auth_http.request.call_count
    with pytest.raises(vol.Invalid):
        await create(hass, config_entry, {**DATA, **data})
    assert auth_http.request.call_count == count


async def test_target_period_and_description(hass, config_entry, auth_http):
    from homeassistant.helpers.service import async_get_all_descriptions

    await setup_writer(hass, config_entry, auth_http)
    for entry in [MockConfigEntry(domain="other"), MockConfigEntry(domain="track_things")]:
        entry.add_to_hass(hass)
        with pytest.raises(ServiceValidationError):
            await create(hass, entry)
    with pytest.raises(ServiceValidationError):
        await create(hass, MockConfigEntry(domain="track_things"))
    with pytest.raises(ServiceValidationError, match="periodEnd"):
        await create(
            hass,
            config_entry,
            {**DATA, "periodStart": "2026-09-09T00:00:00Z", "periodEnd": "2026-09-08T00:00:00Z"},
        )
    descriptions = (await async_get_all_descriptions(hass))["track_things"]
    assert descriptions["create_entry"]["fields"]["config_entry_id"]["required"]
