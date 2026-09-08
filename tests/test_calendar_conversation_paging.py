"""Snapshot paging, expiry and authenticated-context isolation through Assist."""

from datetime import date
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.calendar import CalendarEvent
from homeassistant.components.conversation import ConversationInput
from homeassistant.core import Context
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .api_fixtures import ENTRY
from .conversation_fixtures import say, speech
from .test_calendar_conversation import calendar_agent


def records(count=7):
    return [
        (
            {**ENTRY, "id": f"entry-{number}"},
            CalendarEvent(date(2026, 9, 8), date(2026, 9, 9), f"Record-{number}."),
        )
        for number in range(count)
    ]


@pytest.mark.parametrize(
    "language,command,more",
    [
        ("en", "calendar for 2026-09-08", "more"),
        ("pl", "kalendarz na 2026-09-08", "więcej"),
    ],
)
async def test_seven_entries_once_and_snapshot_survives_refresh(
    hass, config_entry, auth_http, language, command, more
):
    agent = await calendar_agent(hass, config_entry, auth_http)
    source = records()
    with patch.object(
        config_entry.runtime_data.calendar, "async_get_records", AsyncMock(return_value=source)
    ) as read:
        first = await say(hass, agent, command, language=language)
        cid = first.conversation_id
        assert first.continue_conversation
        assert "7" in speech(first)
        for number in range(7):
            assert (f"Record-{number}." in speech(first)) == (number < 5)
        source[5][1].summary = "CHANGED"
        config_entry.runtime_data.calendar.invalidate()
        second = await say(hass, agent, more, cid, language)
        assert second.conversation_id == cid
        assert not second.continue_conversation
        for number in range(7):
            assert (f"Record-{number}." in speech(second)) == (number >= 5)
        assert "CHANGED" not in speech(second)
        third = await say(hass, agent, more, cid, language)
        assert "Record-" not in speech(third)
        read.assert_awaited_once()
        assert next(iter(agent.calendar.sessions.values())).position == 7


@pytest.mark.parametrize(
    "identity",
    [
        {"user_id": "other"},
        {"device_id": "other"},
        {"satellite_id": "other"},
        {"user_id": None},
        {"device_id": None},
    ],
)
async def test_more_cannot_cross_identity(hass, config_entry, auth_http, identity):
    agent = await calendar_agent(hass, config_entry, auth_http)
    with patch.object(
        config_entry.runtime_data.calendar, "async_get_records", AsyncMock(return_value=records())
    ):
        first = await say(hass, agent, "calendar for 2026-09-08")
        result = await say(hass, agent, "more", first.conversation_id, **identity)
        assert "Record-" not in speech(result)
        assert next(iter(agent.calendar.sessions.values())).position == 5
        own = await say(hass, agent, "more", first.conversation_id)
        assert "Record-5." in speech(own)


async def test_language_and_config_entry_isolation(hass, config_entry, auth_http):
    agent = await calendar_agent(hass, config_entry, auth_http)
    second_entry = MockConfigEntry(domain="track_things", data=dict(config_entry.data))
    second_agent = await calendar_agent(hass, second_entry, auth_http)
    with patch.object(
        config_entry.runtime_data.calendar, "async_get_records", AsyncMock(return_value=records())
    ):
        first = await say(hass, agent, "calendar for 2026-09-08")
        for target, language, command in [(agent, "pl", "więcej"), (second_agent, "en", "more")]:
            result = await say(hass, target, command, first.conversation_id, language)
            assert "Record-" not in speech(result)
        assert next(iter(agent.calendar.sessions.values())).position == 5


async def test_expiry_repeat_cancel_and_restart(hass, config_entry, auth_http):
    agent = await calendar_agent(hass, config_entry, auth_http)
    clock = agent.calendar.clock = Mock(return_value=0)
    with patch.object(
        config_entry.runtime_data.calendar, "async_get_records", AsyncMock(return_value=records())
    ):
        first = await say(hass, agent, "calendar for 2026-09-08")
        cid = first.conversation_id
        clock.return_value = 299
        repeated = await say(hass, agent, "repeat", cid)
        assert speech(first) == speech(repeated)
        clock.return_value = 300
        expired = await say(hass, agent, "more", cid)
        assert "Record-" not in speech(expired)
        assert not agent.calendar.sessions
        first = await say(hass, agent, "calendar for 2026-09-08")
        await say(hass, agent, "cancel", first.conversation_id)
        assert not agent.calendar.sessions
        await say(hass, agent, "calendar for 2026-09-08")
        assert agent.calendar.sessions
        assert await hass.config_entries.async_unload(config_entry.entry_id)
        assert not agent.calendar.sessions
        assert "Record-" not in speech(
            await agent.async_process(
                ConversationInput(
                    text="more",
                    context=Context(),
                    conversation_id=cid,
                    device_id=None,
                    satellite_id=None,
                    language="en",
                    agent_id=agent.entity_id,
                )
            )
        )


async def test_unavailable_or_changed_selection_drops_snapshot(hass, config_entry, auth_http):
    agent = await calendar_agent(hass, config_entry, auth_http)
    with patch.object(
        config_entry.runtime_data.calendar, "async_get_records", AsyncMock(return_value=records())
    ):
        first = await say(hass, agent, "calendar for 2026-09-08")
        config_entry.runtime_data.coordinator.last_update_success = False
        result = await say(hass, agent, "more", first.conversation_id)
        assert "unavailable" in speech(result)
        assert not agent.calendar.sessions
        config_entry.runtime_data.coordinator.last_update_success = True
        first = await say(hass, agent, "calendar for 2026-09-08")
        hass.config_entries.async_update_entry(config_entry, options={"tracker_ids": []})
        result = await say(hass, agent, "more", first.conversation_id)
        assert "Record-" not in speech(result)
        assert not agent.calendar.sessions
