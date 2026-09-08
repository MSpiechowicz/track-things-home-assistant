"""Durable backend contract replay at the actual HTTP boundary, with no live writes."""

import asyncio
import json
from copy import deepcopy
from unittest.mock import Mock, patch
from uuid import UUID

import aiohttp
import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .api_fixtures import ENTRY, SUBJECT, TRACKER
from .create_entry_fixtures import DATA, create, setup_writer

pytestmark = pytest.mark.usefixtures("freezer")


def idempotent_sink(http, *, lose_first=False):
    """Model the backend's account/workspace key ledger, not a HA result cache."""
    ledger = {}
    writes = []

    async def request(method, url, **kwargs):
        if method == "GET":
            return http.respond(TRACKER if "/trackers/" in url else SUBJECT)
        key = kwargs["headers"]["Idempotency-Key"]
        fingerprint = json.dumps(kwargs["json"], sort_keys=True)
        if key in ledger:
            previous, result = ledger[key]
            if fingerprint != previous:
                return http.respond({"error": {"code": "idempotency_conflict"}}, status=409)
            return http.respond(result)
        result = {**ENTRY, **deepcopy(kwargs["json"])}
        ledger[key] = fingerprint, result
        writes.append(result)
        if lose_first and len(writes) == 1:
            raise aiohttp.ServerDisconnectedError("sentinel-private-transport")
        return http.respond(result, status=201)

    http.request.side_effect = request
    return writes


async def test_lost_response_identical_retry_then_changed_payload(hass, config_entry, auth_http):
    await setup_writer(hass, config_entry, auth_http)
    writes = idempotent_sink(auth_http, lose_first=True)
    notified = Mock()
    remove = config_entry.runtime_data.coordinator.async_add_listener(notified)
    with pytest.raises(HomeAssistantError, match=DATA["request_id"]):
        await create(hass, config_entry)
    assert len(writes) == 1
    notified.assert_not_called()
    first = await create(hass, config_entry)
    second = await create(hass, config_entry)
    assert first == second
    assert first["request_id"] == DATA["request_id"]
    assert len(writes) == 1
    assert notified.call_count == 2
    with pytest.raises(ServiceValidationError, match="conflicts"):
        await create(hass, config_entry, {**DATA, "values": {"severity": 7}})
    assert len(writes) == 1
    assert notified.call_count == 2
    posts = [c for c in auth_http.request.call_args_list if c.args[0] == "POST"]
    assert len(posts) == 4
    assert {c.kwargs["headers"]["Idempotency-Key"] for c in posts} == {DATA["request_id"]}
    remove()


async def test_generated_key_is_recoverable_after_lost_response(hass, config_entry, auth_http):
    await setup_writer(hass, config_entry, auth_http)
    writes = idempotent_sink(auth_http, lose_first=True)
    data = {k: v for k, v in DATA.items() if k != "request_id"}
    with pytest.raises(HomeAssistantError) as error:
        await create(hass, config_entry, data)
    key = str(error.value).split("request_id=")[1]
    assert UUID(key).version == 4
    result = await create(hass, config_entry, {**data, "request_id": key})
    assert result["request_id"] == key
    assert len(writes) == 1


async def test_concurrent_identical_calls_keep_one_key(hass, config_entry, auth_http):
    await setup_writer(hass, config_entry, auth_http)
    writes = idempotent_sink(auth_http)
    results = await asyncio.gather(create(hass, config_entry), create(hass, config_entry))
    assert results[0] == results[1]
    assert len(writes) == 1


async def test_success_invalidates_existing_calendar_cache(hass, config_entry, auth_http):
    from .calendar_fixtures import setup_calendar

    await setup_calendar(hass, config_entry, auth_http)
    query = config_entry.runtime_data.calendar
    assert query._cache
    idempotent_sink(auth_http)
    # Observe synchronous invalidation separately from the entity's scheduled read.
    from homeassistant.components.calendar.const import DATA_COMPONENT

    entity = next(iter(hass.data[DATA_COMPONENT].entities))
    with patch.object(entity, "async_schedule_update_ha_state") as refresh:
        await create(hass, config_entry)
    assert not query._cache
    refresh.assert_called_once_with(force_refresh=True)
