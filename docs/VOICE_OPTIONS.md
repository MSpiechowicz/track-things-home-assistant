# Voice aliases and an explicit default subject

Open Settings → Devices & services → Track Things → Configure. Keep the desired
tracker selection and enable **Configure voice aliases and default subject**.
Choose a default subject for “me”, or **—** to leave it unset. Select a language
and a labelled resource, then enter one literal alias per line. Save and repeat
for another resource or language. Choose **—** as the resource to save just the
default. Existing aliases appear when editing the same resource and language;
an empty text box removes them. Each resource accepts up to 30 aliases of at most
100 characters each.

Trackers, subjects, schema fields and choice options can have aliases. Field
labels include their tracker; option labels include both tracker and field.
English, Polish, German and French have separate mappings. For example, give
Anna the English alias `Annie` and Polish aliases `Anny` and `Annę`. In an English
Assist conversation, start `log Headache` and answer `Annie` when asked for the
subject. In Polish, start `zapisz Headache` and answer `Anny`.

A field alias such as `intensity` permits `change intensity to six`. A choice
option alias can answer the current choice question or appear in a correction.
Tracker and subject aliases also work in calendar filters, for example
`kalendarz na dzisiaj; tracker: bólu głowy; osoba: Anny`.
Aliases are literal text, not Hassil template syntax or model instructions.
Fixed commands retain their meaning; avoid command words as aliases. Free-text
answers retain their established literal-text behavior.

## Identity and clarification

Only an explicitly configured default supplies “me” (`mnie`, `ja`, `dla mnie` in
Polish; `ich`/`mich` in German; `moi` in French). These are reserved identity
phrases, not ordinary subject aliases. Answer with one when prompted for a
subject. The default must still exist, be active and be assigned to the selected
tracker; a removed assignment cannot use the default from an older draft.
Calendar filters check current assignments too, against the requested tracker or
the configured calendar trackers when no tracker filter is given.

Choosing a default does not silently select it whenever several subjects are
eligible. Speaker, device and HA user identity never choose a backend subject.
The existing sole-eligible-subject behavior remains in place. A valid draft still
requires review and explicit confirmation before any entry can be written.

Two resources may share an alias. Matching stays ambiguous and the agent asks
for clarification instead of picking the first match. Reply with a unique name
or stable ID; for an ambiguous correction, repeat the correction using the
field/option ID. Nothing about an alias authorizes a write.

## Renames and repair

Aliases are stored against stable IDs, so label-only renames preserve them.
Each turn rebuilds the validated alias mapping from current cached discovery and
schema data; changes take effect on the next turn without restarting HA or
clearing drafts. The Hassil grammar uses wildcard names, so there is no separate
static name list to reload. Backend changes become visible after metadata
refresh, and the existing write path revalidates metadata before saving.

Unavailable references are excluded from recognition and displayed with **⚠**
in configuration. Select a missing resource in its original language and clear
its aliases, then configure its replacement if needed. A removed default is
also flagged: choose a current subject or **—**. Stored references are retained
for repair rather than silently reassigned. Schema field/option aliases are
scoped to their tracker and never spill into another tracker's schema.

## Verification record

The synthetic tests configure English/Polish aliases through the real HA options
flow, rename Anna and replay requests through the Assist conversation endpoint.
Expected/actual: both aliases select Anna's stable ID after the rename. Removing
her assignment during a subject-selection draft keeps “me” at subject selection;
restoring it allows explicit selection. Shared aliases require clarification,
and editing one mapping changes the next turn without an integration reload.
Other tests cover schema references removed while a form is open, unavailable
metadata, repair of deleted resources/defaults, language and tracker separation,
choice/field aliases, and calendar filters.

```sh
.venv/bin/python -m pytest -q tests/test_voice_options.py tests/test_alias_resolution.py
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python scripts/check_file_sizes.py
.venv/bin/python -m pytest -q
```

These are automated text/API replays with synthetic resources and mocked HTTP.
The manual disposable-backend/UI walkthrough has not been performed: configure
the aliases above, use each through Assist, rename Anna in the frontend, refresh
metadata and repeat. Remove her tracker assignment, refresh metadata, then verify
“me” cannot select her. Microphone/STT/TTS and Google hardware checks remain
deferred as recorded in [the Assist guide](ASSIST_CONVERSATION.md); this change
does not establish a Google multi-turn route.
