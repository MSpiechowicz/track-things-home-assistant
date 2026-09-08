# Track Things through Assist

A configured Track Things account now provides a selectable **Track Things**
conversation entity. The local Hassil adapter owns recognition and questions;
`DraftStore` owns schema validation and review. English, Polish, German and
French use the same isolated draft flow. Calendar dispatch and backend saving
remain separate increments: confirmation explicitly reports that saving is
unavailable, and creates no entry.

The owner authorized proceeding with local Assist wiring on 2026-09-08 and
postponing live voice tests. This follows the independent local-question path
already documented in [the adapter guide](CONVERSATION_ADAPTER.md). It does not
resolve the Google speaker experiment in #25 or claim a tested speaker bridge.
No Gemini agent, API key, subscription, or model call is needed for this path.

## Configure the pipeline

1. Install the integration and connect a disposable Track Things workspace.
   Select the desired trackers in its options. Active manual trackers with
   resolvable schemas are available for conversation drafts.
2. In Home Assistant Settings → Voice assistants, add/edit an assistant and
   select **Track Things** as its conversation agent. Keep this agent selected
   for subsequent turns; another agent cannot continue its drafts. Disable
   "Prefer handling commands locally" for this dedicated pipeline and avoid
   sentence-trigger automations matching these replies, so they cannot consume
   a turn before Track Things receives it.
3. Configure one assistant/pipeline for English and another for Polish (or
   German/French). Choose STT and TTS providers that support each language.
   Home Assistant's pipeline owns audio capture, STT, TTS and playback; Track
   Things consumes text and returns speech plus follow-up signaling.
4. Open Assist, choose that assistant, and begin with text input. For example,
   `log Headache` or `zapisz Headache` starts a draft for that tracker label.
   Select an eligible subject if asked, then answer the requested details.
5. Use `review` / `sprawdź` to omit remaining optional details and read back the
   tracker, subject, occurrence and values. If all details are answered or
   skipped, review is presented automatically. A subsequent `confirm` /
   `potwierdź` reports saving unavailable. Verify no entry appears in the backend.

The sole eligible subject is automatically selected from tracker assignments.
Multiple eligible subjects are enumerated; the speaker's identity never selects
one. Choice questions enumerate valid labels, booleans enumerate yes/no, and
conditional hidden fields are omitted. Defaults require an explicit
`use defaults` / `użyj domyślnych` command; they cannot confirm a write.

Use `repeat` / `powtórz` to replay the current question and `cancel` / `anuluj`
to discard the draft. Unsupported answers receive recovery guidance and the
current prompt. Corrections invalidate prior review. See the
[phrase table](CONVERSATION_ADAPTER.md#example-phrases) for all four languages.

In free-text fields, words such as `confirm` and `cancel` remain literal text.
Text input supports `/review`, `/cancel`, `/skip` and localized equivalents to
issue controls instead. The question explains this escape. An ergonomic spoken
control mode for free text remains untested; do not assume STT produces slash
commands. Live voice validation is deferred, including this limitation.

## Session and recovery behavior

Each entity/config entry owns a separate in-memory store. Sessions are scoped
by conversation ID, authenticated HA user ID, device ID, satellite ID and
language. Missing context is a distinct scope, never a wildcard. Changed context
requires a new draft. The returned conversation ID must be preserved between
turns. The agent never reads another agent's chat history or stores its own
conversation log on disk. HA's standard conversation traces/debug logs are
managed by HA and may contain utterances; this integration adds no transcript
logging or diagnostics.

Drafts expire five minutes after the last draft transition. Repeating a prompt
or attempting an invalid answer does not prolong that lifetime. A thirty-second
cleanup timer removes expired drafts and cached questions; lookups expire them
immediately. Unload/reload/restart clears everything and unregisters the timer.
An old conversation ID cannot revive a draft. Turns are serialized per entity.

When metadata refresh reports a connectivity/auth failure, the agent reports
unavailability without parsing further answers. Restore connectivity or
reauthenticate through the integration UI. A still-unexpired draft can then
continue; otherwise start again. No automatic retry can save an entry in this
increment. Metadata snapshots guide questions; the future saving callback must
refresh assignments/schema and obtain renewed review when meanings change.

## Confirmed-draft handoff

`TrackThingsConversation.confirmed_draft_callback` is an internal optional async
callback accepting `SubmissionIntent` and returning response speech. Nothing
installs it yet. Only an explicit local confirmation of the current reviewed
revision invokes it. The draft is consumed before awaiting the callback, so
concurrent confirmations cannot hand it off twice. The future saving integration
(#17) owns transport retries, uncertain outcomes, idempotency and metadata
revalidation; callback handoff alone is not a claim of successful saving.

## Verification and deferred device checks

```sh
.venv/bin/python -m pytest -q tests/test_conversation.py tests/test_conversation_sessions.py tests/test_init.py
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python scripts/check_file_sizes.py
.venv/bin/python -m pytest -q
```

The tests load the real config entry and conversation entity and invoke HA's
conversation API. Synthetic cached metadata drives Headache/Anna/Ben transcripts.
Expected: subject clarification, typed pain/severity answers, correction from
seven to six, review, then saving unavailable and zero HTTP POSTs. The same
transcript runs in all four languages. Session tests cover context boundaries,
expiry, cancellation, reload and a mocked one-time confirmed callback. These are
automated text replays, not manual Assist UI or microphone evidence.

Deferred at the owner's request: disposable Assist UI/pipeline walkthrough;
English/Polish STT/TTS and actual follow-up listening; Google/Nest speaker
models, firmware, account/region/language matrix and any multi-turn transport.
Google fixed-script [summary](GOOGLE_DAILY_SUMMARY.md) and
[entry](GOOGLE_FIXED_ENTRY.md) shortcuts remain the documented speaker path.
They do not forward arbitrary speech or follow-up answers to this agent.

API reference: Home Assistant's
[conversation entity contract](https://developers.home-assistant.io/docs/core/entity/conversation/).
The agent overrides `async_process` to own ephemeral session handling and returns
`ConversationResult.continue_conversation` for questions/review.
