"""Exercise account setup through Home Assistant's actual flow manager."""

import json
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.track_things.auth import normalize_backend_url
from custom_components.track_things.const import DOMAIN

from .api_fixtures import WORKSPACE
from .auth_fixtures import ENTRY_DATA, LOGIN, login_responses


async def start(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "advanced"}
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "password"}
    )


async def test_setup_workspace_selection_and_secrets(hass, auth_http, caplog):
    result = await start(hass)
    assert result["step_id"] == "password"
    login_responses(auth_http, workspaces=[WORKSPACE, {**WORKSPACE, "id": "workspace-2"}])
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["step_id"] == "workspace"
    assert len(auth_http.request.call_args_list) == 4
    assert [call.args[1].split(".test")[-1] for call in auth_http.request.call_args_list] == [
        "/auth/password",
        "/api/users/sync",
        "/api/users/me",
        "/api/workspaces",
    ]
    with patch("custom_components.track_things.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"workspace_id": "workspace-2"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {**ENTRY_DATA, "workspace_id": "workspace-2"}
    assert "password" not in json.dumps(result["data"])
    assert "identifier" not in result["data"]
    for secret in ("sentinel-password", "sentinel-access", "sentinel-refresh"):
        assert secret not in caplog.text


async def test_duplicate_normalized_backend_account_workspace(hass, auth_http):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id=json.dumps(
            [ENTRY_DATA["backend_url"], "user-1", "workspace-1"], separators=(",", ":")
        ),
    )
    entry.add_to_hass(hass)
    result = await start(hass)
    login_responses(auth_http)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"workspace_id": "workspace-1"}
    )
    assert result["reason"] == "already_configured"
    assert entry.data == ENTRY_DATA


@pytest.mark.parametrize(
    ("status", "error"), [(401, "invalid_auth"), (503, "cannot_connect"), (429, "cannot_connect")]
)
async def test_login_failures(hass, auth_http, status, error, caplog):
    result = await start(hass)
    auth_http.respond({"message": "sentinel-password"}, status=status)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["errors"] == {"base": error}
    assert "sentinel-password" not in str(result)
    assert "sentinel-password" not in caplog.text
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_no_workspaces(hass, auth_http):
    result = await start(hass)
    login_responses(auth_http, workspaces=[])
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["reason"] == "no_workspaces"


@pytest.mark.parametrize(
    "url",
    [
        "http://backend.example.test",
        "https://user:secret@example.test",
        "https://example.test?token=secret",
        "https://example.test/#secret",
        "not-a-url",
    ],
)
async def test_invalid_url_does_not_send_credentials(hass, auth_http, url):
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**LOGIN, "backend_url": url}
    )
    assert result["errors"] == {"base": "invalid_url"}
    auth_http.request.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://192.168.1.10",
        "http://[::1]:8000",
        "http://backend.local",
    ],
)
def test_http_requires_explicit_local_opt_in(url):
    with pytest.raises(ValueError):
        normalize_backend_url(url)
    assert normalize_backend_url(url, True) == url


def test_public_http_remains_forbidden():
    with pytest.raises(ValueError):
        normalize_backend_url("http://backend.example.test", True)
