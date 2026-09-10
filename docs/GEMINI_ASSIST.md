# Natural wording through Gemini in Assist (POC)

This opt-in, English-only prototype adds **Track Things natural (Gemini POC)**
as a separate conversation agent. Your phone remains the microphone. It does not
connect a Google Nest microphone or change Google Home's exposed shortcuts.

Gemini returns one structured proposal containing an action, resource IDs,
typed field values, and an optional request to review. Exact tracker/subject names
are resolved locally to unique eligible IDs; names cannot bypass assignments. Track Things applies it
directly to the existing draft engine, without reparsing text commands. The engine returns the actual question/review, validates
fields, and saves only after a separate explicit `confirm` or `save` utterance.
Model-generated confirmation/save actions are rejected before any proposal is applied.

## Setup

1. Install this integration revision and restart Home Assistant.
2. In the Google Gemini integration, create a dedicated conversation agent.
   Set its conversation entity's name to exactly **Track Things interpreter**.
   Matching ignores capitalization and surrounding spaces. There must be exactly one matching entity.
3. In that Gemini agent's configuration, disable **Control Home Assistant**
   (no LLM APIs selected) and disable the Google Search tool. The adapter refuses
   an interpreter with either enabled. Keep its instructions simple: return the
   JSON requested by the caller, without Markdown or commentary.
4. Create a voice assistant called **Track Things natural test**. Select
   **Track Things natural (Gemini POC)** as the conversation agent, English as
   the language, and your working speech-to-text/text-to-speech providers.
   Disable **Prefer handling commands locally** for this assistant if shown.
5. Select that assistant in phone Assist. Use a disposable workspace with
   fictional trackers/subjects for initial testing.

The Gemini integration keeps and uses your existing API key. This integration
neither copies the key nor configures billing. Free-tier quotas depend on your
selected model and Google account; enabling this feature does not guarantee free
usage. It makes one interpretation request per non-control turn, with a 45-second
timeout and no automatic model retry.

## Test

Use an actual tracker label from the selected workspace. For example:

- “Log my headache and skip all details.”
- Answer any required subject/detail questions naturally.
- “Change severity to six and skip the optional notes.”
- Listen to the review, then say exactly “confirm”.
- Verify the saved entry in Track Things.

“Skip all details” requests review; it cannot bypass required fields. “My” does
not infer identity. Existing subject selection rules still apply. To discard the
draft, say “cancel”. Literal controls bypass the model; in a free-text question,
existing engine rules still treat unprefixed controls as data. Use text `/cancel`
or `/review` when needed in that case.

Only `confirm` or `save` (optionally prefixed with `/` for text) can authorize a
write. Capitalization and trailing speech punctuation are normalized, so
“Confirm.” and “CONFIRM!” work; “My confirm” does not authorize saving. Natural variations such as “yes, go ahead” are intentionally not accepted
as saving authorization in this POC. Gemini cannot grant itself permission.

## Data and limitations

Choosing this agent sends the utterance, current engine question/review, and
selected tracker/subject/schema metadata to the configured Gemini service. These
can include personal labels, field definitions, and review values. HA/Gemini may
retain conversation traces according to their settings. Use fictional data first;
review Google's API terms before using sensitive tracking data.

Each model request starts a fresh model conversation. Drafts remain isolated by
HA conversation ID, user, device, satellite, and language in the deterministic
engine, with its existing expiration and uncertain-write behavior. The original
step-by-step agent remains available and has separate draft state. Switching
agents does not transfer a draft.

This POC does not promise arbitrary natural-language accuracy. Malformed or unsafe
model output produces recovery guidance without applying a proposal. Schema
validation remains authoritative. A create/update followed by a requested review
may leave an unsaved draft still asking for required fields. No model proposal
can save it. Explicit default-value acceptance is not exposed to Gemini in this
prototype. Listen to the engine's final review before confirming.

Automated tests use mocked Gemini responses and the real HA/draft engine. They
are not live Gemini accuracy or billing evidence. Live speech/model testing is
still required after configuring the dedicated interpreter.

## Live POC evidence — 2026-09-10

The user confirmed that phone Assist with the configured Gemini interpreter could
handle a natural request specifying a tracker, named subject, and today's date.
Earlier testing also reached an acknowledged save after review and explicit
confirmation. Personal names, addresses and actual tracker data are omitted.

Fixes made during the POC include case-insensitive interpreter lookup, typed
proposals instead of text-command translation, punctuation-tolerant literal
controls, local name/assignment resolution, readable date reviews, and distinct
provider/metadata/proposal failure messages. The final offline suite passed
692 tests; lint, formatting, source-size and whitespace checks passed.

These are bounded user-reported results, not a full live accuracy evaluation.
Google Nest microphone routing remains unproven; this POC uses phone Assist.
