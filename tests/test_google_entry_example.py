"""Run the shipped fixed-entry blueprint through HA and the real write action."""

from pathlib import Path
from shutil import copyfile
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml

from .api_fixtures import SUBJECT, TRACKER
from .create_entry_fixtures import setup_writer
from .test_create_entry_retries import idempotent_sink

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
BLUEPRINT = Path("blueprints/script/track_things/fixed_entry.yaml")


async def install(hass, entry, **inputs):
    destination = Path(hass.config.path(str(BLUEPRINT)))

    def copy():
        destination.parent.mkdir(parents=True, exist_ok=True)
        copyfile(EXAMPLES / BLUEPRINT, destination)

    await hass.async_add_executor_job(copy)
    assert await async_setup_component(
        hass,
        "script",
        {
            "script": {
                "track_things_fixed_entry": {
                    "alias": "Track Things fixed entry",
                    "use_blueprint": {
                        "path": "track_things/fixed_entry.yaml",
                        "input": {
                            "config_entry_id": entry.entry_id,
                            "tracker_id": TRACKER["id"],
                            "subject_id": SUBJECT["id"],
                            "values": {"severity": 6},
                            "tts_entity": "tts.synthetic",
                            "output_speaker": "media_player.nest_audio",
                            **inputs,
                        },
                    },
                }
            }
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get("script.track_things_fixed_entry") is not None
    speak = AsyncMock()
    hass.services.async_register("tts", "speak", speak)
    return speak


async def invoke(hass, context=None):
    await hass.services.async_call(
        "script", "track_things_fixed_entry", {}, blocking=True, context=context
    )
    await hass.async_block_till_done()


def posts(http):
    return [c for c in http.request.call_args_list if c.args[0] == "POST"]


@pytest.mark.parametrize("lose_first", [False, True])
async def test_creation_and_lost_response_retry(hass, config_entry, auth_http, lose_first):
    await setup_writer(hass, config_entry, auth_http)
    writes = idempotent_sink(auth_http, lose_first=lose_first)
    speak = await install(hass, config_entry)
    await invoke(hass)
    assert len(writes) == 1
    attempts = posts(auth_http)
    assert len(attempts) == (2 if lose_first else 1)
    assert len({c.kwargs["headers"]["Idempotency-Key"] for c in attempts}) == 1
    assert all(c.kwargs["json"] == attempts[0].kwargs["json"] for c in attempts)
    assert writes[0]["values"] == {"severity": 6}
    assert writes[0]["subjectId"] == SUBJECT["id"]
    assert writes[0]["source"] == "manual"
    assert speak.call_args.args[0].data == {
        "entity_id": ["tts.synthetic"],
        "media_player_entity_id": "media_player.nest_audio",
        "language": "en",
        "message": "Entry saved in Track Things.",
    }
    await invoke(hass)
    assert len(writes) == 2
    assert len({c.kwargs["headers"]["Idempotency-Key"] for c in posts(auth_http)}) == 2


@pytest.mark.parametrize("failure", ["missing", "assignment", "schema", "offline"])
async def test_failures_never_announce_success(hass, config_entry, auth_http, failure):
    await setup_writer(hass, config_entry, auth_http)
    speak = await install(
        hass, config_entry, values={} if failure == "missing" else {"severity": 6}
    )

    async def request(method, url, **kwargs):
        if method == "GET":
            tracker = {**TRACKER, "subjectIds": []} if failure == "assignment" else TRACKER
            return auth_http.respond(tracker if "/trackers/" in url else SUBJECT)
        return auth_http.respond(
            {"error": {"code": "tracker_schema_changed", "message": "private sentinel"}},
            status=503 if failure == "offline" else 409,
        )

    auth_http.request.side_effect = request
    await invoke(hass)
    assert len(posts(auth_http)) == (0 if failure in {"missing", "assignment"} else 2)
    speak.assert_awaited_once()
    assert speak.call_args.args[0].data["message"].startswith("Entry could not be confirmed.")
    trace = next(reversed(hass.data["trace"]["script.track_things_fixed_entry"].runs.values()))
    assert trace.as_extended_dict()["script_execution"] == "aborted"


async def test_fixed_occurrence_polish_and_tts_failure(hass, config_entry, auth_http):
    await setup_writer(hass, config_entry, auth_http)
    writes = idempotent_sink(auth_http)
    occurrence = "2026-09-08T12:00:00+02:00"
    speak = await install(
        hass, config_entry, occurred_at=occurrence, language="pl", tts_language="pl"
    )
    speak.side_effect = HomeAssistantError("speaker offline")
    with pytest.raises(HomeAssistantError, match="speaker offline"):
        await invoke(hass)
    assert len(writes) == len(posts(auth_http)) == 1
    assert writes[0]["occurredAt"] == occurrence
    assert speak.call_args.args[0].data["message"] == "Zapisano wpis w Track Things."


def test_selective_google_exposure():
    config = load_yaml(str(EXAMPLES / "google_assistant_fixed_entry.yaml"))["google_assistant"]
    assert config["expose_by_default"] is False
    assert config["entity_config"] == {
        "script.track_things_fixed_entry": {"expose": True, "name": "Track Things fixed entry"}
    }


@pytest.mark.parametrize("response", [{}, {"entry": {}}, {"entry": {"id": ""}}])
async def test_malformed_response_and_previous_success(hass, config_entry, auth_http, response):
    from homeassistant.core import SupportsResponse

    await setup_writer(hass, config_entry, auth_http)
    idempotent_sink(auth_http)
    speak = await install(hass, config_entry)
    await invoke(hass)
    assert speak.call_args.args[0].data["message"] == "Entry saved in Track Things."

    async def malformed(call):
        return {"request_id": call.data["request_id"], **response}

    hass.services.async_register(
        "track_things", "create_entry", malformed, supports_response=SupportsResponse.ONLY
    )
    await invoke(hass)
    assert speak.call_args.args[0].data["message"].startswith("Entry could not be confirmed.")


async def test_separate_activations_sharing_parent_context(hass, config_entry, auth_http):
    from homeassistant.core import Context

    await setup_writer(hass, config_entry, auth_http)
    writes = idempotent_sink(auth_http)
    await install(hass, config_entry, occurred_at="2026-09-08T12:00:00+02:00")
    parent = Context()
    await invoke(hass, parent)
    await invoke(hass, parent)
    assert len(writes) == 2
    assert len({c.kwargs["headers"]["Idempotency-Key"] for c in posts(auth_http)}) == 2
