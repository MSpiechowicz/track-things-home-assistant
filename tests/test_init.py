"""Exercise the scaffold through Home Assistant's actual loader and lifecycle."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.track_things.const import DOMAIN


async def test_yaml_setup(hass: HomeAssistant) -> None:
    """The documented empty YAML loads the real custom component."""
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: {}})
    assert DOMAIN in hass.config.components
    integration = await async_get_integration(hass, DOMAIN)
    assert not integration.is_built_in
    assert integration.version == "0.1.0"
    assert DOMAIN not in hass.services.async_services()
    assert hass.states.async_entity_ids(DOMAIN) == []


async def test_yaml_rejects_unknown_settings(hass: HomeAssistant) -> None:
    """The scaffold must not silently accept account settings it cannot use yet."""
    assert not await async_setup_component(hass, DOMAIN, {DOMAIN: {"token": "unused"}})


async def test_entry_setup_reload_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Real config-entry transitions succeed without owning background resources."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert DOMAIN not in hass.data
    assert DOMAIN not in hass.services.async_services()
    assert hass.states.async_entity_ids(DOMAIN) == []


async def test_entries_unload_independently(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Unloading one future account/workspace must not unload another entry."""
    other = MockConfigEntry(domain=DOMAIN, title="Another workspace", data={})
    for entry in (config_entry, other):
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert other.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(other.entry_id)
