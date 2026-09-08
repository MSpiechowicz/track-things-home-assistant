# Create-entry action

`track_things.create_entry` creates an entry in an explicitly targeted, loaded
account instance and returns `{request_id, entry}`. Use it from Developer Tools →
Actions or an automation with a `response_variable`. Calling this action is the
write authorization; it does not present a conversation confirmation dialog.

```yaml
action: track_things.create_entry
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
  trackerId: YOUR_SELECTED_MANUAL_TRACKER_UUID
  subjectId: YOUR_ASSIGNED_SUBJECT_UUID
  occurredAt: "2026-09-08T10:00:00.000Z"
  values:
    severity: 6
  request_id: headache-2026-09-08-001
response_variable: created
```

Replace the IDs and details with a disposable workspace's resources and schema.
Required fields are `config_entry_id`, `trackerId`, `subjectId`, `occurredAt`, and
`values`. Optional fields are `periodStart`, `periodEnd`, `title`, `note`, `tagIds`,
and `request_id`. Period endpoints accept timezone-bearing ISO timestamps or
null; end cannot precede start. Tags accept at most 50 unique UUIDs. Title and
note accept strings or null. The occurrence is explicit so retries cannot
silently acquire a different timestamp.

The action fetches the current tracker and subject, bypassing historical caches.
Only selected, active manual trackers and active, currently assigned subjects
are accepted. It reads the immutable current schema and validates supplied
values without coercing them or accepting defaults. The backend receives
`source=manual`, `expectedSchemaVersionId`, and the request ID as `Idempotency-Key`.
Backend authorization, tag existence/ownership, and transactional schema checks
remain authoritative. A viewer cannot write even if metadata reads succeed.

## Retries and failures

Supply a stable request ID before the first attempt when you need recovery even
if Home Assistant itself stops. IDs contain 1–255 visible ASCII characters.
When omitted, a UUID is generated and returned with the result. If a backend
failure leaves the outcome uncertain, the error includes that key for recovery.
No entry content or backend error text is included in error messages.

Retry with the **same request ID and identical input**, including the occurrence.
The backend's durable account/workspace ledger replays the existing entry.
Changed content with an already used key raises a conflict. There is no local
success cache or automatic POST retry. Authentication refresh can replay a
rejected request with the same body and key.

A schema change between validation and submission fails explicitly. A later
retry may also conflict if the refreshed schema version differs from the original
submission. Check the recorded entry before starting a new logical request;
never automatically switch keys after an uncertain result. Requests without a
caller-supplied key cannot be recovered if HA stops before reporting the key.

After an acknowledged creation or replay, `MetadataCoordinator.async_entries_changed`
notifies existing cache subscribers. The calendar invalidates its ranges and
refreshes its entity state. The action also works without a calendar platform;
failed submissions do not emit this success hook.

## Verification

Offline tests use the real HA action registry and HTTP client with synthetic
responses. The retry fixture models the backend's durable ledger and a response
lost after insertion: identical retries return one entry; changed content
conflicts. It is contract evidence, not a live database or frontend check.

```sh
python -m pytest -q tests/test_create_entry_service.py tests/test_create_entry_retries.py
python -m ruff check .
python -m ruff format --check .
python scripts/check_file_sizes.py
python -m pytest -q
```

For manual end-to-end verification in a disposable HA/backend workspace, invoke
the example with real disposable IDs and a fixed request ID. Repeat it unchanged
and compare returned entry IDs and the frontend entry count (expected: one).
Change severity with the same key (expected: conflict, count unchanged). Repeat
as a viewer (expected: permission rejection). This live Developer Tools/frontend
walkthrough has not been run as part of the offline fixture verification.
