# Google speaker conversation POC

Status: initial feasibility investigation; issue #25 remains open.
Last checked: 2026-09-10.

## Confirmed environment and evidence

The user reports that the Google Home app shows **Google Assistant**, not Gemini
for Home. Home Assistant is 2026.9.1 in Docker and Track Things is v0.20.0.
Nest displays and Nest Audio are available. Exact generations, firmware,
configured recognition language, and account country remain unrecorded.
No private network addresses or household device names are recorded here.

The user confirmed audible short TTS, a spoken zero-entry calendar summary,
and Google voice activation of the exposed example script. Local URL correction
and scoped host-firewall allowances resolved the initial audio failures.
This proves output and fixed invocation, not arbitrary voice input.

## Supported surfaces checked

Official sources checked on 2026-09-10:

| Surface | Documented capability | Implication for this POC |
| --- | --- | --- |
| [Conversational Actions](https://developers.google.com/assistant/ca-sunset) | Google retired custom Conversational Actions on June 13, 2023. | The former custom Google Assistant conversation route cannot be used. |
| [Cloud-to-cloud intents](https://developers.home.google.com/cloud-to-cloud/primer/intents) | SYNC, QUERY, EXECUTE and DISCONNECT for smart-home devices. | No general utterance/session callback is documented by this interface. |
| [Smart-home fulfillment](https://developers.home.google.com/cloud-to-cloud/primer/fulfillment) | Device commands and constrained secondary verification. | Verification challenges do not establish arbitrary schema-driven questions and answers. |
| [Local fulfillment](https://developers.home.google.com/local-home/overview) | Local execution/query of smart-home commands. | A local route does not add a general microphone stream or conversation interface. |
| [HA Google Assistant SDK](https://www.home-assistant.io/integrations/google_assistant_sdk) | HA can send requests to Google Assistant. | This is not evidence of Nest speech being forwarded into a Track Things agent. |
| [HA Assist](https://www.home-assistant.io/voice_control/) | Conversation through supported Assist clients, including the companion app. | A candidate for a separate full-conversation test, but not a Google Nest microphone bridge. |

## Current finding

For the user's confirmed Google Assistant configuration, no supported arbitrary
Nest speech/follow-up transport into Track Things has been identified in the
reviewed public interfaces. The old conversation extension is explicitly retired.
The current script connection cannot simply be replaced with a conversation
agent selection to provide that missing input path.

This is a bounded documentation finding, not a claim that every future Google
partner program or Gemini for Home capability is impossible. Gemini for Home,
the Gemini API, and HA's Gemini agent must be evaluated separately. Enabling an
LLM in HA does not establish access to a Nest microphone.

No full-dialogue device prototype or fake-entry write was run. Do not mark the
full-conversation acceptance checklist complete or claim a successful live test.

## Next checks

- Record configured language, account country, and exact model/firmware before
  making language or device-wide compatibility claims.
- If a newer Google program is proposed, require documentation showing custom
  handler registration, delivery of user answers, session correlation and access
  eligibility on existing Nest devices before implementing an adapter.
- If the user chooses Assist as the input endpoint, exercise the existing Track
  Things agent first with synthetic fixtures and an isolated fake sink. Test
  questions, corrections, review, explicit confirmation, cancellation, duplicate
  confirmation and session isolation. Keep this distinct from Google transport.
- The offline harness, final ADR, full verification and backlog dependency review
  required by #25 are still outstanding. This initial finding does not close it.

See [the nontechnical connection checklist](../GOOGLE_HOME_SETUP.md) for the
already-tested Google shortcut and speaker-output path.
