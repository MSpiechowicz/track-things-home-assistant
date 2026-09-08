# Track Things Home Assistant implementation plan

## Goal and current increment

Read Track Things' recorded-entry calendar and create entries through guided
English and Polish Home Assistant Assist conversations. Google Home provides
fixed-script shortcuts and spoken summaries on a configured speaker.

The [project board](https://github.com/users/MSpiechowicz/projects/4) contains the
implementation backlog. All issues live in this repository, including tickets
whose code belongs in `track-things-backend`. Each issue has its own scope,
dependencies, acceptance checks, and verification steps.

[Issue #1](https://github.com/MSpiechowicz/track-things-home-assistant/issues/1)
only establishes the package, lifecycle, tests, CI, and this document. It adds no
account UI, backend API calls, calendar platform, or voice implementation. Empty
YAML enables development smoke testing without account credentials.

[Issue #7](https://github.com/MSpiechowicz/track-things-home-assistant/issues/7)
adds account/workspace configuration, serialized session rotation, runtime
setup/unload, and same-account reauthentication. See [account setup](ACCOUNT_SETUP.md).

[Issue #11](https://github.com/MSpiechowicz/track-things-home-assistant/issues/11)
adds the read-only workspace calendar, paginated range reads, current/next-event
state, and a 60-second cache. See [calendar behavior and verification](CALENDAR.md).

Baseline: Home Assistant 2026.9.0 and Python 3.14.2+. CI tests the baseline and the
latest stable compatible custom-component harness. Handwritten source/test files
must stay at or below 500 physical lines. See the README for exact check commands.

## Architecture and interfaces

The integration lives under `custom_components/track_things`. Keep API transport,
resource models, schema validation, calendar conversion, conversation state,
service actions, and configuration responsibilities separate as they are added.

Use Home Assistant's shared async HTTP session. Config entries identify backend,
account, and workspace; runtime state holds coordinators and transient drafts.
No global mutable account state or database connection belongs in the integration.

### Account and metadata

- One existing password-authenticated account and workspace per config entry.
  Multiple entries may represent other accounts/workspaces.
- Setup collects backend URL and credentials, synchronizes the application user,
  and selects an accessible workspace. Exchange the password and discard it.
- Store access/refresh tokens and expiry through config-entry storage, redact
  them from logs, serialize refreshes, and persist rotated tokens before reuse.
- Use HTTPS except explicitly configured local development. Invalid sessions
  trigger reauthentication; temporary outages preserve configuration.
- Refresh tracker/subject metadata every five minutes by default; cache immutable
  schemas by version ID. Allow explicit tracker selection and refresh.
- For new voice entries, offer selected active manual trackers and their current
  `subjectIds`. The legacy singular tracker `subjectId` is not a user selection.
- Historical entries keep their recorded subject and schema version. Fetch
  archived resource metadata by ID when needed for rendering.

### Backend prerequisites

Backend runtime routes/validators are authoritative over older design documents.
Initial contract inspection used backend commit `2cad8c4`.

| Ticket | Contract addition |
| --- | --- |
| [#2](https://github.com/MSpiechowicz/track-things-home-assistant/issues/2) | `POST /auth/refresh`, rotated tokens and expiry metadata; preserve password login. |
| [#3](https://github.com/MSpiechowicz/track-things-home-assistant/issues/3) | Entry-list date/timezone, tracker, and recorded-subject filters before cursor pagination. |
| [#4](https://github.com/MSpiechowicz/track-things-home-assistant/issues/4) | Optional `expectedSchemaVersionId` on creation, checked under the tracker lock. |
| [#5](https://github.com/MSpiechowicz/track-things-home-assistant/issues/5) | Transactional `Idempotency-Key` ledger scoped to account/workspace/key. |

Date filtering accepts inclusive `startDate`, exclusive `endDateExclusive`, and
IANA `timeZone` together, plus optional `trackerId`/`subjectId`. Preserve existing
unfiltered responses and bounded cursor pagination; bind cursors to filters.

The create route currently chooses the current tracker schema and does not accept
`schemaVersionId`. The new expected-version guard returns
`409 tracker_schema_changed` on mismatch. Idempotent retries return the original
entry; a changed request with the same key conflicts. Replays recheck permissions
and cannot recreate a deleted entry. Existing `clientMutationId` is correlation
metadata, not duplicate protection. Deploy additive backend changes first.

### Calendar and actions

Expose one read-only calendar entity per workspace containing selected trackers.
Fetch only requested date ranges, consume all cursor pages, and cache ranges for
60 seconds. Invalidate after writes/refresh. Backend failures must not masquerade
as empty calendars. Entity properties read memory rather than doing I/O.

Period boundaries represent calendar dates using the frontend's existing UTC
serialization. Their end date is inclusive: convert it to an exclusive next-day
end for Home Assistant all-day events. Timestamp-only entries use `occurredAt` in
the HA timezone and a one-minute display-only duration. Never persist that display
duration. Use entry IDs as event IDs and historical schemas for detail labels.

| Planned action | Inputs and result |
| --- | --- |
| `track_things.get_daily_calendar` | Explicit config entry, date (today by default), optional tracker/subject filters and language; returns entries, count, localized summary. |
| `track_things.refresh` | Explicit config entry; refreshes metadata and invalidates calendar caches. |
| `track_things.create_entry` | Explicit config entry, tracker, subject, occurrence/period, typed values, optional title/note/tags/request ID; returns the created entry and request ID. |

Automation calls are deliberate writes and do not initiate dialogue. Share their
validation/submission layer with voice. Reuse request IDs only for retries of the
same confirmed submission. User-authored entries use `source: manual`.

### Local voice dialogue

Use a dedicated `ConversationEntity` with `_async_handle_message`, ChatLog,
conversation IDs, and `continue_conversation`. Configure English and Polish Assist
pipelines; Home Assistant supplies speech recognition/playback. Use Hassil
templates with dynamic names/aliases and typed parsers, not an LLM.

The state machine is:

1. Recognize the request and resolve a selected active manual tracker.
2. Resolve its subject: choose the sole eligible subject or ask.
3. Collect required visible details in schema order, one question at a time.
4. Offer optional details, then read back tracker, subject, date/time, and values.
5. Obtain confirmation, refresh metadata, and submit using the guarded,
   idempotent create operation. Meaningful metadata changes require renewed review.

Support text, textarea, number, slider, boolean, date, select, and multiselect.
Serialize field keys and option IDs. Match backend runtime validation, including
slider constraints and conditional visibility. Corrections recompute visibility
and remove newly hidden values. Required defaults need explicit user acceptance.

Prefer exact names and configured aliases. Ambiguous names/choices prompt for
clarification. Polish inflected names can be configured as aliases. “Me” requires
an explicit eligible default subject; speaker identity does not select a subject.

Omitted occurrence means now; date-only commands produce all-day entries matching
the frontend; explicit time produces a timestamp. Use HA's timezone and ask about
ambiguous/nonexistent local times. Support cancellation, correction, repeat,
optional skip, and calendar “more” with five spoken entries per page.

Keep drafts in memory, isolated by instance, conversation ID, and available
user/device context. Expire after five minutes of inactivity. Serialize submission
per draft, preserve keys across transport retries, and never replay drafts after
restart. Do not put entry or conversation contents in diagnostics.

### Google Home boundary

Document selected scripts exposed through Home Assistant's Google integration:
one for daily summaries and another for fixed tracker/subject/value entry creation.
Use an explicitly configured output speaker and TTS service; do not infer the
originating Google microphone/speaker. Validate fixed inputs against current
metadata and direct users to Assist when clarification is required.

The supported smart-home bridge exposes scripts as actions, not arbitrary speech
and follow-up transport. Google retired Conversational Actions. Full Track Things
dialogue therefore runs through Assist, including when using Google shortcuts
elsewhere in the same home.

## Delivery and acceptance

Implement one unblocked issue per focused PR. Mock future collaborators rather
than implementing later tickets to make an earlier ticket testable. The board's
native blocking relationships and issue descriptions define exact prerequisites.

| Tickets | Increment |
| --- | --- |
| #1–#5 | Scaffold and independent backend prerequisites. |
| #6–#8 | Async client, account lifecycle, metadata. |
| #9–#13 | Pure validation/calendar mapping, calendar platform, read/write actions. |
| #14–#19 | Bilingual recognition, isolated drafts, Assist, confirmed saving, calendar speech, aliases. |
| #20–#21 | Google summary and fixed-entry scripts. |
| #22–#23 | Redacted diagnostics, recovery coverage, packaging, real-device acceptance. |

Every PR runs focused tests plus repository checks. Core tests use fake clocks,
mock HTTP, and synthetic data. Backend idempotency/schema guards additionally use
real disposable PostgreSQL concurrency tests. Validate installation, voice input,
and Google scripts on disposable instances/devices before the release ticket is Done.

Final acceptance covers calendar parity with the frontend (including DST and
multi-day ranges), both languages, all field types, ambiguous subjects, conditional
details, cancellation without writes, renewed review after schema/assignment
changes, exactly-one creation after retries, token rotation/reauth, outages, and
restart without draft replay. Record actual results rather than assuming hardware
checks passed. Redact credentials and personal data from all verification evidence.

Outside this release: tracker creation, entry editing/deletion, reminders,
social login, per-speaker backend accounts, arbitrary Google-speaker dialogue,
and LLM-based recognition. Those require separate product decisions and tickets.

## References

- [Home Assistant integration manifests](https://developers.home-assistant.io/docs/creating_integration_manifest/)
- [Home Assistant integration testing](https://developers.home-assistant.io/docs/development_testing/)
- [Conversation entity](https://developers.home-assistant.io/docs/core/entity/conversation/)
- [Calendar entity](https://developers.home-assistant.io/docs/core/entity/calendar/)
- [Home Assistant Google integration](https://www.home-assistant.io/integrations/google_assistant/)
- [Google Conversational Actions retirement](https://developers.google.com/assistant/ca-sunset)
