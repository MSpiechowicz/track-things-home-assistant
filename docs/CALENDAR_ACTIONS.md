# Calendar actions

`track_things.get_daily_calendar` returns complete recorded entries, a `total`,
and a summary in English (`en`, default) or Polish (`pl`). Use Developer Tools →
Actions, select the action and choose the Track Things account instance. The
`config_entry_id` is required even with only one instance.

```yaml
action: track_things.get_daily_calendar
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
  date: "2026-09-08"
  language: pl
response_variable: daily_calendar
```

Omit `date` to use today in Home Assistant's configured timezone. Optional
`trackerId` and `subjectId` filter the recorded entries. IDs must belong to the
chosen workspace; a tracker must also be included in the integration's tracker
selection. Archived historical subjects are supported. Filtering uses recorded
subject IDs, not current tracker assignments.

The response contains `date`, `time_zone`, `language`, `total`, `entries`, and
`summary`. Entries retain all decoded backend fields, including values, notes,
tags, schema version, timestamps, and periods. Summaries localize the count;
user-authored tracker and subject names are preserved. Empty days return zero
and an empty list. Backend errors are action errors, never empty success results.

Reads use the same paginated, 60-second range cache and overlap rules as the
calendar entity, including multi-day records and local DST boundaries. Filters
are applied to complete cached reads, so pagination does not truncate totals.

```yaml
action: track_things.refresh
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
response_variable: refresh_result
```

Refresh invalidates ranges and refreshes workspace metadata. It optionally
returns `{"refreshed": true}`; it can also be called without a response variable.
A failed metadata refresh raises an action error. Calendar listeners refresh
the entity independently; this response confirms metadata refresh, not the
completion of every subsequent calendar request.

## Verification

Run with the repository test environment:

```sh
python -m pytest -q tests/test_calendar_services.py tests/test_refresh_service.py
python -m ruff check .
python -m ruff format --check .
python scripts/check_file_sizes.py
python -m pytest -q
```

The tests exercise the actual HA service registry against synthetic HTTP and
cover complete responses, language/count formatting, local today, explicit
filters, two-instance targeting, invalid/foreign IDs, empty days, unavailable
backend, defensive cache copies, and refresh failure/invalidation.

For the manual UI check, configure a disposable backend workspace, call a
populated day, an empty day and a subject-filtered day in both languages. Verify
IDs and counts against the seeded entries. Stop the backend, call refresh, and
expect an explicit error. This live Developer Tools/backend walkthrough has not
been performed in the automated development environment; synthetic registry
checks do not substitute for that UI check.
