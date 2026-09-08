# Engine-independent conversation drafts

`custom_components.track_things.dialogue` exposes a synchronous `DraftStore` and
its typed inputs/results. It consumes authorized metadata snapshots and proposed
updates, and emits descriptors for either conversation adapter. It has no network,
Home Assistant, model, or persistent-storage collaborator. The speaker/engine
selection in #25 does not gate this module.

## Adapter contract

- Construct `DraftMetadata` with the workspace ID, allowed trackers, subjects, and
  immutable schema versions. The store copies it at start. Only active manual
  trackers and their active, assigned, same-workspace subjects are selectable.
  The adapter must prefilter trackers to the instance's selected/authorized set.
- Start with a runtime-scoped draft ID. The runtime must scope this ID to its
  config entry and authenticated conversation/user/device context. Speaker
  identity must never be used to infer the recorded subject.
- Supply `DraftPatch` with explicit tracker/subject IDs and field values keyed by
  schema keys. Name ambiguities belong to the adapter; tracker/subject descriptors
  enumerate eligible IDs. A sole eligible subject is selected automatically;
  zero or multiple subjects leave the draft incomplete.
- Values are validated without coercion, including when other required values
  are missing. One patch can supply several details. Corrections remove hidden
  values and descendants; revealing them again requires new input. Invalid
  proposals fail atomically and preserve the preceding draft and review.
- `accept_defaults` explicitly accepts named fields' defaults. Missing required
  defaults are never inserted automatically. `remove` deletes an answer;
  `skip_optional` removes an optional answer and suppresses its prompt. Operations
  on the same key cannot be combined. Hidden values/defaults cannot be supplied.
- Descriptors identify required and optional fields and carry copied definitions.
  Their schema order is a deterministic default, not a required question order.
  Labels/descriptions are untrusted display data, never executable instructions.
- `review` requires every visible required field and a valid subject. It may
  intentionally omit unanswered optional fields. Render its copied payload to the
  user before requesting confirmation. `confirm(id, revision)` is a separate
  explicit operation; a patch can never authorize saving.
- Every accepted update invalidates review and creates a fresh opaque revision.
  Confirm only the exact revision returned by review. A successful confirmation
  consumes the draft and emits one `SubmissionIntent`; repeats fail. Reusing a
  draft ID cannot reuse an earlier revision. Backend idempotency and save retries
  remain the saving runtime's responsibility (#17).

## Occurrence and lifecycle

Omitted occurrence freezes the injected wall clock at draft creation, so a long
conversation does not silently change the reviewed time. `reset_occurrence=True`
explicitly selects the current clock value. A `date` produces a one-day inclusive
period with both endpoints serialized at UTC midnight, matching backend calendar
date semantics. An aware `datetime` produces only `occurredAt`, normalized to UTC.
Naive datetimes are rejected. Relative-date parsing and ambiguous/nonexistent
local-time handling belong to the selected adapter before proposing a datetime.

The five-minute inactivity window uses an independently injected monotonic clock.
Successful updates and reviews extend it; inspection and invalid proposals do
not. Every access expires stale drafts. The runtime should also call `expire()`
periodically to erase idle memory promptly and `clear()` on unload. Cancellation,
expiry, clearing, or successful confirmation remove pending state. Nothing is
restored after restart. Resource changes after the copied snapshot still require
fresh permission/schema validation by the eventual saving runtime; the intent
includes `expectedSchemaVersionId` for that purpose.

## Offline verification and manual fixture inspection

From the repository test environment:

```sh
python -m pytest -q tests/test_dialogue.py tests/test_dialogue_corrections.py tests/test_dialogue_expiry.py
python -m ruff check .
python -m ruff format --check .
python scripts/check_file_sizes.py
python -m pytest -q
```

The first test in `tests/test_dialogue.py` is the manual replay fixture: start
without a tracker, choose headache, choose Anna, answer pain=true and severity=7,
correct severity to 6, skip the optional note, review, then explicitly confirm.
The asserted result is one intent for Anna with `{pain: true, severity: 6}`,
`source=manual`, schema-1, and the frozen occurrence. Repeated confirmation fails.
`test_incomplete_conversation_cancel_replay_emits_no_intent` replays subject and
partial detail collection followed by cancellation: no intent can be obtained.
These tests inspect the actual typed payload and require no microphone or backend.
