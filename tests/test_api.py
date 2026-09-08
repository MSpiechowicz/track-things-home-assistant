"""Resource contracts, credential handling, and shared-session ownership."""

from copy import deepcopy

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.track_things.api import TrackThingsApi
from custom_components.track_things.api_errors import InvalidResponseError

from .api_fixtures import (
    CREATE,
    ENTRY,
    SCHEMA,
    SESSION,
    SUBJECT,
    TRACKER,
    USER,
    WORKSPACE,
    MockHttp,
)


@pytest.mark.parametrize(
    ("method", "args", "path", "payload"),
    [
        ("get_user", (), "/api/users/me", USER),
        ("get_workspace", ("w",), "/api/workspaces/w", WORKSPACE),
        ("get_tracker", ("w", "t"), "/api/workspaces/w/trackers/t", TRACKER),
        ("get_subject", ("w", "s"), "/api/workspaces/w/subjects/s", SUBJECT),
        (
            "get_schema_version",
            ("w", "t", "v"),
            "/api/workspaces/w/trackers/t/schema-versions/v",
            SCHEMA,
        ),
        ("get_entry", ("w", "e"), "/api/workspaces/w/entries/e", ENTRY),
    ],
)
async def test_resource_contracts(api_http, method, args, path, payload):
    client, http, _, session = api_http
    http.respond(payload)
    result = await getattr(client, method)(*args)
    assert result == payload
    call = http.request.call_args
    assert call.args == ("GET", "https://backend.example.test" + path)
    assert call.kwargs["headers"]["Authorization"] == "Bearer sentinel-access"
    assert call.kwargs["timeout"].total == 7
    assert call.kwargs["allow_redirects"] is False
    assert not session.closed
    assert "Authorization" not in session.headers


async def test_login_and_rotation_are_explicit(api_http):
    client, http, _, _ = api_http
    http.respond(SESSION)
    login = await client.sign_in("synthetic@example.test", "sentinel-password")
    call = http.request.call_args
    assert call.args == ("POST", "https://backend.example.test/auth/password")
    assert call.kwargs["json"] == {
        "identifier": "synthetic@example.test",
        "password": "sentinel-password",
    }
    assert "Authorization" not in call.kwargs["headers"]
    assert "sentinel" not in repr(login)
    http.respond({**SESSION, "access_token": "rotated-access", "refresh_token": "rotated-refresh"})
    rotated = await client.refresh_session(login.refresh_token)
    assert http.request.call_args.args[1].endswith("/auth/refresh")
    assert http.request.call_args.kwargs["json"] == {"refresh_token": "sentinel-refresh"}
    assert "Authorization" not in http.request.call_args.kwargs["headers"]
    assert rotated.refresh_token == "rotated-refresh"
    client.set_access_token(rotated.access_token)
    http.respond(USER)
    await client.get_user()
    assert http.request.call_args.kwargs["headers"]["Authorization"] == "Bearer rotated-access"


@pytest.mark.parametrize("status", [200, 201])
async def test_create_preserves_guard_idempotency_and_values(api_http, status):
    client, http, sleep, _ = api_http
    original = deepcopy(CREATE)
    http.respond(ENTRY, status=status)
    assert await client.create_entry("w", CREATE, idempotency_key="stable-key") == ENTRY
    call = http.request.call_args
    assert call.args == ("POST", "https://backend.example.test/api/workspaces/w/entries")
    assert call.kwargs["headers"]["Idempotency-Key"] == "stable-key"
    assert call.kwargs["json"] == original
    assert CREATE == original
    sleep.assert_not_awaited()


async def test_ha_owned_session_stays_open(hass, monkeypatch):
    http = MockHttp(monkeypatch)
    session = async_get_clientsession(hass)
    headers = dict(session.headers)
    client = TrackThingsApi("https://backend.example.test", session, access_token="sentinel-access")
    http.respond(USER)
    await client.get_user()
    assert not session.closed
    assert session is async_get_clientsession(hass)
    assert dict(session.headers) == headers


@pytest.mark.parametrize(
    "payload", [None, [], {}, {**SESSION, "expires_at": True}, {**SESSION, "access_token": ""}]
)
async def test_malformed_session(api_http, payload):
    client, http, _, _ = api_http
    http.respond(payload)
    with pytest.raises(InvalidResponseError):
        await client.refresh_session("sentinel-refresh")
    assert http.request.call_count == 1


@pytest.mark.parametrize(
    ("method", "args", "payload"),
    [
        ("get_user", (), {**USER, "email": 4}),
        ("get_tracker", ("w", "t"), {**TRACKER, "subjectIds": "subject-1"}),
        ("get_entry", ("w", "e"), {**ENTRY, "values": []}),
        ("get_workspace", ("w",), {**WORKSPACE, "isDefault": 1}),
        (
            "get_schema_version",
            ("w", "t", "s"),
            {**SCHEMA, "schema": {"version": 1, "fields": [{}]}},
        ),
    ],
)
async def test_malformed_resources(api_http, method, args, payload):
    client, http, _, _ = api_http
    http.respond(payload)
    with pytest.raises(InvalidResponseError):
        await getattr(client, method)(*args)


async def test_additional_properties_are_preserved(api_http):
    client, http, _, _ = api_http
    http.respond({**USER, "futureProperty": "preserved"})
    assert (await client.get_user())["futureProperty"] == "preserved"


@pytest.mark.parametrize(
    "base_url", ["ftp://host", "https://secret@host", "https://host?token=secret", "no-host"]
)
async def test_invalid_base_url_is_sanitized(api_http, base_url):
    _, _, _, session = api_http
    with pytest.raises(ValueError) as error:
        TrackThingsApi(base_url, session)
    assert "secret" not in str(error.value)


async def test_id_path_encoding(api_http):
    client, http, _, _ = api_http
    http.respond(SUBJECT)
    await client.get_subject("w", "id/with?characters")
    assert http.request.call_args.args[1].endswith("/subjects/id%2Fwith%3Fcharacters")
    with pytest.raises(ValueError):
        await client.get_subject("w", "..")
