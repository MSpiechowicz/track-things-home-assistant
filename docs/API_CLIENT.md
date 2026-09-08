# Asynchronous API client

`custom_components.track_things.api.TrackThingsApi` implements issue #6's
transport and resource contracts. It does not register a config flow or entities.

Create it with the backend root URL and Home Assistant's shared session:

```python
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from custom_components.track_things.api import TrackThingsApi

client = TrackThingsApi(
    backend_url,
    async_get_clientsession(hass),
    access_token=stored_access_token,
    timeout=15,
)
```

The client never closes the session or changes its default headers. TLS
verification stays enabled; redirects are rejected. A backend hosted under a
path prefix is supported. Base URLs cannot contain credentials, queries or
fragments. Resource IDs are escaped as individual path segments.

## Authentication and reads

`sign_in(identifier, password)` and `refresh_session(refresh_token)` return a
`Session` with `access_token`, `refresh_token` and Unix-seconds `expires_at`.
The credential fields are hidden in its representation. Callers must persist
both rotated tokens together, then call `set_access_token()`. There is no implicit
refresh, persistence, or credential mutation after failed authentication.

Single-resource methods are `get_user`, `get_workspace`, `get_tracker`,
`get_subject`, `get_schema_version`, and `get_entry`. Their typed dictionary models
preserve backend camelCase keys, nullable fields, date strings, `subjectIds`,
historical schema IDs, and dynamic values. Response shapes are checked, including
nested schema fields; unknown future properties are preserved. Dynamic-field
business validation belongs to issue #9.

`list_workspaces`, `list_trackers`, `list_subjects`, `list_schema_versions`, and
`list_entries` return `CursorPage` objects (`items`, `next_cursor`). They always
request `pagination=cursor` with a limit of 1–100; a legacy array is an invalid
response. Corresponding `iter_*` async iterators traverse pages at limit 100,
stop on repeated cursors, and enforce a 1,000-page ceiling. A ceiling failure
raises `InvalidResponseError`; it is never silently reported as completion.

Entry filters use `startDate`, `endDateExclusive`, `timeZone`, `trackerId`, and
`subjectId`. Supply all three date parameters together. Backend validation remains
authoritative for date/timezone values. Iteration snapshots the filters when
iteration begins and preserves them across cursor requests.

## Writes and errors

`create_entry(workspace_id, entry, idempotency_key=...)` sends the caller's JSON
unchanged, including `expectedSchemaVersionId` and `clientMutationId`, with the
optional `Idempotency-Key` header. Both 201 creation and 200 replay responses
return the same `Entry` model. There are no entry edit/delete methods.

POSTs, including login and refresh, are attempted exactly once. A timeout or
transport failure can leave an unknown write outcome; callers must reconcile it
using their saved payload/key and explicit confirmation state. Do not generate a
new idempotency key when reconciling an uncertain entry creation.

GETs retry connection failures, timeouts, 429 and 5xx, by default twice after the
initial attempt. Local backoff is 1 then 2 seconds. Both numeric and HTTP-date
`Retry-After` values are supported. If the requested delay exceeds the configured
maximum (30 seconds by default), the client returns the typed error immediately
instead of retrying earlier than permitted. Retries can be disabled, or configured
up to five; the maximum retry delay can be configured up to 60 seconds. Each HTTP
attempt has its own total timeout. Responses are released before backoff and
cancellation propagates immediately.

`api_errors` exposes authentication (401), permission (403), not-found (404),
conflict (409), rate-limit (429), server (5xx), timeout, transport and malformed
response errors. Errors retain only status, a known machine code, and retry delay.
The schema-change/unavailable and idempotency conflict codes remain distinct.
Unknown server codes, messages, URLs, headers and bodies are not exposed in error
text, and the client does not log requests or responses. Resource dictionaries
contain private data and must not be logged by callers.

## Contract sources and offline verification

Wire shapes and routes were checked against the owning backend's
`src/api/shared/serializers.ts`, resource routes and `src/openapi/*`, including
refresh, calendar filtering, schema guard, and idempotency contracts.
Session injection follows the [Home Assistant developer guide](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/inject-websession/);
request timeout and response lifecycle follow [aiohttp's client reference](https://docs.aiohttp.org/en/stable/client_reference.html).

Run from the repository test environment:

```sh
python -m pytest -q tests/test_api.py tests/test_api_errors.py tests/test_api_pagination.py
python -m ruff check .
python -m ruff format --check .
python scripts/check_file_sizes.py
python -m pytest -q
```

The HTTP boundary is mocked and pytest disables outbound sockets. Fixtures use
synthetic identities and sentinel credentials/content. The focused suite replays
all resources, Unicode entry values, token rotation, cursor traversal and filters,
malformed responses, errors, cancellation, retry bounds, and POST single attempts.
It inspects sanitized exception text/tracebacks and captured logs for sentinel
secrets, and verifies that the actual HA-owned shared session remains open.
No live backend or device check is required for this client module.
