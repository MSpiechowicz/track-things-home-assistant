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

## Multiple workspaces, including shared workspaces

Connect each workspace once through **Settings → Devices & services → Add
integration → Track Things**, signing in with the same Track Things account and
selecting a different accessible workspace. A workspace shared with your account
can be connected this way; the owner does not need to give you their credentials.
The sharing must grant permission to create entries for writes to succeed.

Open **Configure** on the Track Things instance whose natural voice agent you
use. Select **Workspaces available to the natural voice agent** and optionally a
**Preferred workspace for ambiguous requests**. Only the current workspace is
enabled by default. Select trackers in each workspace's own integration options.
The setting is per agent instance, not per speaker or recognized family member.

One phone Assist agent can then route requests across the enabled workspaces:

- “Log Migraine” selects workspace A if that is its only eligible match.
- “Log Poo” selects workspace B if that is its only eligible match.
- “Log Migraine in Family” selects an explicitly named workspace.
- If several workspaces match, a configured preference wins among those matches;
  otherwise the assistant lists workspace names. Reply with one listed name.

Gemini extracts names; deterministic code checks the connected account, enabled
scope, tracker and subject eligibility before choosing. An explicit workspace
never falls back to another workspace. Duplicate workspace names need distinct
Home Assistant integration titles so the choice is unambiguous.

Every draft response/review states the workspace. A draft stays in that workspace
until completion or cancellation. Cancel before switching workspaces. Drafts and
pending choices expire, remain scoped to the original HA conversation/user/device,
and are cleared by restart. Removing a workspace from the scope or unloading its
integration prevents continuing that draft; restore access or start fresh after
checking any uncertain save. The backend remains authoritative for permissions.

Enabling additional workspaces also sends their selected tracker/subject/schema
metadata to the configured Gemini interpreter. Workspace routing does not create
new trackers; it creates entries in existing trackers. A local phone Assist test
confirmed that a request found its tracker in a second enabled workspace. This
is a user-reported routing result; automated tests cover routing and isolation.
