# Guided questions and the Google experiment

The product has two paths:

1. Deterministic, human-readable questions mapped to tracker schema details, with
a default-details shortcut followed by review and explicit confirmation.
2. An experimental Google Assistant/Gemini path to investigate whether real
speakers can carry those questions and subsequent answers in one conversation.

Both paths must use the same typed draft proposals and validation. This supersedes
the earlier requirement to choose only one engine before building the local
question adapter. Google transport feasibility is still unproven; this module
neither registers Google tools nor forwards speaker audio.

## Available in this increment

`QuestionAdapter` is a stateless, offline module. `AdapterContext` supplies an
authorized metadata snapshot, current descriptor/values, injected clock and
timezone, and language-scoped aliases. The caller owns sessions and passes
`Proposal.patch` to `DraftStore`. Each result is a proposal, not permission to
write. The [Assist conversation entity](ASSIST_CONVERSATION.md) now supplies
session wiring and guided review. The Google experiment remains separate work.

All four Track Things languages are supported: English (`en`), Polish (`pl`),
German (`de`) and French (`fr`). Tracker, subject and detail labels are user data;
they are not automatically translated. Aliases can provide localized spellings.

`questions(result, metadata, language)` returns ordered readable prompts and
stable keys/candidates. Recompute after every draft update so conditional fields
appear or disappear. Required and optional details retain schema order. Boolean
prompts enumerate yes/no, choice prompts enumerate labels, and sliders show
bounds. Defaults are never silently inserted.

`defaults_question(...)` describes available default values. An explicit defaults
command produces an `accept_defaults` patch, preserving answers already supplied.
After presenting the question, set `offering_defaults=True` in the context: a
localized yes proposes defaults and no requests the ordinary question flow.
Neither answer confirms a write.
Defaults are validated in schema order, including newly visible dependents.
Invalid defaults remain unanswered questions. Required details without defaults
still need answers. The runtime must then read back the complete entry and call
`DraftStore.review`, followed by a separate explicit user confirmation bound to
that review revision. A defaults command alone cannot save an entry.

## Example phrases

| Action | English | Polish | German | French |
| --- | --- | --- | --- | --- |
| Start | log headache | zapisz headache | erfasse headache | note headache |
| Boolean | yes / no | tak / nie | ja / nein | oui / non |
| Number | seven | siedem | sieben | sept |
| Correct | change Severity to six | zmień Severity na sześć | ändere Severity auf sechs | change Severity en six |
| Defaults | use defaults | użyj domyślnych | Standardwerte verwenden | utiliser les valeurs par défaut |
| Review | review | sprawdź | Zusammenfassung | résumé |
| Confirm | confirm | potwierdź | bestätigen | confirmer |
| Cancel | cancel | anuluj | abbrechen | annuler |
| Repeat | repeat | powtórz | wiederholen | répéter |
| More | more | więcej | mehr | plus |
| Skip | skip | pomiń | überspringen | passer |
| Calendar | calendar for yesterday | kalendarz na wczoraj | Kalender für gestern | calendrier pour hier |

Starting without a tracker asks which tracker. Replies select a subject or answer
the current detail. Spoken integers zero–ten and numeric literals are supported;
decimals accept `6.5` or `6,5`. Multi-choice answers use semicolon-separated labels
or IDs. Dates accept today/yesterday/tomorrow in each language and ISO dates;
occurrence commands also accept ISO timestamps. Local DST gaps and overlaps
require clarification; an explicit timestamp offset disambiguates an overlap.
Other natural date phrases or number words require rephrasing.

Free text preserves original case, punctuation and whitespace. In a text detail,
even “confirm” is content. To issue a control command in that context, prefix it
with `/` (for example `/skip`, `/pomiń`, `/überspringen`, `/passer`). A future
spoken runtime must provide an explicit control mode rather than guessing that
note content is a command. `repeat` and `more` are typed intents; the runtime
owns replaying questions and presenting further details.

Aliases map stable IDs to literal spellings under keys such as `pl:subjects`,
`de:trackers`, `fr:headache:fields`, and `en:headache:severity-id:options`.
Unknown IDs cannot match; collisions return all candidates for clarification.
No subject is inferred from speaker identity. Alias configuration UI belongs
to its own issue.

## Google/Gemini boundary

A future adapter may consume the same questions and propose the same `DraftPatch`
contract. Labels, notes and model output are untrusted data. Model assertions
that a user confirmed cannot authorize saving. Runtime code must associate an
explicit user confirmation with its current reviewed draft revision and session.
Model credentials, network calls, tool registration, and actual speaker
follow-up routing are not implemented or validated here. No claim is made about
Google speaker support in any of the four languages.

## Reproducible offline verification

```sh
.venv/bin/python -m pytest -q tests/test_conversation_adapter_contract.py tests/test_selected_conversation_adapter.py
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python scripts/check_file_sizes.py
.venv/bin/python -m pytest -q
```

The transcript fixture in `tests/test_selected_conversation_adapter.py` starts a
headache entry, selects Anna, answers pain/severity, corrects seven to six,
reviews and confirms through the real draft store in all four languages.
Expected payload: Anna/headache, pain=true and severity=6. This is an offline
adapter replay with synthetic data, not a live microphone or Google test.

Hassil grammar follows the official
[sentence syntax documentation](https://developers.home-assistant.io/docs/voice/intent-recognition/template-sentence-syntax/).
