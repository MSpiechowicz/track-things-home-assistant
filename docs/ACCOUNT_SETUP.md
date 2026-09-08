# Account setup and reauthentication

Install the integration and restart Home Assistant. In Settings → Devices &
services → Add integration, choose Track Things. Enter the backend HTTPS URL
(including any deployment path prefix), email/username, and password. The flow
exchanges the password, calls `POST /api/users/sync`, reads `GET /api/users/me`,
and paginates accessible workspaces. Choose a workspace explicitly, including
when only one is available. English and Polish forms are included in the package.

For a disposable development backend only, enable “Allow HTTP for local
development” and use localhost, a private IP, or a `.local` hostname. Public
HTTP, URLs containing credentials, query parameters, and fragments are rejected
before sending a password. HTTPS remains the default.

A config entry represents one normalized backend URL, account ID, and workspace
ID. Repeating that combination aborts without replacing its credentials.
Different account/workspace combinations remain independent. The integration
stores access token, refresh token, and Unix expiry together using Home
Assistant's config-entry storage. It does not retain passwords or identifiers
in entry data, and does not log credentials. Protect Home Assistant's normal
configuration storage and backups, which contain session credentials.

`entry.runtime_data` is the authenticated API client. Requests refresh at expiry
(with a 30-second margin), or once after an HTTP 401. Concurrent refresh callers
share a lock and check the session revision again. The rotated pair is submitted
to Home Assistant's config-entry storage before subsequent authenticated
requests; Home Assistant performs its normal deferred disk save. No integration
refresh timer or background task is needed. A process crash before that deferred
save may require reauthentication; config-entry storage is not a synchronous
filesystem transaction.

Invalid refresh credentials start reauthentication and prevent repeated refresh
attempts. Temporary errors preserve entry data and permit retry. Setup outages
use Home Assistant's retry state. Reauthentication requires the original account
and access to the original workspace; successful reauthentication updates and
reloads the same entry. Unload disables the old client and leaves Home Assistant's
shared HTTP session open. Reload restores the latest saved credentials.

## Verification

Run from the repository's Python test environment:

```sh
python -m pytest -q tests/test_config_flow.py tests/test_auth.py tests/test_reauth.py tests/test_init.py
python -m ruff check .
python -m ruff format --check .
python scripts/check_file_sizes.py
python -m pytest -q
```

The offline fixture replay exercises the real Home Assistant flow manager and
loader with mocked aiohttp responses: password exchange → user sync → profile →
workspace selection; expiry → one refresh → authenticated requests; revocation
→ reauthentication; wrong account rejection; outage → retry; and reload/unload.
Synthetic sentinels check that logs, form responses, and persisted entry data do
not contain the password. No backend, Google speaker, or microphone is involved.

The live acceptance walkthrough requires a disposable Home Assistant instance,
a local test backend/Supabase, and disposable account credentials:

1. Add the integration and select the test workspace; expect one loaded entry.
2. Wait across token expiry and make an authenticated read; expect success
   without login and rotated credentials in config-entry storage.
3. Revoke the refresh session, repeat the read, and complete reauthentication;
   expect the same entry/account/workspace to reload.
4. Stop the backend and restart HA; expect setup retry with entry data preserved.
   Restore the backend and verify recovery. Unload/reload the integration.

Live account/expiry/revocation UI checks were not run in the implementation
workspace: no disposable backend/account was supplied. Automated fixture results
are recorded in the PR and do not claim a live Supabase or browser walkthrough.
