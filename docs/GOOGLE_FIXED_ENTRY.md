# Google Home fixed-entry shortcut

The [fixed-entry blueprint](../examples/blueprints/script/track_things/fixed_entry.yaml)
records preconfigured values through `track_things.create_entry` and announces
an acknowledged save or an unconfirmed outcome on one selected speaker.
Invoking the shortcut authorizes that write; there is no confirmation question.
The tracker, subject, values, and account are saved configuration, never inferred
from the speaker or supplied by Google speech.

This standalone shortcut does not depend on the conversation POC. Questions and
follow-up answers require the planned Assist conversation flow; this blueprint
does not implement dialogue or a Google microphone bridge.

## Installation

Use Home Assistant 2026.9 or later with a configured Track Things account, an
active selected manual tracker, its assigned subject, and a working TTS entity
and output media player. Start with a disposable workspace.

1. Copy `examples/blueprints/script/track_things/fixed_entry.yaml` to
   `blueprints/script/track_things/fixed_entry.yaml` in your HA config directory.
2. Reload blueprints under **Settings → Automations & scenes → Blueprints** and
   create a script from **Track Things fixed entry**.
3. Select the account, enter the tracker and assigned subject IDs, and supply an
   object containing all required current schema values, for example `severity: 6`.
   See the [create-entry contract](CREATE_ENTRY_ACTION.md). Defaults are not added
   automatically; tracker selection, assignment, and schema are revalidated.
4. Explicitly choose the occurrence rule. The default `{{ now().isoformat() }}`
   means the time this run starts, with a timezone. For a fixed historical event,
   use a timezone-bearing timestamp such as `2026-09-08T12:00:00+02:00`.
   The occurrence and field templates are evaluated once before any write attempt.
5. Choose the fixed speaker, TTS entity, announcement language (`en` or `pl`),
   and a matching provider-supported TTS language code. Output always plays here,
   regardless of which Google device starts the command.
6. Save as `script.track_things_fixed_entry`, validate configuration, and run in
   HA first. Inspect the trace and compare the entry with the frontend.

For YAML-managed `scripts.yaml`:

```yaml
track_things_fixed_entry:
  alias: Track Things fixed entry
  use_blueprint:
    path: track_things/fixed_entry.yaml
    input:
      config_entry_id: YOUR_CONFIG_ENTRY_ID
      tracker_id: YOUR_MANUAL_TRACKER_ID
      subject_id: YOUR_ASSIGNED_SUBJECT_ID
      occurred_at: "{{ now().isoformat() }}"
      values:
        severity: 6
      tts_entity: tts.YOUR_TTS_ENTITY
      output_speaker: media_player.YOUR_SPEAKER
      language: en
      tts_language: en
```

Merge into existing scripts; do not duplicate configuration keys. The script
uses `mode: single`, so an overlapping activation is ignored with an HA warning.

## Google exposure

With Home Assistant Cloud, enable Google Assistant exposure for this script in
**Settings → Voice assistants → Expose**. With the manual integration, merge the
[exposure example](../examples/google_assistant_fixed_entry.yaml) into your
existing Google configuration, preserving project and authentication settings.
It uses `expose_by_default: false` and explicitly exposes only this script.
Review existing exposures separately and keep other write/helper scripts hidden.

Sync devices, then activate **Track Things fixed entry**, or configure a Google
routine to activate that scene/script. Follow the existing
[daily-summary exposure instructions](GOOGLE_DAILY_SUMMARY.md#expose-only-the-intended-shortcut)
for setup and room assignment. Exposure allows household members with access to
invoke these configured writes. Choose a name that makes the recorded event clear.
Google's activation acknowledgement is not proof that an entry was saved.
Polish TTS does not establish Polish recognition support on Google speakers.

## Retries and recovery

Each activation captures a request ID from its HA execution context plus a random per-run suffix and freezes
its occurrence and values. There are at most two write attempts with identical
inputs and the same ID. The backend's durable idempotency ledger prevents a lost
response followed by a retry from creating a second entry. Every attempt still
uses the shared action's current assignment and schema validation.

Only a matching request ID and an entry ID trigger the generic success message.
Validation, schema conflicts, and connection failures cannot produce success.
After two unconfirmed attempts, the script attempts a generic warning and ends
with a failed trace. Some HA configuration/template errors stop immediately;
fix those in the trace. No backend content, notes, or names are sent to TTS.

A new activation is a new intentional entry with a new ID. **Do not repeat the
Google command to recover an uncertain save.** First inspect the frontend and
HA trace. If recovery is needed, call `track_things.create_entry` directly using
the trace's exact request ID, occurrence, account, tracker, subject, and values.
Do not reuse a key with changed content or replay after editing the schema.
This example does not persist recovery data across HA restarts; retain the trace
before restarting and inspect the backend if the trace is unavailable.

TTS failure does not retry a successful write. If audio is missing, inspect the
trace and frontend before invoking again. Successful TTS dispatch cannot prove
audible playback. Traces contain the configured entry values; handle them as
account data and do not publish unsanitized traces.

## Verification

```sh
python -m pytest -q tests/test_google_entry_example.py
python -m ruff check .
python -m ruff format --check .
python scripts/check_file_sizes.py
python -m pytest -q
```

Offline tests load the actual blueprint in HA and invoke the real create-entry
action, with HTTP and TTS mocked. They verify configured values, occurrence,
missing fields, stale assignments, schema rejection, bounded retries, a lost
response with one ledger entry, distinct activations, Polish output, speaker
failure, and selective exposure. The ledger is a fixture, not a live database.

Pending manual acceptance in a disposable installation:

1. Import and validate the configured script. Invoke from Google Home and verify
   the exact tracker, subject, occurrence, and values in the frontend (one entry).
2. Add a required schema field without changing the script. Invoke again:
   expect an unconfirmed warning and no new entry. Repeat with a removed assignment.
3. Restore valid configuration and exercise a lost response with the same
   request ID; expect one entry. Verify the configured speaker announces success.
4. Record HA/TTS versions, speaker model/firmware, region/language, and actual
   versus expected outcomes. Check that no unintended scripts are exposed.

Real Google invocation and audible speaker/frontend checks have **not been run**
in this development environment. They remain required acceptance evidence.

References: [HA script errors and response variables](https://www.home-assistant.io/docs/scripts/)
and [blueprint inputs](https://www.home-assistant.io/docs/blueprint/schema/),
checked with Context7 on 2026-09-08.
