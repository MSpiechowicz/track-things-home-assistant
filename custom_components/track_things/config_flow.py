"""Password login, explicit workspace selection, and same-account reauthentication."""

import json
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import TrackThingsApi
from .api_errors import ApiError, AuthenticationError
from .api_models import User, Workspace
from .auth import AuthenticatedApi, normalize_backend_url, session_data
from .const import DOMAIN

LOGIN_FIELDS = {
    vol.Required("identifier"): str,
    vol.Required("password"): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
}


class TrackThingsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a backend/account/workspace instance without retaining passwords."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._workspaces: dict[str, Workspace] = {}
        self._user: User | None = None

    async def _login(self, user_input: dict[str, Any]) -> None:
        api = TrackThingsApi(self._data["backend_url"], async_get_clientsession(self.hass))
        credentials = await api.sign_in(user_input["identifier"], user_input["password"])
        self._data.update(session_data(credentials))
        client = AuthenticatedApi(
            self._data["backend_url"],
            async_get_clientsession(self.hass),
            credentials=credentials,
            persist=lambda rotated: self._data.update(session_data(rotated)),
        )
        await client.sync_user()
        self._user = await client.get_user()
        self._workspaces = {
            workspace["id"]: workspace async for workspace in client.iter_workspaces()
        }

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            self._data = {}
            try:
                self._data = {
                    "backend_url": normalize_backend_url(
                        user_input["backend_url"], user_input.get("allow_local_http", False)
                    ),
                    "allow_local_http": user_input.get("allow_local_http", False),
                }
                await self._login(user_input)
            except ValueError:
                errors["base"] = "invalid_url"
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except ApiError:
                errors["base"] = "cannot_connect"
            else:
                if not self._workspaces:
                    return self.async_abort(reason="no_workspaces")
                return await self.async_step_workspace()
            self._data = {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("backend_url"): str,
                    **LOGIN_FIELDS,
                    vol.Optional("allow_local_http", default=False): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_workspace(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            workspace_id = user_input["workspace_id"]
            if workspace_id not in self._workspaces:
                errors["base"] = "invalid_workspace"
            else:
                assert self._user is not None
                unique_id = json.dumps(
                    [self._data["backend_url"], self._user["id"], workspace_id],
                    separators=(",", ":"),
                )
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=self._workspaces[workspace_id]["name"],
                    data={**self._data, "user_id": self._user["id"], "workspace_id": workspace_id},
                )
        return self.async_show_form(
            step_id="workspace",
            data_schema=vol.Schema(
                {
                    vol.Required("workspace_id"): vol.In(
                        {key: workspace["name"] for key, workspace in self._workspaces.items()}
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            entry = self._get_reauth_entry()
            self._data = {
                "backend_url": entry.data["backend_url"],
                "allow_local_http": entry.data.get("allow_local_http", False),
            }
            try:
                await self._login(user_input)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except ApiError:
                errors["base"] = "cannot_connect"
            else:
                assert self._user is not None
                if self._user["id"] != entry.data["user_id"]:
                    errors["base"] = "wrong_account"
                elif entry.data["workspace_id"] not in self._workspaces:
                    errors["base"] = "workspace_unavailable"
                else:
                    return self.async_update_reload_and_abort(entry, data_updates=self._data)
            self._data = {}
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=vol.Schema(LOGIN_FIELDS), errors=errors
        )
