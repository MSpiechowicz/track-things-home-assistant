"""Labelled resource selection and literal aliases, without hand-written ID mappings."""

from copy import deepcopy

import voluptuous as vol
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
)

from .api_errors import ApiError
from .conversation_language import SENTENCES
from .voice_options import (
    CONF_ALIASES,
    CONF_DEFAULT_SUBJECT,
    catalog,
    current_metadata,
    parse_aliases,
    target_key,
)


class VoiceOptionsMixin:
    async def async_step_voice(self, user_input=None):
        try:
            metadata = await current_metadata(self.config_entry)
        except ApiError:
            return self.async_abort(reason="voice_unavailable")
        self._voice_resources = catalog(metadata)
        saved = self._pending_options.get(CONF_ALIASES, {})
        stale = {
            target for targets in saved.values() for target in targets
        } - self._voice_resources.keys()
        subjects = {
            key: subject["name"]
            for key, subject in metadata.subjects.items()
            if target_key("subjects", key) in self._voice_resources
        }
        old_default = self._pending_options.get(CONF_DEFAULT_SUBJECT, "")
        errors = {}
        if user_input is not None:
            default = user_input.get(CONF_DEFAULT_SUBJECT, "")
            target = user_input.get("target", "")
            language = user_input.get("language", "en")
            if default and default not in subjects:
                errors["base"] = "invalid_subject"
            elif language not in SENTENCES or (
                target and target not in self._voice_resources and target not in stale
            ):
                errors["base"] = "invalid_reference"
            else:
                self._pending_options[CONF_DEFAULT_SUBJECT] = default
                self._voice_language = language
                self._voice_target = target
                if target:
                    return await self.async_step_alias()
                return self.async_create_entry(title="", data=self._pending_options)
        targets = [{"value": "", "label": "—"}]
        targets.extend(
            {"value": key, "label": label} for key, label in self._voice_resources.items()
        )
        targets.extend({"value": key, "label": f"⚠ {key}"} for key in sorted(stale))
        defaults = [{"value": "", "label": "—"}]
        defaults.extend({"value": key, "label": label} for key, label in subjects.items())
        if old_default and old_default not in subjects:
            defaults.append({"value": old_default, "label": f"⚠ {old_default}"})
        return self.async_show_form(
            step_id="voice",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_DEFAULT_SUBJECT, default=old_default): SelectSelector(
                        SelectSelectorConfig(options=defaults)
                    ),
                    vol.Required("language", default="en"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": "en", "label": "English"},
                                {"value": "pl", "label": "Polski"},
                                {"value": "de", "label": "Deutsch"},
                                {"value": "fr", "label": "Français"},
                            ]
                        )
                    ),
                    vol.Optional("target", default=""): SelectSelector(
                        SelectSelectorConfig(options=targets, mode="dropdown")
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_alias(self, user_input=None):
        saved = self._pending_options.get(CONF_ALIASES, {})
        existing = saved.get(self._voice_language, {}).get(self._voice_target, [])
        errors = {}
        if user_input is not None:
            try:
                aliases = parse_aliases(user_input.get("aliases", ""))
                # Revalidate at submission, including resources removed while the form was open.
                resources = catalog(await current_metadata(self.config_entry))
                default = self._pending_options.get(CONF_DEFAULT_SUBJECT)
                if default and target_key("subjects", default) not in resources:
                    return await self.async_step_voice()
                if aliases and self._voice_target not in resources:
                    raise ValueError("invalid_reference")
            except ApiError:
                errors["base"] = "voice_unavailable"
            except ValueError as error:
                errors["base"] = str(error)
            else:
                updated = deepcopy(saved)
                targets = updated.setdefault(self._voice_language, {})
                if aliases:
                    targets[self._voice_target] = aliases
                else:
                    targets.pop(self._voice_target, None)
                self._pending_options[CONF_ALIASES] = updated
                return self.async_create_entry(title="", data=self._pending_options)
        return self.async_show_form(
            step_id="alias",
            data_schema=vol.Schema(
                {
                    vol.Optional("aliases", default="\n".join(existing)): TextSelector(
                        TextSelectorConfig(multiline=True)
                    ),
                }
            ),
            description_placeholders={
                "resource": self._voice_resources.get(
                    self._voice_target, f"⚠ {self._voice_target}"
                ),
            },
            errors=errors,
        )
