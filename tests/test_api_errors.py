"""Safe typed failures, retry limits, cancellation and unknown write outcomes."""

import asyncio
import traceback
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import call

import aiohttp
import pytest

from custom_components.track_things.api_errors import (
    ApiError,
    ApiTimeoutError,
    AuthenticationError,
    ConflictError,
    InvalidResponseError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    TransportError,
)

from .api_fixtures import CREATE, USER


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (400, ApiError),
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (409, ConflictError),
        (429, RateLimitError),
        (500, ServerError),
        (503, ServerError),
        (302, ApiError),
    ],
)
async def test_status_mapping_and_redaction(api_http, caplog, status, error_type):
    client, http, sleep, _ = api_http
    for _ in range(3):
        http.respond(
            {"error": {"code": "sentinel-secret", "message": "sentinel-body"}}, status=status
        )
    with pytest.raises(error_type) as caught:
        await client.get_user()
    assert caught.value.status == status
    assert caught.value.code == "request_failed"
    assert "sentinel" not in str(caught.value) + repr(caught.value) + caplog.text
    expected = 3 if status in {429, 500, 503} else 1
    assert http.request.call_count == expected
    assert sleep.await_count == expected - 1


@pytest.mark.parametrize(
    "code", ["tracker_schema_changed", "tracker_schema_unavailable", "idempotency_conflict"]
)
async def test_known_conflicts_remain_distinguishable(api_http, code):
    client, http, _, _ = api_http
    http.respond({"error": {"code": code, "message": "sentinel"}}, status=409)
    with pytest.raises(ConflictError) as caught:
        await client.create_entry("w", CREATE, idempotency_key="key")
    assert caught.value.code == code
    assert http.request.call_count == 1


@pytest.mark.parametrize(("header", "delay"), [("4", 4), ("0", 0), ("garbage", 1), ("NaN", 1)])
async def test_retry_after_and_response_release(api_http, header, delay):
    client, http, sleep, _ = api_http
    response = http.respond({}, status=429, headers={"Retry-After": header})
    http.respond(USER)

    async def inspect_release(seconds):
        assert seconds == delay
        response.__aexit__.assert_awaited_once()

    sleep.side_effect = inspect_release
    assert await client.get_user() == USER
    sleep.assert_awaited_once_with(delay)


async def test_http_date_retry_after(api_http):
    client, http, sleep, _ = api_http
    future = format_datetime(datetime.now(UTC) + timedelta(seconds=10), usegmt=True)
    http.respond({}, status=503, headers={"Retry-After": future})
    http.respond(USER)
    await client.get_user()
    assert 8 <= sleep.call_args.args[0] <= 10


async def test_long_retry_after_returns_without_retrying_early(api_http):
    client, http, sleep, _ = api_http
    http.respond({}, status=429, headers={"Retry-After": "3600"})
    with pytest.raises(RateLimitError) as caught:
        await client.get_user()
    assert caught.value.retry_after == 3600
    assert http.request.call_count == 1
    sleep.assert_not_awaited()


async def test_retry_bound_and_backoff(api_http):
    client, http, sleep, _ = api_http
    for _ in range(3):
        http.fail(aiohttp.ClientConnectionError("sentinel-secret"))
    with pytest.raises(TransportError) as caught:
        await client.get_user()
    assert caught.value.__context__ is None
    assert "sentinel-secret" not in "".join(traceback.format_exception(caught.value))
    assert http.request.call_count == 3
    assert sleep.await_args_list == [call(1), call(2)]


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("sign_in", ("user", "sentinel-password")),
        ("refresh_session", ("sentinel-refresh",)),
        ("create_entry", ("w", CREATE)),
    ],
)
@pytest.mark.parametrize("failure", ["timeout", "connection", "server", "rate_limit"])
async def test_post_is_never_retried(api_http, method, args, failure):
    client, http, sleep, _ = api_http
    if failure == "timeout":
        http.fail(TimeoutError("sentinel-secret"))
        expected = ApiTimeoutError
    elif failure == "connection":
        http.fail(aiohttp.ClientConnectionError("sentinel-secret"))
        expected = TransportError
    else:
        http.respond({}, status=503 if failure == "server" else 429)
        expected = ServerError if failure == "server" else RateLimitError
    with pytest.raises(expected):
        await getattr(client, method)(*args)
    assert http.request.call_count == 1
    sleep.assert_not_awaited()


async def test_read_timeout_can_recover(api_http):
    client, http, sleep, _ = api_http
    http.fail(TimeoutError())
    http.respond(USER)
    assert await client.get_user() == USER
    sleep.assert_awaited_once_with(1)


async def test_cancelled_requests_are_not_retried(api_http):
    client, http, sleep, _ = api_http
    http.fail(asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await client.get_user()
    sleep.assert_not_awaited()


async def test_malformed_json_does_not_leak_or_retry(api_http, caplog):
    client, http, sleep, _ = api_http
    http.respond(error=ValueError("sentinel-body"))
    with pytest.raises(InvalidResponseError) as caught:
        await client.get_user()
    assert caught.value.__context__ is None
    assert "sentinel-body" not in "".join(traceback.format_exception(caught.value)) + caplog.text
    assert http.request.call_count == 1
    sleep.assert_not_awaited()


async def test_html_auth_error_still_maps_status(api_http):
    client, http, _, _ = api_http
    http.respond(status=401, error=ValueError("html"))
    with pytest.raises(AuthenticationError):
        await client.get_user()
