"""Configured names drive the real adapter, preserving ambiguity and identity."""

from copy import deepcopy
from dataclasses import replace

import pytest

from custom_components.track_things.conversation_adapter import AdapterContext, QuestionAdapter
from custom_components.track_things.conversation_contract import Clarification
from custom_components.track_things.dialogue import Descriptor, DraftPatch
from custom_components.track_things.voice_options import (
    CONF_ALIASES,
    CONF_DEFAULT_SUBJECT,
    alias_mapping,
    catalog,
    target_key,
)

from .conversation_fixtures import say, setup_agent, speech
from .dialogue_fixtures import NOW, metadata
from .test_voice_options import edit_alias


@pytest.mark.parametrize(
    "language,start,alias", [("en", "log Headache", "Annie"), ("pl", "zapisz Headache", "Anny")]
)
async def test_configured_alias_and_rename_through_assist(
    hass, config_entry, auth_http, language, start, alias
):
    agent = await setup_agent(hass, config_entry, auth_http)
    auth_http.respond({"items": [], "nextCursor": None})
    await edit_alias(hass, config_entry, language, target_key("subjects", "anna"), alias)
    config_entry.runtime_data.coordinator.store.snapshot.subjects["anna"]["name"] = "Renamed"
    first = await say(hass, agent, start, language=language)
    result = await say(hass, agent, alias, first.conversation_id, language)
    assert "Pain" in speech(result)
    session = next(iter(agent._sessions.values()))
    agent.drafts.update(
        session.draft_id, DraftPatch(values={"pain": False}, skip_optional=frozenset({"note"}))
    )
    assert agent.drafts.review(session.draft_id).payload["subjectId"] == "anna"


@pytest.mark.parametrize(
    "language,start,me", [("en", "log Headache", "me"), ("pl", "zapisz Headache", "mnie")]
)
async def test_me_requires_explicit_current_assignment(
    hass, config_entry, auth_http, language, start, me
):
    agent = await setup_agent(hass, config_entry, auth_http)
    first = await say(hass, agent, start, language=language)
    cid = first.conversation_id
    assert "Anna, Ben" in speech(await say(hass, agent, me, cid, language))
    auth_http.respond({"items": [], "nextCursor": None})
    hass.config_entries.async_update_entry(config_entry, options={CONF_DEFAULT_SUBJECT: "anna"})
    tracker = config_entry.runtime_data.coordinator.store.snapshot.trackers["headache"]
    tracker["subjectIds"] = ["ben"]
    assert "Anna, Ben" in speech(await say(hass, agent, me, cid, language))
    session = next(iter(agent._sessions.values()))
    assert agent.drafts.inspect(session.draft_id).descriptors[0].kind == "subject"
    tracker["subjectIds"] = ["anna", "ben"]
    result = await say(hass, agent, me, cid, language)
    assert "Pain" in speech(result)
    agent.drafts.update(
        session.draft_id, DraftPatch(values={"pain": False}, skip_optional=frozenset({"note"}))
    )
    assert agent.drafts.review(session.draft_id).payload["subjectId"] == "anna"


def test_tracker_field_option_scopes_language_and_collisions():
    meta = metadata()
    for key, subject in meta.subjects.items():
        subject["name"] = key.title()
    meta.trackers["headache"]["name"] = "Headache"
    choice = {
        "id": "mood-id",
        "key": "mood",
        "label": "Mood",
        "type": "select",
        "options": [{"id": "good", "label": "Good"}, {"id": "bad", "label": "Bad"}],
    }
    meta.schemas["schema-1"]["schema"]["fields"].append(choice)
    other = deepcopy(meta.trackers["headache"])
    other.update(id="other", name="Other", currentSchemaVersionId="schema-2")
    meta.trackers["other"] = other
    meta.schemas["schema-2"] = {
        **deepcopy(meta.schemas["schema-1"]),
        "id": "schema-2",
        "trackerId": "other",
    }
    options = {
        CONF_ALIASES: {
            "en": {
                target_key("trackers", "headache"): ["migraine"],
                target_key("subjects", "anna"): ["friend"],
                target_key("subjects", "ben"): ["friend"],
                target_key("headache:fields", "mood-id"): ["feeling"],
                target_key("headache:mood-id:options", "good"): ["great"],
                target_key("headache:mood-id:options", "missing"): ["invented"],
            }
        }
    }
    context = AdapterContext(meta, "en", NOW, "UTC", aliases=alias_mapping(options, catalog(meta)))
    adapter = QuestionAdapter("en")
    assert adapter.parse("log migraine", context).patch.tracker_id == "headache"
    with pytest.raises(Clarification):
        QuestionAdapter("pl").parse("zapisz migraine", replace(context, language="pl"))
    subject = replace(
        context, tracker_id="headache", descriptor=Descriptor("subject", candidates=("anna", "ben"))
    )
    with pytest.raises(Clarification) as error:
        adapter.parse("friend", subject)
    assert set(error.value.candidates) == {"anna", "ben"}
    assert adapter.parse("anna", subject).patch.subject_id == "anna"
    context = replace(context, tracker_id="headache")
    assert adapter.parse("change feeling to great", context).patch.values == {"mood": "good"}
    for text, ctx in [
        ("change feeling to invented", context),
        ("change feeling to great", replace(context, tracker_id="other")),
    ]:
        with pytest.raises(Clarification):
            adapter.parse(text, ctx)


async def test_collisions_request_clarification_and_options_apply_next_turn(
    hass, config_entry, auth_http
):
    agent = await setup_agent(hass, config_entry, auth_http)
    options = {
        CONF_ALIASES: {
            "en": {
                target_key("subjects", "anna"): ["friend"],
                target_key("subjects", "ben"): ["friend"],
            }
        }
    }
    auth_http.respond({"items": [], "nextCursor": None})
    hass.config_entries.async_update_entry(config_entry, options=options)
    first = await say(hass, agent, "log Headache")
    result = await say(hass, agent, "friend", first.conversation_id)
    assert result.continue_conversation
    assert "anna, ben" in speech(result) or "ben, anna" in speech(result)
    session = next(iter(agent._sessions.values()))
    assert agent.drafts.inspect(session.draft_id).descriptors[0].kind == "subject"
    options = deepcopy(options)
    options[CONF_ALIASES]["en"][target_key("subjects", "ben")] = ["buddy"]
    hass.config_entries.async_update_entry(config_entry, options=options)
    result = await say(hass, agent, "friend", first.conversation_id)
    assert "Pain" in speech(result)


async def test_calendar_filters_share_aliases_and_explicit_default(
    hass, config_entry, auth_http, monkeypatch
):
    from unittest.mock import AsyncMock

    agent = await setup_agent(hass, config_entry, auth_http)
    records = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "custom_components.track_things.calendar_conversation.async_daily_records", records
    )
    auth_http.respond({"items": [], "nextCursor": None})
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            CONF_DEFAULT_SUBJECT: "anna",
            CONF_ALIASES: {
                "pl": {
                    target_key("trackers", "headache"): ["bólu głowy"],
                    target_key("subjects", "anna"): ["Anny"],
                }
            },
        },
    )
    for subject in ("Anny", "mnie"):
        result = await say(
            hass,
            agent,
            f"kalendarz na dzisiaj; tracker: bólu głowy; osoba: {subject}",
            language="pl",
        )
        assert "Brak wpisów" in speech(result)
        assert records.call_args.args[-2:] == ("headache", "anna")
    records.reset_mock()
    config_entry.runtime_data.coordinator.store.snapshot.trackers["headache"]["subjectIds"] = [
        "ben"
    ]
    result = await say(hass, agent, "calendar; tracker: Headache; subject: me")
    assert result.continue_conversation
    records.assert_not_called()


async def test_initial_tracker_collision_creates_a_clarification_session(
    hass, config_entry, auth_http
):
    agent = await setup_agent(hass, config_entry, auth_http)
    store = config_entry.runtime_data.coordinator.store
    other = deepcopy(store.snapshot.trackers["headache"])
    other.update(id="other", name="Other", currentSchemaVersionId="schema-2")
    store.snapshot.trackers["other"] = other
    store._schemas["schema-2"] = {
        **deepcopy(store._schemas["schema-1"]),
        "id": "schema-2",
        "trackerId": "other",
    }
    auth_http.respond({"items": [], "nextCursor": None})
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            CONF_ALIASES: {
                "en": {
                    target_key("trackers", "headache"): ["shared"],
                    target_key("trackers", "other"): ["shared"],
                }
            }
        },
    )
    first = await say(hass, agent, "log shared")
    assert first.continue_conversation
    session = next(iter(agent._sessions.values()))
    assert agent.drafts.view(session.draft_id).tracker_id is None
    result = await say(hass, agent, "other", first.conversation_id)
    assert "Anna, Ben" in speech(result)
    assert agent.drafts.view(session.draft_id).tracker_id == "other"
