# Confirmed voice creation

Local Assist now saves a reviewed draft through the same validation and backend
write functions as `track_things.create_entry`. The local-question path remains
independent of the unproven Google speaker experiment (#25), following the
recorded product direction in `IMPLEMENTATION_PLAN.md` and `ASSIST_CONVERSATION.md`.

## Safety and recovery contract

- Read back tracker, explicit subject, occurrence and typed details before saving.
  Confirmation belongs to the review visible when the user turn arrives. Two
  queued confirmations cannot approve a newer review created by a metadata race.
- Refresh metadata before submission. Retain compatible values, remove invalid
  answers, and ask again after schema/assignment changes. A replacement subject
  always requires an explicit choice. Schema conflicts require renewed review.
- Serialize turns and use one backend idempotency key per confirmed revision.
  A lost response retains the original payload and key for explicit retry in the
  same authenticated conversation. Corrections cannot alter an uncertain write.
- Announce success and invalidate calendar caches only after acknowledgement.
  Distinguish a metadata outage before writing from an uncertain write outcome.
  Permissions and authentication use localized messages without backend content.
- Cancellation before submission makes no write. After an uncertain submission,
  cancellation only stops retries; it does not claim the backend entry was removed.
  Expiry/unload/restart never replays an entry. Check the calendar before recreating
  an entry whose result was uncertain.

The optional internal callback seam remains for alternate runtimes/tests.
Production uses `VoiceEntryWriter`. No Gemini/model callback owns the save gate.

## Reproducible automated evidence — 2026-09-08

Executed with Python 3.14.7 and both installed compatibility environments:

| Environment | Home Assistant | Test plugin | Full suite |
| --- | --- | --- | --- |
| `.venv-minimum` | 2026.9.0 | 0.13.363 | 612 passed |
| `.venv` | 2026.9.1 | 0.13.364 | 612 passed |

```sh
.venv/bin/python -m pytest -q tests/test_voice_creation.py tests/test_voice_creation_conflicts.py
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python scripts/check_file_sizes.py
.venv/bin/python -m pytest -q
.venv-minimum/bin/python -m pytest -q
```

The 22 new tests use the real HA config entry, conversation API, local adapter,
draft validation and shared create logic with mocked API resources and a synthetic
idempotent sink. They do not contact a live backend or use real credentials.

| Replay | Expected | Actual |
| --- | --- | --- |
| English/Polish follow-ups then confirmation | No prior write; one typed Anna/Headache entry after confirmation | Passed |
| Concurrent confirmation | One entry and one cache notification | Passed |
| Lost response then explicit retry | Identical payload/key, one sink entry | Passed |
| Schema/assignment change | No stale write; compatible answers retained; fresh review | Passed |
| Schema changes between refresh and validation | No write; return to review | Passed |
| Two queued confirmations during schema change | Neither approves the newly produced review | Passed |
| Changed constraints | Keep valid values; ask again for invalid values | Passed |
| Cancellation, expiry, unload, identity mismatch | No unintended write or replay | Passed |
| Forged proposal/unspoken revision | No write | Passed |
| Permission/authentication failure | Safe localized failure, no success notification | Passed |

Lint, formatting and the 500-line source/test limit pass. The sandbox blocked
asyncio's internal self-pipe sockets, so HA tests ran outside that restriction;
pytest's socket prohibition and mocked API boundaries remained enabled.

## Disposable-backend walkthrough — not executed

Live Assist UI, backend/frontend parity and STT/TTS checks remain deferred as
recorded in `ASSIST_CONVERSATION.md`. No live-device result is claimed by this PR.
To verify later:

1. Connect a disposable workspace with an active manual Headache tracker, Anna
   and Ben assignments, required pain/severity details and optional note.
2. In the Track Things Assist text pipeline, say `log Headache`, choose Anna,
   answer pain/severity, and review. Verify zero new frontend entries before
   confirmation; confirm and verify one entry with matching occurrence/values.
3. Repeat in Polish (`zapisz Headache`, `Anna`, `tak`, `siedem`, `/pomiń`,
   `potwierdź`). Confirm again and verify no duplicate entry.
4. Start a new draft, cancel it and verify no additional entry.
5. Change the tracker schema between review and confirmation. Confirm; expect
   clarification/new review and no write. Answer the new question and explicitly
   confirm again, then inspect the final frontend values.
6. Repeat through configured English/Polish STT/TTS pipelines when available.
   The free-text slash-command limitation and Google transport restrictions in
   `ASSIST_CONVERSATION.md` still apply.
