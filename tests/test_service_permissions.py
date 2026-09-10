"""User-scoped services enforce HA permissions before accessing workspace data."""

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_READ_ONLY, GROUP_ID_USER
from homeassistant.auth.models import Group
from homeassistant.core import Context
from homeassistant.exceptions import Unauthorized, UnknownUser
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .calendar_fixtures import setup_calendar

ACTIONS = {
    "create_entry": {
        "trackerId": "tracker",
        "subjectId": "subject",
        "occurredAt": "2026-09-10T12:00:00Z",
        "values": {},
    },
    "record_entry": {"tracker": "Tracker", "subject": "Subject"},
    "refresh": {},
    "get_daily_calendar": {"date": "2026-09-10"},
    "get_recording_options": {},
}
READS = {"get_daily_calendar", "get_recording_options"}


async def invoke(hass, entry, action, caller_id):
    return await hass.services.async_call(
        "track_things",
        action,
        {"config_entry_id": entry.entry_id, **ACTIONS[action]},
        context=Context(user_id=caller_id),
        blocking=True,
        return_response=True,
    )


@pytest.fixture
def effects(loaded, config_entry):
    """Observe every service's first data access or side effect."""
    with ExitStack() as stack:
        mocks = [
            stack.enter_context(
                patch(f"custom_components.track_things.services.{name}", new_callable=AsyncMock)
            )
            for name in (
                "async_create_entry",
                "record_entry",
                "async_daily_records",
                "recording_options",
            )
        ]
        for mock in mocks:
            mock.return_value = {}
        mocks[2].return_value = []
        runtime = config_entry.runtime_data
        mocks.append(stack.enter_context(patch.object(runtime.calendar, "invalidate")))
        mocks.append(
            stack.enter_context(patch.object(runtime.coordinator, "async_refresh", AsyncMock()))
        )
        yield mocks


@pytest.fixture
async def loaded(hass, config_entry, auth_http):
    await hass.auth.async_create_user("Owner")
    return await setup_calendar(hass, config_entry, auth_http)


@pytest.mark.parametrize("action", ACTIONS)
async def test_read_only_user_cannot_write(hass, config_entry, loaded, action, effects):
    caller = await hass.auth.async_create_user("Reader", group_ids=[GROUP_ID_READ_ONLY])
    assert not caller.permissions.check_entity(loaded.entity_id, "control")
    if action in READS:
        await invoke(hass, config_entry, action, caller.id)
        assert any(mock.called for mock in effects)
    else:
        with pytest.raises(Unauthorized):
            await invoke(hass, config_entry, action, caller.id)
        assert not any(mock.called for mock in effects)


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("identity", ["unknown", "inactive", "no_access"])
async def test_denied_user_never_accesses_data(
    hass, config_entry, loaded, action, identity, effects
):
    caller_id = "missing-user"
    if identity != "unknown":
        caller = await hass.auth.async_create_user("Denied")
        caller.is_active = identity != "inactive"
        caller_id = caller.id
    with pytest.raises(UnknownUser if identity == "unknown" else Unauthorized):
        await invoke(hass, config_entry, action, caller_id)
    assert not any(mock.called for mock in effects)


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("group", [GROUP_ID_ADMIN, GROUP_ID_USER, None])
async def test_authorized_users_and_internal_automations_still_work(
    hass, config_entry, loaded, action, group, effects
):
    caller = await hass.auth.async_create_user("Allowed", group_ids=[group]) if group else None
    await invoke(hass, config_entry, action, caller.id if caller else None)
    assert any(mock.called for mock in effects)


@pytest.mark.parametrize("action", ACTIONS)
async def test_permission_is_bound_to_target_instance(
    hass, config_entry, auth_http, loaded, action, effects
):
    other = MockConfigEntry(domain="track_things", data=dict(config_entry.data))
    other_entity = await setup_calendar(hass, other, auth_http)
    registry = er.async_get(hass)
    renamed = registry.async_update_entity(loaded.entity_id, new_entity_id="calendar.renamed")
    caller = await hass.auth.async_create_user("Scoped")
    caller.groups = [
        Group(name="Scoped", policy={"entities": {"entity_ids": {renamed.entity_id: True}}})
    ]
    assert not caller.permissions.check_entity(other_entity.entity_id, "read")
    with pytest.raises(Unauthorized):
        await invoke(hass, other, action, caller.id)
    assert not any(mock.called for mock in effects)
    await invoke(hass, config_entry, action, caller.id)
    assert any(mock.called for mock in effects)


async def test_missing_permission_anchor_fails_closed(hass, config_entry, loaded, effects):
    caller = await hass.auth.async_create_user("Allowed", group_ids=[GROUP_ID_USER])
    with patch.object(er.async_get(hass), "async_get_entity_id", return_value=None):
        with pytest.raises(Unauthorized):
            await invoke(hass, config_entry, "create_entry", caller.id)
    assert not any(mock.called for mock in effects)
