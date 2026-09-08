# Diagnostics and recovery

In Home Assistant, open **Settings → Devices & services → Track Things**, then
use the config entry's menu to **Download diagnostics**. The integration's data
contains only an explicit set of health facts: config-entry state, configuration
presence flags, metadata availability, whether metadata requires reauthentication,
the last successful metadata refresh in UTC, and tracker/subject/missing-schema
counts. Counts describe the last complete snapshot and may be stale during an
outage. The timestamp advances only after a successful complete metadata refresh;
it is not the last calendar read or write time. Unloaded/failed setup entries
report no live runtime. A new runtime starts without a previous refresh timestamp.

The integration does not serialize its config entry, options, exception messages,
resource IDs, backend URL, credentials, resource names, schemas, calendar entry
bodies, notes, aliases, transcripts, prompts, or tool payloads. Unknown future
config fields are excluded too. Downloading diagnostics performs no backend call,
refresh-token rotation, telemetry upload, or model request. Home Assistant may
wrap integration data in its own system/environment information; inspect the
complete downloaded file before sharing it.

## Expected recovery behavior

- Metadata/backend failure makes the calendar unavailable and prevents normal
  conversation progress. The previous complete metadata snapshot and its timestamp
  remain available for diagnosis. A successful refresh invalidates calendar ranges,
  refreshes the calendar, and allows conversation to continue.
- Rejected refresh credentials or revoked workspace access start reauthentication.
  Restore access and complete the integration's reauthentication flow. It reloads
  the same config entry with the replacement session.
- Unload/reload removes calendar listeners and conversation expiry callbacks,
  disables the old API client, invalidates calendar caches, and discards drafts,
  conversation pagination, and pending write state. Restart cannot replay a write.
  If an interrupted write might have reached the server, inspect the recorded-entry
  calendar before intentionally starting another entry.

Coverage targets the repository's existing local question adapter through HA
Assist. No Gemini runtime is configured or invoked by these diagnostics. Google
speaker routing and the unresolved POC decision in #25 are not established by
these tests.

## Reproducible offline verification

From the repository's activated test environment:

```sh
python -m pytest -q tests/test_diagnostics.py tests/test_recovery.py
python -m ruff check .
python -m ruff format --check .
python scripts/check_file_sizes.py
python -m pytest -q
```

The focused replay runs the actual integration, calendar and conversation platforms
with mocked HTTP. Sentinel credentials, names, entry notes, unknown model/config
fields and exception text must not appear in integration diagnostics. It checks
outage/recovery, refresh-token rejection, workspace revocation, real reauthentication
and reload, and unload/restart with an uncertain pending write. HA's fixture teardown
checks leaked resources; advancing time after unload checks that polling stops.

## Disposable live verification checklist

These checks require a configured disposable HA instance and seeded backend and
are **not claimed as executed by the offline replay**:

1. Seed recognizable fake names, notes and credentials. Download diagnostics from
   the integration UI and search the entire file for those sentinels. Expected:
   no private integration content, only the documented health fields and counts.
2. Stop the backend and request a refresh. Expected: unavailable calendar and
   blocked dialogue; unchanged last successful refresh. Restart it and refresh:
   expected available calendar, advanced timestamp, and usable Assist dialogue.
3. Revoke the backend session, trigger refresh, and reauthenticate. Expected:
   reauth prompt, unavailable calendar until recovery, same config entry afterwards.
4. Start a draft and restart HA before confirmation; then say “confirm” using the
   old conversation ID. Expected: no resumed draft and no new backend entry.
5. Repeat after a lost write response. Expected: no automatic retry on restart;
   check the backend entry count before manually initiating another write.

Record HA/backend versions and expected versus actual results before claiming live
acceptance. No microphone or Google hardware is needed for the offline tests.
