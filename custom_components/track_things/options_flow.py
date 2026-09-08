"""Cached tracker selection; options changes do not discard schema caches."""

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .coordinator import CONF_TRACKER_IDS
from .voice_options_flow import VoiceOptionsMixin


class TrackerOptionsFlow(VoiceOptionsMixin, OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        runtime = getattr(self.config_entry, "runtime_data", None)
        if runtime is None:
            return self.async_abort(reason="not_loaded")
        trackers = runtime.coordinator.store.snapshot.trackers
        errors = {}
        if user_input is not None:
            selected = user_input.get(CONF_TRACKER_IDS, [])
            if not isinstance(selected, list) or any(
                not isinstance(key, str) or key not in trackers for key in selected
            ):
                errors["base"] = "invalid_tracker"
            else:
                self._pending_options = {**self.config_entry.options, CONF_TRACKER_IDS: selected}
                if user_input.get("configure_voice", False):
                    return await self.async_step_voice()
                return self.async_create_entry(title="", data=self._pending_options)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional("configure_voice", default=False): bool,
                    vol.Optional(
                        CONF_TRACKER_IDS,
                        default=self.config_entry.options.get(CONF_TRACKER_IDS, list(trackers)),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": key, "label": item["name"]}
                                for key, item in trackers.items()
                            ],
                            multiple=True,
                        )
                    ),
                }
            ),
            errors=errors,
        )
