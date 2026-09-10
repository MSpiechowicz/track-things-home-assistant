"""Cached tracker selection; options changes do not discard schema caches."""

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .coordinator import CONF_TRACKER_IDS
from .voice_options_flow import VoiceOptionsMixin
from .workspace_routing import CONF_PREFERRED, CONF_WORKSPACES


class TrackerOptionsFlow(VoiceOptionsMixin, OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        runtime = getattr(self.config_entry, "runtime_data", None)
        if runtime is None:
            return self.async_abort(reason="not_loaded")
        trackers = runtime.coordinator.store.snapshot.trackers
        workspace_entries = {
            entry.entry_id: entry.title
            for entry in self.hass.config_entries.async_entries("track_things")
            if entry.data["backend_url"] == self.config_entry.data["backend_url"]
            and entry.data["user_id"] == self.config_entry.data["user_id"]
        }
        errors = {}
        if user_input is not None:
            selected = user_input.get(CONF_TRACKER_IDS, [])
            if not isinstance(selected, list) or any(
                not isinstance(key, str) or key not in trackers for key in selected
            ):
                errors["base"] = "invalid_tracker"
            elif any(
                key not in workspace_entries
                for key in user_input.get(CONF_WORKSPACES, [self.config_entry.entry_id])
            ) or (
                user_input.get(CONF_PREFERRED, "")
                and user_input[CONF_PREFERRED]
                not in user_input.get(CONF_WORKSPACES, [self.config_entry.entry_id])
            ):
                errors["base"] = "invalid_workspace"
            else:
                self._pending_options = {**self.config_entry.options, CONF_TRACKER_IDS: selected}
                for key in (CONF_WORKSPACES, CONF_PREFERRED):
                    if key in user_input:
                        self._pending_options[key] = user_input[key]
                if user_input.get("configure_voice", False):
                    return await self.async_step_voice()
                return self.async_create_entry(title="", data=self._pending_options)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional("configure_voice", default=False): bool,
                    vol.Optional(
                        CONF_WORKSPACES,
                        default=self.config_entry.options.get(
                            CONF_WORKSPACES, [self.config_entry.entry_id]
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": key, "label": title}
                                for key, title in workspace_entries.items()
                            ],
                            multiple=True,
                        )
                    ),
                    vol.Optional(
                        CONF_PREFERRED, default=self.config_entry.options.get(CONF_PREFERRED, "")
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[{"value": "", "label": "Ask when ambiguous"}]
                            + [
                                {"value": key, "label": title}
                                for key, title in workspace_entries.items()
                            ]
                        )
                    ),
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
