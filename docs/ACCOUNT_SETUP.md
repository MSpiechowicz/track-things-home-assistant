# Account setup and reauthentication

Install the integration and restart Home Assistant. In **Settings → Devices &
services → Add integration → Track Things**, choose **Connect with your Track
Things account**. The integration automatically uses `https://api.track-things.com`.
No backend URL or Track Things password is needed for this setup.

1. Keep the Home Assistant setup window open and follow its Track Things link.
2. Sign in using **Google, GitHub**, or your usual Track Things sign-in method.
   Use the account that owns or has access to your workspace.
3. Enter the code shown in Home Assistant. Confirm that it matches and approve
   the connection you started. Codes expire after ten minutes.
4. Return to Home Assistant and choose your workspace, even if only one is
   available. English and Polish setup forms are included.

The browser approval grants a separate Home Assistant session. Your provider
password, OAuth client secret, and browser refresh token are never copied to HA.
The connection can read accessible workspace resources and create entries using
existing account permissions. Workspace selection controls this integration
instance; the token can access other workspaces available to the same account.
To revoke access, open **Account → Security → Manage Home Assistant connections**
on Track Things, or visit `/connect/home-assistant`. Refresh the connection list
if an approval has only just completed. Revocation invalidates both device tokens.
Existing password-based entries keep working and use their existing reauth flow.

**Advanced setup** offers a custom backend or a Track Things password login.
SSO users do not need to create a password. Custom-server linking requires both
the backend device endpoints and the corresponding frontend approval page; see
[the backend deployment guide](https://github.com/MSpiechowicz/track-things-backend/blob/main/docs/HOME_ASSISTANT_LINKING.md).
For a disposable development backend only, explicitly allow local HTTP. Public
HTTP, URLs containing credentials, query parameters, and fragments are rejected.
The backend operator configures the frontend approval URL.

A config entry represents one normalized backend URL, account ID, and workspace
ID. Repeating that combination aborts without replacing its credentials.
Different account/workspace combinations remain independent. The integration
stores access token, refresh token, and Unix expiry together using Home
Assistant's config-entry storage. It does not retain passwords or identifiers
in entry data, and does not log credentials. Protect Home Assistant's normal
configuration storage and backups, which contain session credentials.

Service actions check the calling Home Assistant user's permissions against the
target instance's calendar entity, including after that entity is renamed.
`get_daily_calendar` and `get_recording_options` require read permission;
`create_entry`, `record_entry`, and `refresh` require control permission.
Read-only users cannot record entries. Unknown or inactive users are rejected,
and access to one instance does not grant access to another. Calls made by trusted
automations without a user context remain supported. User-scoped service calls
are rejected if the instance's calendar entity is absent from the entity registry.

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
python -m pytest -q tests/test_device_link.py tests/test_config_flow.py tests/test_auth.py tests/test_reauth.py tests/test_init.py
python -m ruff check .
python -m ruff format --check .
python scripts/check_file_sizes.py
python -m pytest -q
```

The offline fixture replay exercises the real Home Assistant flow manager and
loader with mocked aiohttp responses: browser linking or password exchange → user sync → profile →
workspace selection; expiry → one refresh → authenticated requests; revocation
→ reauthentication; wrong account rejection; outage → retry; and reload/unload.
Synthetic sentinels check that logs, form responses, and persisted entry data do
not contain the password. No backend, Google speaker, or microphone is involved.

The live acceptance walkthrough requires a disposable Home Assistant instance,
a local test backend/Supabase, and disposable account credentials:

1. Add the integration with Google, then repeat with GitHub on a separate test
   account/workspace. Approve the displayed code and select the test workspace;
   expect one loaded entry per setup. Verify denial and expired codes create no entry.
2. Wait across token expiry and make an authenticated read; expect success
   without login and rotated credentials in config-entry storage.
3. Revoke the connection on the Track Things approval page, repeat the read,
   and complete browser reauthentication;
   expect the same entry/account/workspace to reload.
4. Stop the backend and restart HA; expect setup retry with entry data preserved.
   Restore the backend and verify recovery. Unload/reload the integration.

Live account/expiry/revocation UI checks were not run in the implementation
workspace: no disposable backend/account was supplied. Automated fixture results
are recorded in the PR and do not claim a live Supabase or browser walkthrough.
