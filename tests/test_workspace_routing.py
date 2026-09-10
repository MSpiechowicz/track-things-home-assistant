"""Workspace choices remain deterministic and respect connected account scope."""

from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState

from custom_components.track_things.workspace_routing import connected, matches

from .dialogue_fixtures import metadata
from .test_natural_conversation import model_result, natural_agent, user


def fixtures():
    a, b = metadata(("anna",)), metadata(("anna",))
    a.trackers["headache"]["name"] = "Migraine"
    b.trackers["headache"]["name"] = "Poo"
    for m in (a, b):
        m.subjects["anna"]["name"] = "Anna"
    entries = {"a": SimpleNamespace(title="Personal"), "b": SimpleNamespace(title="Family")}
    return entries, {"a": a, "b": b}


def test_unique_tracker_overrides_preference_and_explicit_workspace_is_strict():
    entries, catalog = fixtures()
    data = {"action": "create", "tracker_name": "Poo", "subject_name": "Anna"}
    assert list(matches(data, None, entries, catalog, preferred="a")) == ["b"]
    assert not matches(data, "Personal", entries, catalog, preferred="b")
    assert list(matches(data, "Family", entries, catalog)) == ["b"]


def test_ambiguity_preference_and_duplicate_titles():
    entries, catalog = fixtures()
    catalog["b"].trackers["headache"]["name"] = "Migraine"
    data = {"action": "create", "tracker_name": "Migraine"}
    assert len(matches(data, None, entries, catalog)) == 2
    assert list(matches(data, None, entries, catalog, preferred="b")) == ["b"]
    entries["b"].title = "Personal"
    assert len(matches(data, "Personal", entries, catalog, preferred="b")) == 2


def test_account_and_explicit_scope_filter(hass):
    owner = SimpleNamespace(
        entry_id="a",
        options={"voice_workspace_entries": ["a", "b", "c"]},
        data={"backend_url": "https://example.com", "user_id": "u"},
    )

    def entry(id, user, state=ConfigEntryState.LOADED):
        return SimpleNamespace(
            entry_id=id, data={"backend_url": "https://example.com", "user_id": user}, state=state
        )

    with patch.object(
        hass.config_entries,
        "async_entries",
        return_value=[
            entry("a", "u"),
            entry("b", "other"),
            entry("c", "u", ConfigEntryState.NOT_LOADED),
            entry("d", "u"),
        ],
    ):
        assert list(connected(hass, owner)) == ["a"]


async def test_clarify_then_keep_draft_workspace(hass, config_entry, auth_http):
    agent = await natural_agent(hass, config_entry, auth_http)
    other = SimpleNamespace(
        entry_id="other",
        title="Family",
        data=dict(config_entry.data),
        runtime_data=config_entry.runtime_data,
        options={},
    )
    entries = {config_entry.entry_id: config_entry, "other": other}
    with (
        patch(
            "custom_components.track_things.natural_conversation.connected", return_value=entries
        ),
        patch.object(agent, "_gemini", return_value="conversation.interpreter"),
        patch(
            "homeassistant.components.conversation.async_converse",
            return_value=model_result(
                {
                    "action": "create",
                    "tracker_name": "Headache",
                    "values": {"pain": False},
                    "review": True,
                }
            ),
        ),
    ):
        result = await agent.async_process(user("log headache without pain"))
        assert "Which workspace" in result.response.speech["plain"]["speech"]
        result = await agent.async_process(user("Family"))
        assert "Workspace Family" in result.response.speech["plain"]["speech"]
        assert "Review" in result.response.speech["plain"]["speech"]
        assert not agent._sessions
        assert agent._workspace_engines["other"]._sessions
        await agent.async_process(user("cancel"))
        assert not agent._workspace_engines["other"]._sessions
        assert not agent._workspace_routes


async def test_confirmation_saves_only_selected_workspace(hass, config_entry, auth_http):
    from unittest.mock import AsyncMock

    agent = await natural_agent(hass, config_entry, auth_http)
    other = SimpleNamespace(
        entry_id="other",
        title="Family",
        data=dict(config_entry.data),
        runtime_data=config_entry.runtime_data,
        options={},
    )
    entries = {config_entry.entry_id: config_entry, "other": other}
    own_sink, other_sink = AsyncMock(), AsyncMock(return_value="Entry saved.")
    agent.confirmed_draft_callback = own_sink
    agent._engine(other).confirmed_draft_callback = other_sink
    with (
        patch(
            "custom_components.track_things.natural_conversation.connected", return_value=entries
        ),
        patch.object(agent, "_gemini", return_value="conversation.interpreter"),
        patch(
            "homeassistant.components.conversation.async_converse",
            return_value=model_result(
                {
                    "action": "create",
                    "workspace_name": "Family",
                    "tracker_name": "Headache",
                    "values": {"pain": False},
                    "review": True,
                }
            ),
        ),
    ):
        await agent.async_process(user("log headache in Family without pain"))
        await agent.async_process(user("confirm", uid="other-user"))
        other_sink.assert_not_called()
        result = await agent.async_process(user("Confirm."))
        assert "Workspace Family. Entry saved." == result.response.speech["plain"]["speech"]
        await agent.async_process(user("confirm"))
    own_sink.assert_not_called()
    other_sink.assert_awaited_once()
