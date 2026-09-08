"""Options UI persists stable references and permits repair without a reload."""

from copy import deepcopy

import pytest

from custom_components.track_things.voice_options import (
    CONF_ALIASES,
    CONF_DEFAULT_SUBJECT,
    alias_mapping,
    catalog,
    current_metadata,
    target_key,
)

from .conversation_fixtures import setup_agent


async def voice_form(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"tracker_ids": ["headache"], "configure_voice": True}
    )


async def edit_alias(hass, entry, language, target, text, default=""):
    result = await voice_form(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"language": language, "target": target, CONF_DEFAULT_SUBJECT: default},
    )
    assert result["step_id"] == "alias"
    return await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"aliases": text}
    )


async def test_language_separation_rename_stability_and_live_options(hass, config_entry, auth_http):
    await setup_agent(hass, config_entry, auth_http)
    runtime = config_entry.runtime_data
    target = target_key("subjects", "anna")
    for language, alias in [("en", "Annie"), ("pl", "Anny")]:
        result = await edit_alias(hass, config_entry, language, target, alias, "anna")
        assert result["type"] == "create_entry"
    assert config_entry.options[CONF_DEFAULT_SUBJECT] == "anna"
    saved = deepcopy(config_entry.options[CONF_ALIASES])
    runtime.coordinator.store.snapshot.subjects["anna"]["name"] = "Renamed"
    resources = catalog(await current_metadata(config_entry))
    mapping = alias_mapping(config_entry.options, resources)
    assert mapping["en:subjects"] == {"anna": ("Annie",)}
    assert mapping["pl:subjects"] == {"anna": ("Anny",)}
    assert config_entry.options[CONF_ALIASES] == saved
    assert config_entry.runtime_data is runtime


async def test_removed_reference_is_excluded_and_can_be_cleared(hass, config_entry, auth_http):
    await setup_agent(hass, config_entry, auth_http)
    target = target_key("subjects", "anna")
    await edit_alias(hass, config_entry, "pl", target, "Anny")
    del config_entry.runtime_data.coordinator.store.snapshot.subjects["anna"]
    assert alias_mapping(config_entry.options, catalog(await current_metadata(config_entry))) == {}
    result = await edit_alias(hass, config_entry, "pl", target, "Anny")
    assert result["errors"] == {"base": "invalid_reference"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"aliases": ""}
    )
    assert result["type"] == "create_entry"
    assert not config_entry.options[CONF_ALIASES]["pl"]


@pytest.mark.parametrize("default", ["missing", "anna"])
async def test_removed_or_unknown_default_requires_repair(hass, config_entry, auth_http, default):
    await setup_agent(hass, config_entry, auth_http)
    del config_entry.runtime_data.coordinator.store.snapshot.subjects["anna"]
    hass.config_entries.async_update_entry(config_entry, options={CONF_DEFAULT_SUBJECT: default})
    result = await voice_form(hass, config_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_DEFAULT_SUBJECT: default, "language": "en"}
    )
    assert result["errors"] == {"base": "invalid_subject"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_DEFAULT_SUBJECT: "", "language": "en"}
    )
    assert result["type"] == "create_entry"
    assert config_entry.options[CONF_DEFAULT_SUBJECT] == ""


async def test_reference_removed_while_alias_form_open(hass, config_entry, auth_http):
    await setup_agent(hass, config_entry, auth_http)
    result = await voice_form(hass, config_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"language": "en", "target": target_key("headache:fields", "severity-id")},
    )
    fields = config_entry.runtime_data.coordinator.store._schemas["schema-1"]["schema"]["fields"]
    fields[:] = [field for field in fields if field["id"] != "severity-id"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"aliases": "intensity"}
    )
    assert result["errors"] == {"base": "invalid_reference"}
    assert CONF_ALIASES not in config_entry.options


@pytest.mark.parametrize("aliases", ["a" * 101, "\n".join(str(i) for i in range(31))])
async def test_invalid_alias_input_is_not_saved(hass, config_entry, auth_http, aliases):
    await setup_agent(hass, config_entry, auth_http)
    result = await edit_alias(hass, config_entry, "en", target_key("subjects", "anna"), aliases)
    assert result["errors"] == {"base": "invalid_alias"}
    assert CONF_ALIASES not in config_entry.options


async def test_metadata_failure_does_not_offer_stale_configuration(hass, config_entry, auth_http):
    await setup_agent(hass, config_entry, auth_http)
    config_entry.runtime_data.coordinator.last_update_success = False
    result = await voice_form(hass, config_entry)
    assert result["type"] == "abort"
    assert result["reason"] == "voice_unavailable"
