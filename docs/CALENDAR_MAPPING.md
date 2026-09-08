# Pure calendar mapping

`custom_components.track_things.calendar_mapping` exposes two synchronous helpers.
Neither needs a Home Assistant instance, an API client, or credentials.

- `entry_to_calendar_event(entry, schema_version, tracker=tracker, subject=subject)`
  accepts the serialized models from `api_models` and returns Home Assistant's
  `CalendarEvent`. Callers supply the schema version identified by the entry,
  the recorded subject (including archived subjects), and tracker metadata.
  Mismatched IDs/workspaces raise `ValueError`; the current tracker schema is
  deliberately ignored.
- `calendar_event_overlaps(event, range_start, range_end, time_zone=zone)` checks
  half-open intervals. Query timestamps must be aware. All-day boundaries use
  midnight in the supplied timezone, and comparisons use UTC instants so DST
  folds and 23/25-hour days work correctly. Empty/reversed queries return false.

Period dates use the date prefix of the backend's UTC serialization, matching
frontend calendar semantics. They are never shifted to another timezone. Missing
period end means a single day; inclusive end becomes the following exclusive
calendar date. A timestamp-only entry uses aware `occurredAt`, normalized to UTC,
with exactly one minute of display duration. No duration is persisted. Malformed,
naive, reversed, or end-only boundaries raise `ValueError`.

The stable event UID is the entry ID. Summaries contain subject, tracker, and
optional title separated by ` · `. Descriptions contain the note and recorded
field labels/values in schema order. Select/multiselect options use historical
labels with raw IDs as a fallback for unknown options. Booleans render as Yes/No;
text, dates, and numbers retain their serialized values. Missing/null details are
omitted; false and zero remain visible. These are plain display strings, not HTML
or instructions. No input is mutated, no current-schema validation is applied to
historical values, and no visibility rule suppresses recorded details.

## Offline verification

```sh
.venv/bin/python -m pytest -q tests/test_calendar_mapping.py tests/test_calendar_ranges.py
```

The fixture replay compares actual Home Assistant objects against:

| Synthetic entry | Expected start | Expected exclusive end | Summary |
| --- | --- | --- | --- |
| September 8 period, no end | 2026-09-08 | 2026-09-09 | Anna · Headache |
| September 8–10 period | 2026-09-08 | 2026-09-11 | Anna · Headache |
| September 8, 00:30 +02:00 timestamp | 2026-09-07 22:30 UTC | 2026-09-07 22:31 UTC | Anna · Headache |

Tests also cover Berlin DST transitions, New York versus Berlin midnight,
exclusive query edges, stable IDs, historical labels, invalid metadata, and input
immutability. This pure-module fixture replay is the issue's manual inspection;
no hardware or live backend is needed. Calendar entity registration remains a
separate issue.

Contract references:
[Home Assistant calendar entities](https://developers.home-assistant.io/docs/core/entity/calendar/)
and [calendar best practices](https://developers.home-assistant.io/blog/2023/03/28/calendar_best_practices/).
