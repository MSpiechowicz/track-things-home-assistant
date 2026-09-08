"""Execute the shipped blueprint with real HA scripts and mocked service edges."""

from pathlib import Path
from shutil import copyfile
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
BLUEPRINT = Path("blueprints/script/track_things/daily_summary.yaml")
INPUTS = {
    "config_entry_id": "synthetic-account",
    "tts_entity": "tts.synthetic",
    "output_speaker": "media_player.nest_audio",
}


@pytest.fixture
async def services(hass):
    """No Google, backend, TTS provider, or speaker network connection is made."""
    calendar = AsyncMock(return_value={"summary": "2026-09-08: 0 entries.", "total": 0})
    speak = AsyncMock(return_value=None)
    hass.services.async_register(
        "track_things", "get_daily_calendar", calendar, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register("tts", "speak", speak)
    return calendar, speak


async def install_example(hass, **inputs):
    """Load the actual YAML through HA's blueprint and script validators."""
    destination = Path(hass.config.path(str(BLUEPRINT)))

    def copy_blueprint():
        destination.parent.mkdir(parents=True, exist_ok=True)
        copyfile(EXAMPLES / BLUEPRINT, destination)

    await hass.async_add_executor_job(copy_blueprint)
    assert await async_setup_component(
        hass,
        "script",
        {
            "script": {
                "track_things_daily_summary": {
                    "alias": "Track Things daily summary",
                    "use_blueprint": {
                        "path": "track_things/daily_summary.yaml",
                        "input": {**INPUTS, **inputs},
                    },
                }
            }
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get("script.track_things_daily_summary") is not None


async def invoke(hass):
    await hass.services.async_call("script", "track_things_daily_summary", {}, blocking=True)
    await hass.async_block_till_done()


def assert_failed_calendar_trace(hass):
    traces = hass.data["trace"]["script.track_things_daily_summary"].runs
    trace = next(reversed(traces.values())).as_extended_dict()
    assert trace["script_execution"] == "aborted"
    result = trace["trace"][trace["last_step"]][-1]["result"]
    assert result["error"] is True
    assert result["stop"].startswith("Track Things daily calendar failed")


@pytest.mark.parametrize(
    "language,tts_language,total,summary",
    [
        ("en", "en-US", 2, "2026-09-08: 2 entries. Anna · Headache Anna · Headache"),
        ("en", "en", 0, "2026-09-08: 0 entries."),
        ("pl", "pl", 1, "2026-09-08: 1 wpis. Anna · Headache"),
        ("pl", "pl-PL", 0, "2026-09-08: 0 wpisów."),
    ],
)
async def test_summary_and_empty_day(hass, services, language, tts_language, total, summary):
    calendar, speak = services
    calendar.return_value = {"summary": summary, "total": total, "entries": [{"note": "private"}]}
    await install_example(hass, summary_language=language, tts_language=tts_language)
    await invoke(hass)
    calendar.assert_awaited_once()
    assert calendar.call_args.args[0].data == {
        "config_entry_id": "synthetic-account",
        "language": language,
    }
    speak.assert_awaited_once()
    assert speak.call_args.args[0].data == {
        "entity_id": ["tts.synthetic"],
        "media_player_entity_id": "media_player.nest_audio",
        "language": tts_language,
        "message": summary,
    }


@pytest.mark.parametrize("language", ["en", "pl"])
async def test_backend_error_announces_failure_and_keeps_failed_trace(hass, services, language):
    calendar, speak = services
    calendar.side_effect = HomeAssistantError("synthetic backend unavailable")
    await install_example(hass, summary_language=language)
    await invoke(hass)
    assert_failed_calendar_trace(hass)
    message = speak.call_args.args[0].data["message"]
    assert message == (
        "Nie udało się pobrać kalendarza Track Things. Spróbuj ponownie później."
        if language == "pl"
        else "Unable to read the Track Things calendar. Please try again later."
    )
    speak.assert_awaited_once()
    assert "synthetic backend unavailable" not in message


@pytest.mark.parametrize("response", [{}, {"summary": ""}, {"summary": None}, {"summary": "  "}])
async def test_invalid_response_cannot_be_announced_as_empty_success(hass, services, response):
    calendar, speak = services
    calendar.return_value = response
    await install_example(hass)
    await invoke(hass)
    assert_failed_calendar_trace(hass)
    assert speak.call_args.args[0].data["message"].startswith("Unable to read")


@pytest.mark.parametrize("backend_fails", [False, True])
async def test_tts_failure_stops_without_retry_or_alternate_speaker(hass, services, backend_fails):
    calendar, speak = services
    if backend_fails:
        calendar.side_effect = HomeAssistantError("backend offline")
    speak.side_effect = HomeAssistantError("speaker unavailable")
    await install_example(hass)
    with pytest.raises(HomeAssistantError, match="speaker unavailable"):
        await invoke(hass)
    calendar.assert_awaited_once()
    speak.assert_awaited_once()
    assert speak.call_args.args[0].data["media_player_entity_id"] == "media_player.nest_audio"


async def test_failed_second_invocation_never_reuses_previous_summary(hass, services):
    calendar, speak = services
    calendar.return_value = {"summary": "First invocation only", "total": 1}
    await install_example(hass, output_speaker="media_player.nest_hub")
    await invoke(hass)
    calendar.side_effect = HomeAssistantError("backend offline")
    await invoke(hass)
    assert_failed_calendar_trace(hass)
    messages = [call.args[0].data["message"] for call in speak.call_args_list]
    assert messages == [
        "First invocation only",
        "Unable to read the Track Things calendar. Please try again later.",
    ]
    assert all(
        call.args[0].data["media_player_entity_id"] == "media_player.nest_hub"
        for call in speak.call_args_list
    )


def test_google_configuration_exposes_only_the_intended_script():
    example = load_yaml(str(EXAMPLES / "google_assistant_daily_summary.yaml"))
    config = example["google_assistant"]
    assert config["expose_by_default"] is False
    assert config["entity_config"] == {
        "script.track_things_daily_summary": {"expose": True, "name": "Track Things daily summary"}
    }
