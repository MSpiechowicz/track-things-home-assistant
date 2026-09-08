"""Reauthentication retains backend, account, workspace, and entry identity."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH

from custom_components.track_things.const import DOMAIN

from .api_fixtures import SESSION, USER
from .auth_fixtures import LOGIN, login_responses


async def start(hass, entry):
    entry.add_to_hass(hass)
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id}, data=entry.data
    )


async def test_reauth_updates_session_and_reloads_same_entry(hass, config_entry, auth_http):
    result = await start(hass, config_entry)
    assert result["step_id"] == "reauth_confirm"
    rotated = {**SESSION, "access_token": "new-access", "refresh_token": "new-refresh"}
    login_responses(auth_http, credentials=rotated)
    before = dict(config_entry.data)
    with patch.object(hass.config_entries, "async_reload", return_value=True) as reload:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"identifier": LOGIN["identifier"], "password": LOGIN["password"]}
        )
        await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    reload.assert_called_once_with(config_entry.entry_id)
    assert config_entry.data == {**before, **rotated}
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


@pytest.mark.parametrize(
    ("user", "workspaces", "error"),
    [({**USER, "id": "wrong-user"}, None, "wrong_account"), (USER, [], "workspace_unavailable")],
)
async def test_reauth_rejects_identity_or_access_change(
    hass, config_entry, auth_http, user, workspaces, error
):
    result = await start(hass, config_entry)
    before = dict(config_entry.data)
    login_responses(auth_http, user=user, workspaces=workspaces)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"identifier": LOGIN["identifier"], "password": LOGIN["password"]}
    )
    assert result["errors"] == {"base": error}
    assert config_entry.data == before
    assert "sentinel-password" not in str(result)


@pytest.mark.parametrize(("status", "error"), [(401, "invalid_auth"), (503, "cannot_connect")])
async def test_reauth_error_keeps_config(hass, config_entry, auth_http, status, error):
    result = await start(hass, config_entry)
    before = dict(config_entry.data)
    auth_http.respond(status=status)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"identifier": LOGIN["identifier"], "password": LOGIN["password"]}
    )
    assert result["errors"] == {"base": error}
    assert config_entry.data == before
