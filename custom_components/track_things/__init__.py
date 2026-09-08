"""Load a password-authenticated Track Things account/workspace instance."""

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api_decode import decode_session
from .api_errors import ApiError, AuthenticationError, NotFoundError, PermissionDeniedError
from .auth import AuthenticatedApi, normalize_backend_url, session_data
from .const import DOMAIN

CONFIG_SCHEMA = vol.Schema({vol.Optional(DOMAIN): vol.Schema({})}, extra=vol.ALLOW_EXTRA)
type TrackThingsConfigEntry = ConfigEntry[AuthenticatedApi]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Allow empty YAML for installation smoke checks; accounts use the UI."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TrackThingsConfigEntry) -> bool:
    """Restore credentials, validate identity/access, and expose the runtime client."""
    client = AuthenticatedApi(
        normalize_backend_url(entry.data["backend_url"], entry.data.get("allow_local_http", False)),
        async_get_clientsession(hass),
        credentials=decode_session(dict(entry.data)),
        persist=lambda session: hass.config_entries.async_update_entry(
            entry, data={**entry.data, **session_data(session)}
        ),
        auth_failed=lambda: entry.async_start_reauth(hass),
    )
    try:
        user = await client.get_user()
        if user["id"] != entry.data["user_id"]:
            raise AuthenticationError(code="invalid_session")
        await client.get_workspace(entry.data["workspace_id"])
    except (AuthenticationError, PermissionDeniedError, NotFoundError) as err:
        client.close()
        raise ConfigEntryAuthFailed("Account or workspace access must be restored") from err
    except ApiError as err:
        client.close()
        raise ConfigEntryNotReady("Track Things is temporarily unavailable") from err
    entry.runtime_data = client
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TrackThingsConfigEntry) -> bool:
    """Disable the client without closing HA's shared session or retaining tasks."""
    entry.runtime_data.close()
    return True
