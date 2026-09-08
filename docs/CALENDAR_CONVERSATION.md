# Calendar questions in Assist

The local Track Things Assist agent answers recorded-entry calendar questions in
English, Polish, German and French. It uses the same date boundaries, tracker
selection, resource validation, cache, and authentication recovery as
`get_daily_calendar`. Calendar reads do not require a writable tracker or its
current creation schema. The Google speaker experiment remains separate.

## Queries and filters

| Language | Day query | With optional filters | Next page |
| --- | --- | --- | --- |
| English | calendar for yesterday | calendar for today for tracker Headache for subject Anna | more |
| Polish | kalendarz na wczoraj | kalendarz na dzisiaj dla trackera Headache dla osoby Anna | więcej |
| German | Kalender für gestern | Kalender für heute für Tracker Headache für Person Anna | mehr |
| French | calendrier pour hier | calendrier pour aujourd'hui du tracker Headache de la personne Anna | plus |

Omitting the day means today in Home Assistant's configured timezone. ISO dates
such as `2026-09-08` are supported. Use the documented phrases; unrestricted
natural-language interpretation is not provided. Tracker and subject labels are
literal user data. You can use a stable ID instead of a name. “My calendar” does
not infer a subject from the speaker.

For text input, equivalent explicit filters are
`calendar for 2026-09-08; tracker: Headache; subject: Anna` or
`kalendarz na 2026-09-08; tracker: Headache; osoba: Anna`. German uses `Tracker`
and `Person`; French uses `tracker` and `personne`. Explicit filters are useful
when a label contains a spoken filter delimiter. Semicolons delimit filters and
cannot be part of a filter label; use its stable ID in that case.

Unknown or colliding names prompt for a valid name/ID, displaying IDs to
distinguish identical labels. Tracker clarification precedes subject clarification.
No ambiguous name silently chooses a resource. Cancel and ask again to replace a
query while its filter question is pending. Alias configuration remains #19.

## Paging and lifecycle

Each answer speaks the date, exact total, and at most five entry summaries. Say
more to hear the remaining entries; repeat replays the current page without
advancing. Empty days have a distinct localized response. Unavailable backend or
access failures never masquerade as an empty day. Authentication errors use the
shared reauthentication path. Exhausted pages do not repeat entries.

The first read freezes ordered entry IDs and summary strings. Later cache
refreshes or writes do not change that result: ask the calendar question again
for updated results. Raw entry bodies, values and notes are not retained in the
conversation paging store. A snapshot lasts five minutes from the original
query; paging, repeat and invalid answers do not extend it. It is isolated by
config entry, conversation ID, HA user, device, satellite and language. Unload or
restart clears snapshots and pending filter questions. Reported metadata failure
or changed tracker selection discards the snapshot before a follow-up reads it.

An existing creation draft is preserved during a calendar query. Cancel exits
the calendar interaction; repeat can then resume the draft's question/review.
Creation fields containing free text keep the existing slash-command convention:
a literal calendar phrase is content; `/calendar` explicitly requests a query.
A new creation command replaces the calendar interaction once filters are resolved.
An uncertain write retains priority: only retry confirmation/cancellation is
accepted until its outcome is resolved. Calendar questions never submit entries.

## Reproducible verification

```sh
.venv/bin/python -m pytest -q tests/test_calendar_conversation.py tests/test_calendar_conversation_paging.py
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python scripts/check_file_sizes.py
.venv/bin/python -m pytest -q
```

Tests use the real HA Assist entity with synthetic HTTP responses or mocked
calendar records. The seven-record English/Polish replay expects records 0–4 on
the first page and 5–6 on more, exactly once and in the same conversation. It
checks snapshot stability, empty days, auth/backend failures, filter ambiguity,
local dates, isolation, expiry, cancellation and unload. Existing daily-action
and calendar-query tests cover DST boundaries, backend paging and deduplication.

Live Assist UI/STT/TTS/backend walkthrough remains deferred, consistent with the
owner's recorded local-Assist authorization in [the runtime guide](ASSIST_CONVERSATION.md).
No microphone, Google device or live-backend pass is claimed. To perform it:

1. In a disposable workspace, seed seven distinguishable entries on one day.
2. Ask the English date query, then more; verify the first five and final two
   each appear once. Repeat in Polish with the same expected IDs/count.
3. Ask for an empty day and verify an explicit empty response.
4. Stop the backend, invalidate the calendar cache with the refresh action, and
   ask again; expect unavailable, never zero entries. Restore and retry.
5. Use a duplicate subject label and verify clarification before any result.

Verified on 2026-09-08: all 643 tests passed on Home Assistant 2026.9.0
(harness 0.13.363) and 2026.9.1 (harness 0.13.364). Ruff lint/format and the
500-line checker passed. Expected versus actual seven-entry replay: first page
0–4, second page 5–6, with total 7 and no repeat/skip; both languages passed. These replays exercise text processing and do not establish spoken recognition
quality or prove routing from Google speakers.
