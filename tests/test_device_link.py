"""Browser account linking through HA's actual progress flow."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.track_things.api_errors import InvalidResponseError
from custom_components.track_things.device_link import DEFAULT_BACKEND_URL, validate_authorization

from .api_fixtures import SESSION, USER, WORKSPACE

AUTHORIZATION = {
    "device_code": "ttd_" + "a" * 64,
    "user_code": "ABCDE-23456",
    "verification_uri": "https://track-things.com/connect/home-assistant",
    "interval": 5,
    "expires_in": 600,
}


async def start(hass, http):
    result = await hass.config_entries.flow.async_init(
        "track_things", context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["link", "advanced"]
    http.respond(AUTHORIZATION)
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "link"}
    )


async def finish_poll(hass, flow_id):
    flow = hass.config_entries.flow._progress[flow_id]
    await flow._link_task
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(flow_id)
    if result["type"] is FlowResultType.SHOW_PROGRESS_DONE:
        result = await hass.config_entries.flow.async_configure(flow_id)
    return result


def approved(http, user=USER, workspaces=None):
    http.respond({"status": "approved", "session": SESSION})
    http.respond(user)
    http.respond(user)
    http.respond(
        {"items": workspaces if workspaces is not None else [WORKSPACE], "nextCursor": None}
    )


async def test_default_browser_setup_preserves_only_session_and_workspace(hass, auth_http, caplog):
    with patch("custom_components.track_things.device_link.sleep", new=AsyncMock()):
        # Responses are queued before yielding to the progress task.
        result = await start(hass, auth_http)
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        assert result["description_placeholders"]["user_code"] == AUTHORIZATION["user_code"]
        assert AUTHORIZATION["device_code"] not in str(result)
        approved(auth_http)
        result = await finish_poll(hass, result["flow_id"])
    assert result["step_id"] == "workspace"
    with patch("custom_components.track_things.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"workspace_id": WORKSPACE["id"]}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["backend_url"] == DEFAULT_BACKEND_URL
    assert result["data"]["auth_method"] == "device"
    assert "password" not in result["data"]
    assert "device_code" not in result["data"]
    assert "user_code" not in result["data"]
    assert AUTHORIZATION["device_code"] not in caplog.text
    assert all(
        call.args[1].startswith(DEFAULT_BACKEND_URL) for call in auth_http.request.call_args_list
    )


@pytest.mark.parametrize("status,reason", [("denied", "link_denied"), ("expired", "link_expired")])
async def test_denial_and_expiry_create_no_entry(hass, auth_http, status, reason):
    with patch("custom_components.track_things.device_link.sleep", new=AsyncMock()):
        result = await start(hass, auth_http)
        auth_http.respond({"status": status})
        result = await finish_poll(hass, result["flow_id"])
    assert result["reason"] == reason
    assert not hass.config_entries.async_entries("track_things")


async def test_poll_pending_slowdown_and_recovery(hass, auth_http):
    with patch("custom_components.track_things.device_link.sleep", new=AsyncMock()) as sleep:
        result = await start(hass, auth_http)
        auth_http.respond({"status": "pending"})
        auth_http.respond({"status": "slow_down"})
        auth_http.respond({}, status=503)
        approved(auth_http)
        result = await finish_poll(hass, result["flow_id"])
    assert result["step_id"] == "workspace"
    assert [call.args[0] for call in sleep.call_args_list] == [5, 5, 10, 10]
    hass.config_entries.flow.async_abort(result["flow_id"])


async def test_abort_cancels_poll_and_prevents_more_requests(hass, auth_http):
    result = await start(hass, auth_http)
    flow = hass.config_entries.flow._progress[result["flow_id"]]
    task = flow._link_task
    await asyncio.sleep(0)
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()
    assert task.cancelled()
    assert auth_http.request.call_count == 1


@pytest.mark.parametrize("wrong_account", [True, False])
async def test_reauth_keeps_original_account_and_workspace(
    hass, config_entry, auth_http, wrong_account
):
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, "auth_method": "device"}
    )
    before = dict(config_entry.data)
    result = await hass.config_entries.flow.async_init(
        "track_things",
        context={"source": SOURCE_REAUTH, "entry_id": config_entry.entry_id},
        data=config_entry.data,
    )
    assert result["step_id"] == "reauth_link"
    auth_http.respond(
        {**AUTHORIZATION, "verification_uri": "https://track-things.com/connect/home-assistant"}
    )
    with patch("custom_components.track_things.device_link.sleep", new=AsyncMock()):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        approved(auth_http, user={**USER, "id": "other"} if wrong_account else USER, workspaces=[])
        result = await finish_poll(hass, result["flow_id"])
    assert result["reason"] == ("wrong_account" if wrong_account else "workspace_unavailable")
    assert config_entry.data == before


@pytest.mark.parametrize(
    "changes",
    [
        {"verification_uri": "https://evil.example/connect"},
        {"verification_uri": "javascript:alert(1)"},
        {"device_code": "secret"},
        {"user_code": "[click](https://evil.example)"},
        {"interval": 0},
        {"expires_in": 999999},
        {"expires_in": True},
    ],
)
def test_untrusted_authorization_is_rejected(changes):
    with pytest.raises((InvalidResponseError, ValueError)):
        validate_authorization({**AUTHORIZATION, **changes}, DEFAULT_BACKEND_URL, False)


async def test_reauth_success_updates_same_entry(hass, config_entry, auth_http):
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, "auth_method": "device", "access_token": "old"}
    )
    result = await hass.config_entries.flow.async_init(
        "track_things",
        context={"source": SOURCE_REAUTH, "entry_id": config_entry.entry_id},
        data=config_entry.data,
    )
    auth_http.respond(AUTHORIZATION)
    with (
        patch("custom_components.track_things.device_link.sleep", new=AsyncMock()),
        patch.object(hass.config_entries, "async_reload", new=AsyncMock()) as reload,
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        approved(auth_http)
        result = await finish_poll(hass, result["flow_id"])
        await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["access_token"] == SESSION["access_token"]
    assert config_entry.data["workspace_id"] == WORKSPACE["id"]
    assert config_entry.data["user_id"] == USER["id"]
    reload.assert_awaited_once_with(config_entry.entry_id)


async def test_poll_timeout_aborts_without_entry(hass, auth_http):
    with patch("custom_components.track_things.device_link.sleep", side_effect=TimeoutError):
        result = await start(hass, auth_http)
        result = await finish_poll(hass, result["flow_id"])
    assert result["reason"] == "link_expired"
    assert not hass.config_entries.async_entries("track_things")
