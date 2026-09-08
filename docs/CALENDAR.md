# Workspace calendar

Issue #11 adds one read-only Home Assistant calendar for each configured Track
Things account/workspace. The entity uses the config entry's title. Its registry
identity is based on the config entry ID, so renaming the entry, changing tracker
selection, or reloading does not create a new calendar.

Open Home Assistant's Calendar panel and select this calendar. All trackers are
included by default, including archived historical trackers resolved by ID.
Integration options restrict the calendar to selected tracker IDs; an explicit
empty selection displays no events. Changes invalidate cached ranges immediately.
Calendar creation, editing, and deletion are not supported.

## Reads and state

Calendar views and Home Assistant's `calendar.get_events` action accept arbitrary
timezone-aware ranges. The reader translates them to backend date filters in the
HA timezone, consumes every cursor page, resolves recorded schema/subject/tracker
metadata through the metadata coordinator, sorts events, and then applies exact
half-open range filtering. It includes the minute preceding the query when
choosing backend dates so timestamp entries crossing midnight remain visible.
Multi-day periods retain their recorded calendar dates and use an exclusive
next-day end. See [calendar mapping](CALENDAR_MAPPING.md).

The current/next-event state polls every 60 seconds. Since the backend has no
next-event query, this read covers today through the end of the supported Python
date domain (exclusive 9999-12-30), including ongoing periods that started earlier.
It does not stop at a short lookahead window. This can read many pages for a
workspace with many future entries; the API client's existing pagination bound
still applies and fails explicitly if exceeded. Past-only histories are filtered
on the backend. Entity properties perform no network I/O.

Successful complete date ranges are cached for 60 seconds using a monotonic clock,
with at most 32 ranges per config entry. Precise subranges share the date cache;
HA timezone and tracker selection are part of the key. Returned events are copied
so consumers cannot mutate cached state. Concurrent reads are serialized, and an
in-flight result invalidated by a metadata/options change is retried.

`entry.runtime_data.calendar.invalidate()` is the internal hook for later refresh
and write actions. It clears all ranges; the next query/poll reads fresh data.
Metadata refresh and options changes also schedule an immediate entity refresh.
No new Track Things service actions are introduced by this issue.

API or historical-metadata failures raise a safe `HomeAssistantError` for calendar
queries and mark the entity unavailable; they never become a successful empty
calendar. Polling retries, and successful reads restore availability. Authentication
failures request reauthentication. Unload removes the platform, its timers and
metadata listener, clears the cache, shuts down the coordinator, and closes the
runtime client without closing HA's shared HTTP session.

## Verification

```sh
python -m pytest -q tests/test_calendar.py tests/test_calendar_cache.py
python -m ruff check .
python -m ruff format --check .
python scripts/check_file_sizes.py
python -m pytest -q
```

The offline HA fixture replay uses the real loader, calendar entity registry,
`calendar.get_events`, HTTP serializer/pagination, and options/reload/unload paths.
It checks a multi-day period, exact range boundaries, a timestamp spanning local
midnight, DST folds, a next event more than a year away, explicit empty selection,
archived metadata, cache expiry/races, backend failure and recovery, and cleanup.

Manual UI acceptance still requires a disposable backend/HA instance with seeded
entries and the frontend; it is not replaced by an automated device claim:

1. Set HA to Europe/Berlin and configure the disposable workspace.
2. Seed a three-day period and a timestamp near local midnight. Open the same week
   in HA and Track Things. Expect matching recorded days and subjects; HA's
   timestamp event has its documented display-only one-minute duration.
3. Select one tracker in integration options, then none, then all. Expect the
   calendar and current-event state to update without a reload.
4. Stop the disposable backend, query an uncached range, and expect an unavailable
   entity and explicit query error. Restart it and expect recovery on polling.

No live frontend/backend comparison was performed for this PR; all fixture data
is synthetic and all test HTTP requests are mocked.
