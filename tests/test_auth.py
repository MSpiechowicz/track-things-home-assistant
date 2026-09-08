"""Refresh, storage ordering, expiry, and runtime recovery contracts."""

import asyncio
from unittest.mock import Mock

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.track_things.api_errors import AuthenticationError, ServerError
from custom_components.track_things.api_models import Session
from custom_components.track_things.auth import AuthenticatedApi

from .api_fixtures import SESSION, USER
from .auth_fixtures import setup_responses


async def test_concurrent_expiry_persists_before_requests(auth_http):
    auth_http.respond(SESSION)
    for _ in range(8):
        auth_http.respond(USER)
    persisted = []
    async with aiohttp.ClientSession() as http:

        def persist(session):
            # Only refresh has hit the network at the point storage is updated.
            assert auth_http.request.call_count == 1
            persisted.append(session)

        api = AuthenticatedApi(
            "https://backend.example.test",
            http,
            credentials=Session("old-access", "old-refresh", 100),
            persist=persist,
            clock=lambda: 100,
        )
        users = await asyncio.gather(*(api.get_user() for _ in range(8)))
        assert users == [USER] * 8
    assert len(persisted) == 1
    assert auth_http.request.call_args_list[0].kwargs["json"] == {"refresh_token": "old-refresh"}
    assert all(
        call.kwargs["headers"]["Authorization"] == "Bearer sentinel-access"
        for call in auth_http.request.call_args_list[1:]
    )


async def test_access_rejected_refreshes_and_retries_once(auth_http):
    auth_http.respond(status=401)
    auth_http.respond(SESSION)
    auth_http.respond(USER)
    persist = Mock()
    async with aiohttp.ClientSession() as http:
        api = AuthenticatedApi(
            "https://backend.example.test",
            http,
            credentials=Session("old", "refresh", 2000000000),
            persist=persist,
        )
        assert await api.get_user() == USER
    persist.assert_called_once_with(Session(**SESSION))
    assert auth_http.request.call_count == 3


async def test_refresh_rejection_is_latched_and_requests_reauth(auth_http):
    auth_http.respond(status=401)
    failed, persist = Mock(), Mock()
    async with aiohttp.ClientSession() as http:
        api = AuthenticatedApi(
            "https://backend.example.test",
            http,
            credentials=Session("old", "refresh", 1),
            persist=persist,
            auth_failed=failed,
        )
        for _ in range(2):
            with pytest.raises(AuthenticationError):
                await api.get_user()
    failed.assert_called_once()
    persist.assert_not_called()
    assert auth_http.request.call_count == 1


async def test_refresh_outage_preserves_credentials_and_can_recover(auth_http):
    auth_http.respond(status=503)
    auth_http.respond(SESSION)
    auth_http.respond(USER)
    failed, persist = Mock(), Mock()
    original = Session("old", "refresh", 1)
    async with aiohttp.ClientSession() as http:
        api = AuthenticatedApi(
            "https://backend.example.test",
            http,
            credentials=original,
            persist=persist,
            auth_failed=failed,
        )
        with pytest.raises(ServerError):
            await api.get_user()
        assert api.credentials == original
        persist.assert_not_called()
        assert await api.get_user() == USER
    failed.assert_not_called()


async def test_runtime_rotation_survives_reload(hass, config_entry, auth_http):
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, "expires_at": 1}
    )
    auth_http.respond(SESSION)
    setup_responses(auth_http)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert dict(config_entry.data).items() >= SESSION.items()
    assert config_entry.runtime_data.api.credentials == Session(**SESSION)
    setup_responses(auth_http)
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    assert auth_http.request.call_count == 9
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_runtime_outage_retries_without_erasing_config(hass, config_entry, auth_http):
    config_entry.add_to_hass(hass)
    before = dict(config_entry.data)
    for _ in range(3):
        auth_http.respond(status=503)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert config_entry.data == before
    setup_responses(auth_http)
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_runtime_revocation_starts_reauth(hass, config_entry, auth_http):
    config_entry.add_to_hass(hass)
    setup_responses(auth_http)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    auth_http.respond(status=401)
    auth_http.respond(status=401)
    with pytest.raises(AuthenticationError):
        await config_entry.runtime_data.api.get_user()
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == "reauth"
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_late_concurrent_401_uses_already_rotated_session(auth_http):
    """A slow old-token response must not rotate a second time."""
    first = auth_http.respond(status=401)
    second = auth_http.respond(status=401)
    refresh = auth_http.respond(SESSION)
    success = auth_http.respond(USER)
    both_started = asyncio.Event()
    rotated = asyncio.Event()
    old_calls = 0

    async def respond(method, url, **kwargs):
        nonlocal old_calls
        if url.endswith("/auth/refresh"):
            return refresh
        if kwargs["headers"]["Authorization"] == "Bearer old":
            old_calls += 1
            if old_calls == 1:
                await both_started.wait()
                return first
            both_started.set()
            await rotated.wait()
            return second
        return success

    auth_http.request.side_effect = respond
    persist = Mock(side_effect=lambda session: rotated.set())
    async with aiohttp.ClientSession() as http:
        api = AuthenticatedApi(
            "https://backend.example.test",
            http,
            credentials=Session("old", "refresh", 2000000000),
            persist=persist,
        )
        assert await asyncio.gather(api.get_user(), api.get_user()) == [USER, USER]
    persist.assert_called_once()
    assert auth_http.request.call_count == 5


async def test_rotated_access_rejected_does_not_loop(auth_http):
    auth_http.respond(status=401)
    auth_http.respond(SESSION)
    auth_http.respond(status=401)
    failed = Mock()
    async with aiohttp.ClientSession() as http:
        api = AuthenticatedApi(
            "https://backend.example.test",
            http,
            credentials=Session("old", "refresh", 2000000000),
            persist=Mock(),
            auth_failed=failed,
        )
        with pytest.raises(AuthenticationError):
            await api.get_user()
    failed.assert_called_once()
    assert auth_http.request.call_count == 3


async def test_setup_invalid_refresh_enters_reauth(hass, config_entry, auth_http):
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, "expires_at": 1}
    )
    auth_http.respond(status=401)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert len(hass.config_entries.flow.async_progress()) == 1


async def test_setup_rejects_wrong_account(hass, config_entry, auth_http):
    config_entry.add_to_hass(hass)
    auth_http.respond({**USER, "id": "wrong-user"})
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert len(hass.config_entries.flow.async_progress()) == 1
    assert auth_http.request.call_count == 1
