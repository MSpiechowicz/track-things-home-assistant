"""Calendar queries through the real Assist entity and shared daily query."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components import conversation

from custom_components.track_things.api_errors import AuthenticationError, ServerError

from .api_fixtures import ENTRY, SUBJECT, TRACKER
from .calendar_fixtures import setup_calendar
from .conversation_fixtures import say, speech


async def calendar_agent(hass, config_entry, auth_http):
    await setup_calendar(hass, config_entry, auth_http)
    return next(
        conversation.async_get_agent(hass, entity_id)
        for entity_id in hass.states.async_entity_ids("conversation")
        if getattr(conversation.async_get_agent(hass, entity_id), "entry", None) is config_entry
    )


@pytest.mark.parametrize(
    "language,command,expected",
    [
        ("en", "calendar", "2026-09-08: 1 entry."),
        ("en", "calendar for yesterday", "2026-09-07: 1 entry."),
        ("pl", "kalendarz na wczoraj", "2026-09-07: liczba wpisów: 1."),
        ("pl", "kalendarz na 2026-09-08", "2026-09-08: liczba wpisów: 1."),
        ("de", "Kalender für gestern", "2026-09-07: 1 Eintrag."),
        ("fr", "calendrier pour hier", "2026-09-07 : 1 entrée."),
    ],
)
async def test_local_dates_and_grounded_totals(
    hass, config_entry, auth_http, freezer, language, command, expected
):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-09-07T22:30:00Z")
    agent = await calendar_agent(hass, config_entry, auth_http)
    day = expected[:10]
    auth_http.respond({"items": [{**ENTRY, "occurredAt": day + "T12:00:00Z"}], "nextCursor": None})
    result = await say(hass, agent, command, language=language)
    assert speech(result) == expected + " Anna · Headache"
    assert not result.continue_conversation
    assert not any(call.args[0] == "POST" for call in auth_http.request.call_args_list)


@pytest.mark.parametrize(
    "language,command,choose",
    [
        ("en", "calendar for 2026-09-08; tracker: Headache; subject: Anna", "Which subject"),
        ("pl", "kalendarz na 2026-09-08; tracker: Headache; osoba: Anna", "Wybierz (osoba)"),
    ],
)
async def test_filters_and_ambiguous_subjects(
    hass, config_entry, auth_http, language, command, choose
):
    agent = await calendar_agent(hass, config_entry, auth_http)
    store = config_entry.runtime_data.coordinator.store
    store.snapshot.subjects["other"] = {**SUBJECT, "id": "other"}
    store._subjects["other"] = store.snapshot.subjects["other"]
    first = await say(hass, agent, command, language=language)
    assert choose in speech(first)
    assert SUBJECT["id"] in speech(first) and "other" in speech(first)
    assert first.continue_conversation
    invalid = await say(hass, agent, "invented", first.conversation_id, language)
    assert speech(invalid) == speech(first)
    auth_http.respond(
        {"items": [ENTRY, {**ENTRY, "id": "second", "subjectId": "other"}], "nextCursor": None}
    )
    result = await say(hass, agent, SUBJECT["id"], first.conversation_id, language)
    assert "1" in speech(result) and "Anna · Headache" in speech(result)
    session = next(iter(agent.calendar.sessions.values()))
    assert session.records == ((ENTRY["id"], "Anna · Headache"),)
    assert session.filters == {"tracker": TRACKER["id"], "subject": SUBJECT["id"]}


async def test_calendar_can_filter_archived_read_only_tracker(hass, config_entry, auth_http):
    agent = await calendar_agent(hass, config_entry, auth_http)
    store = config_entry.runtime_data.coordinator.store
    store.snapshot.trackers[TRACKER["id"]]["archivedAt"] = "2026-01-01T00:00:00Z"
    assert not config_entry.runtime_data.coordinator.voice_trackers
    auth_http.respond({"items": [ENTRY], "nextCursor": None})
    result = await say(hass, agent, "calendar for 2026-09-08; tracker: Headache")
    assert "Anna · Headache" in speech(result)


@pytest.mark.parametrize(
    "language,command,empty,unavailable",
    [
        ("en", "calendar for 2026-09-08", "No entries", "unavailable"),
        ("pl", "kalendarz na 2026-09-08", "Brak wpisów", "niedostępny"),
    ],
)
async def test_empty_and_errors_are_distinct(
    hass, config_entry, auth_http, language, command, empty, unavailable
):
    agent = await calendar_agent(hass, config_entry, auth_http)
    auth_http.respond({"items": [], "nextCursor": None})
    result = await say(hass, agent, command, language=language)
    assert empty in speech(result)
    cid = result.conversation_id
    for error in (ServerError(), AuthenticationError()):
        with patch.object(
            config_entry.runtime_data.calendar, "async_get_records", AsyncMock(side_effect=error)
        ):
            with patch.object(config_entry, "async_start_reauth") as reauth:
                result = await say(hass, agent, command, cid, language)
                assert unavailable in speech(result)
                assert empty not in speech(result)
                assert not agent.calendar.sessions
                assert reauth.called == isinstance(error, AuthenticationError)


@pytest.mark.parametrize(
    "command",
    [
        "calendar for invalid",
        "calendar for 9999-12-31",
        "calendar; subject:",
        "calendar; tracker: Headache; tracker: Headache",
        "calendar; unknown: Anna",
    ],
)
async def test_invalid_query_never_reads(hass, config_entry, auth_http, command):
    agent = await calendar_agent(hass, config_entry, auth_http)
    with patch.object(config_entry.runtime_data.calendar, "async_get_records") as read:
        result = await say(hass, agent, command)
        read.assert_not_called()
        assert "Anna · Headache" not in speech(result)


@pytest.mark.parametrize(
    "language,command",
    [
        ("en", "calendar for 2026-09-08 for tracker Headache for subject Anna"),
        ("pl", "kalendarz na 2026-09-08 dla trackera Headache dla osoby Anna"),
        ("de", "Kalender für 2026-09-08 für Tracker Headache für Person Anna"),
        ("fr", "calendrier pour 2026-09-08 du tracker Headache de la personne Anna"),
    ],
)
async def test_spoken_filters(hass, config_entry, auth_http, language, command):
    agent = await calendar_agent(hass, config_entry, auth_http)
    auth_http.respond({"items": [ENTRY], "nextCursor": None})
    result = await say(hass, agent, command, language=language)
    assert "Anna · Headache" in speech(result)
    assert next(iter(agent.calendar.sessions.values())).filters == {
        "tracker": TRACKER["id"],
        "subject": SUBJECT["id"],
    }


async def test_ambiguous_tracker_then_subject_and_expiring_question(hass, config_entry, auth_http):
    from unittest.mock import Mock

    agent = await calendar_agent(hass, config_entry, auth_http)
    clock = agent.calendar.clock = Mock(return_value=0)
    store = config_entry.runtime_data.coordinator.store
    store.snapshot.trackers["other"] = {**TRACKER, "id": "other"}
    store.snapshot.subjects["other"] = {**SUBJECT, "id": "other"}
    command = "calendar for 2026-09-08 for tracker Headache for subject Anna"
    first = await say(hass, agent, command)
    assert "Which tracker" in speech(first)
    result = await say(hass, agent, TRACKER["id"], first.conversation_id)
    assert "Which subject" in speech(result)
    clock.return_value = 300
    result = await say(hass, agent, SUBJECT["id"], first.conversation_id)
    assert not agent.calendar.sessions
    assert "Anna · Headache" not in speech(result)
