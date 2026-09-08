"""Exercise the scaffold through Home Assistant's actual loader and lifecycle."""

import tomllib
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.track_things.const import DOMAIN

from .auth_fixtures import ENTRY_DATA, setup_responses


@pytest.fixture
def package_version() -> str:
    """Read the current package version outside the running event loop."""
    root = Path(__file__).resolve().parents[1]
    return tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]


async def test_yaml_setup(hass: HomeAssistant, package_version: str) -> None:
    """The documented empty YAML loads the real custom component."""
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: {}})
    assert DOMAIN in hass.config.components
    integration = await async_get_integration(hass, DOMAIN)
    assert not integration.is_built_in
    assert integration.version == package_version
    assert set(hass.services.async_services()[DOMAIN]) == {"get_daily_calendar", "refresh"}
    assert hass.states.async_entity_ids(DOMAIN) == []


async def test_yaml_rejects_unknown_settings(hass: HomeAssistant) -> None:
    """The scaffold must not silently accept account settings it cannot use yet."""
    assert not await async_setup_component(hass, DOMAIN, {DOMAIN: {"token": "unused"}})


async def test_entry_setup_reload_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry, auth_http
) -> None:
    """Real config-entry transitions succeed without owning background resources."""
    setup_responses(auth_http)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    previous = config_entry.runtime_data
    setup_responses(auth_http)
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    current = config_entry.runtime_data
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    with pytest.raises(RuntimeError, match="unloaded"):
        await previous.api.get_user()
    with pytest.raises(RuntimeError, match="unloaded"):
        await current.api.get_user()
    assert DOMAIN not in hass.data
    assert set(hass.services.async_services()[DOMAIN]) == {"get_daily_calendar", "refresh"}
    assert hass.states.async_entity_ids(DOMAIN) == []


async def test_entries_unload_independently(
    hass: HomeAssistant, config_entry: MockConfigEntry, auth_http
) -> None:
    """Unloading one future account/workspace must not unload another entry."""
    other = MockConfigEntry(domain=DOMAIN, title="Another workspace", data=ENTRY_DATA)
    for entry in (config_entry, other):
        setup_responses(auth_http)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert other.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(other.entry_id)
