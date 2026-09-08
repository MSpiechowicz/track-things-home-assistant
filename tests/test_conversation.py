"""Bilingual guided drafts through Home Assistant's conversation API."""

from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.track_things.conversation_contract import Proposal
from custom_components.track_things.dialogue import DraftPatch

from .conversation_fixtures import say, setup_agent, speech


@pytest.mark.parametrize(
    ("language", "start", "yes", "seven", "correct", "skip", "confirm", "review", "unavailable"),
    [
        (
            "en",
            "log Headache",
            "yes",
            "seven",
            "change Severity to six",
            "/skip",
            "confirm",
            "Review",
            "No entry was saved",
        ),
        (
            "pl",
            "zapisz Headache",
            "tak",
            "siedem",
            "zmień Severity na sześć",
            "/pomiń",
            "potwierdź",
            "Sprawdź",
            "Nie zapisano wpisu",
        ),
        (
            "de",
            "erfasse Headache",
            "ja",
            "sieben",
            "ändere Severity auf sechs",
            "/überspringen",
            "bestätigen",
            "prüfen",
            "Kein Eintrag",
        ),
        (
            "fr",
            "note Headache",
            "oui",
            "sept",
            "change Severity en six",
            "/passer",
            "confirmer",
            "Vérifie",
            "Aucune entrée",
        ),
    ],
)
async def test_creation_reaches_review_without_saving(
    hass,
    config_entry,
    auth_http,
    language,
    start,
    yes,
    seven,
    correct,
    skip,
    confirm,
    review,
    unavailable,
):
    agent = await setup_agent(hass, config_entry, auth_http)
    agent.writer = None  # Explicitly exercise the optional no-writer runtime seam.
    first = await say(hass, agent, start, language=language)
    cid = first.conversation_id
    assert first.continue_conversation
    assert "Anna, Ben" in speech(first)
    for text, expected in [("Anna", "Pain"), (yes, "Severity"), (seven, "Note")]:
        result = await say(hass, agent, text, cid, language)
        assert expected in speech(result)
        assert result.conversation_id == cid
        assert result.continue_conversation
    # Slash commands protect literal free-text answers from being treated as controls.
    await say(hass, agent, "/" + correct, cid, language)
    result = await say(hass, agent, skip, cid, language)
    assert review in speech(result)
    assert "Severity: 6" in speech(result)
    assert "Headache; Anna;" in speech(result)
    result = await say(hass, agent, confirm, cid, language)
    assert unavailable in speech(result)
    assert agent.confirmed_draft_callback is None
    assert not any(call.args[0] == "POST" for call in auth_http.request.call_args_list)


async def test_unreviewed_confirmation_and_free_text_are_not_writes(hass, config_entry, auth_http):
    agent = await setup_agent(hass, config_entry, auth_http, subjects=("anna",))
    callback = agent.confirmed_draft_callback = AsyncMock(return_value="callback accepted")
    first = await say(hass, agent, "log Headache")
    cid = first.conversation_id
    assert "Pain" in speech(first)  # Sole eligible subject selected explicitly by DraftStore.
    assert "could not use" in speech(await say(hass, agent, "confirm", cid))
    callback.assert_not_called()
    await say(hass, agent, "yes", cid)
    await say(hass, agent, "seven", cid)
    result = await say(hass, agent, "confirm", cid)
    assert "Note: confirm" in speech(result)
    callback.assert_not_called()
    await say(hass, agent, "confirm", cid)
    callback.assert_awaited_once()
    submission = callback.call_args.args[0]
    assert submission.payload["subjectId"] == "anna"
    assert submission.payload["values"]["note"] == "confirm"
    await say(hass, agent, "confirm", cid)
    callback.assert_awaited_once()


async def test_hidden_fields_defaults_and_recovery(hass, config_entry, auth_http):
    agent = await setup_agent(hass, config_entry, auth_http, subjects=("anna",))
    first = await say(hass, agent, "log")
    cid = first.conversation_id
    assert "Headache" in speech(first)
    await say(hass, agent, "Headache", cid)
    result = await say(hass, agent, "no", cid)
    assert "Note" in speech(result)
    assert "Severity" not in speech(result)
    result = await say(hass, agent, "/change Severity to seven", cid)
    assert "could not use" in speech(result)
    await say(hass, agent, "/skip", cid)
    auth_http.respond({"items": [], "nextCursor": None})
    result = await say(hass, agent, "calendar", cid)
    assert "No entries" in speech(result)
    await say(hass, agent, "cancel", cid)
    result = await say(hass, agent, "repeat", cid)
    assert "Pain: no" in speech(result)
    assert "Severity" not in speech(result)
    await say(hass, agent, "cancel", cid)
    first = await say(hass, agent, "log Headache")
    result = await say(hass, agent, "use defaults", first.conversation_id)
    assert "Severity" in speech(result)
    assert "Pain?" not in speech(result)


@pytest.mark.parametrize("proposal", [None, Proposal("patch", DraftPatch(values={"invented": 1}))])
async def test_malformed_adapter_output_preserves_draft(hass, config_entry, auth_http, proposal):
    agent = await setup_agent(hass, config_entry, auth_http, subjects=("anna",))
    first = await say(hass, agent, "log Headache")
    agent._adapters["en"] = Mock(parse=Mock(return_value=proposal))
    result = await say(hass, agent, "bad proposal", first.conversation_id)
    assert "could not use" in speech(result)
    assert "Pain" in speech(result)
    assert "invented" not in speech(result)
