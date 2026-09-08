# Workspace metadata

Account setup now loads all tracker and subject pages, then refreshes metadata
roughly every five minutes. Settings → Devices & services → Track Things →
Configure selects trackers for future calendar use, including integration,
computed, and archived trackers. Initially all discovered trackers are selected;
saving an empty selection disables all trackers. Selection changes take effect
without reloading the client or discarding its schema cache.

Future voice writes use only selected, active manual trackers with a resolvable
current schema. All `subjectIds` assignments are retained; speaker identity does
not select a subject. Missing subject resources remain absent, so downstream
writers must validate the selected subject against available metadata.

`entry.runtime_data` contains `api` and `coordinator`. Consumers read
`coordinator.data`, `calendar_trackers`, and `voice_trackers` without network I/O.
They must check `last_update_success` before using metadata for writes. A failed
refresh marks availability false and preserves the last complete snapshot;
a later successful refresh restores availability. Authentication/permission
failures initiate reauthentication. Initial refresh failure retries setup.

Internal explicit refresh uses `await coordinator.async_refresh()`; callers must
check `last_update_success` afterward. No public refresh action is registered yet.
Historical reads use `coordinator.store.async_tracker(id)`, `async_subject(id)`,
and `async_schema(tracker_id, version_id)`. Historical metadata is read by ID when
absent from discovery. Successful immutable schema versions are fetched once per
runtime, including concurrent requests, and returned as defensive copies. Missing
schemas are retried on later refreshes and excluded from write eligibility.
Unload cancels polling and unregisters the runtime subscription.

## Verification

```sh
python -m pytest -q tests/test_coordinator.py tests/test_metadata.py tests/test_tracker_options.py
python -m ruff check .
python -m ruff format --check .
python scripts/check_file_sizes.py
python -m pytest -q
```

The offline fixture replay adds a tracker, renames a tracker and subject, archives
a tracker, refreshes assignments, and checks stable schema fetch counts. It also
covers historical archived lookups, concurrent schema reads, missing schemas,
transient failure/recovery, real options flows, and timer/listener cleanup.
These are synthetic harness checks, not a live frontend/backend walkthrough.
For live verification, connect a disposable workspace, change tracker names and
assignments in the frontend, invoke the internal refresh, and compare the snapshot
and schema IDs. No live workspace was used for this implementation.
