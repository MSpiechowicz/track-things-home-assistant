"""Bounded browser authorization; device secrets remain inside the config flow."""

import asyncio
import re
from asyncio import sleep
from typing import Any

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TrackThingsApi
from .api_decode import decode_session
from .api_errors import ApiError, InvalidResponseError
from .auth import normalize_backend_url

DEFAULT_BACKEND_URL = "https://api.track-things.com"


class DeviceLinkFlow:
    """Config-flow mixin using HA-managed cancellable progress tasks."""

    _link_task: asyncio.Task | None = None
    _authorization: dict[str, Any] | None = None
    _link_error: str | None = None

    async def async_step_link(self, user_input=None):
        if self._authorization is None:
            self._data.setdefault("backend_url", DEFAULT_BACKEND_URL)
            self._data.setdefault("allow_local_http", False)
            api = TrackThingsApi(self._data["backend_url"], async_get_clientsession(self.hass))
            try:
                authorization = await api.request("POST", "/auth/device", authenticated=False)
                self._authorization = validate_authorization(
                    authorization, self._data["backend_url"], self._data["allow_local_http"]
                )
            except ApiError, ValueError:
                return self.async_abort(reason="cannot_connect")
        if self._link_task is None:
            self._link_task = self.hass.async_create_task(self._poll_link(), eager_start=False)
        if not self._link_task.done():
            return self.async_show_progress(
                step_id="link",
                progress_action="linking",
                progress_task=self._link_task,
                description_placeholders={
                    "verification_url": self._authorization["verification_uri"],
                    "user_code": self._authorization["user_code"],
                },
            )
        if self._link_task.cancelled() or self._link_task.exception() is not None:
            self._link_error = "cannot_connect"
        self._authorization = None
        return self.async_show_progress_done(next_step_id="link_finish")

    async def _poll_link(self):
        auth = self._authorization
        api = TrackThingsApi(self._data["backend_url"], async_get_clientsession(self.hass))
        delay = auth["interval"]
        try:
            async with asyncio.timeout(auth["expires_in"]):
                while True:
                    await sleep(delay)
                    try:
                        result = await api.request(
                            "POST",
                            "/auth/device/token",
                            authenticated=False,
                            body={"device_code": auth["device_code"]},
                        )
                    except ApiError as error:
                        if error.status is None or error.status == 429 or error.status >= 500:
                            delay = min(60, max(delay, error.retry_after or 5))
                            continue
                        raise
                    if not isinstance(result, dict):
                        raise InvalidResponseError()
                    status = result.get("status")
                    if status in {"pending", "slow_down"}:
                        if status == "slow_down":
                            delay = min(60, delay + 5)
                        continue
                    if status != "approved":
                        self._link_error = "link_denied" if status == "denied" else "link_expired"
                        return
                    await self._load_credentials(decode_session(result.get("session")))
                    self._data["auth_method"] = "device"
                    return
        except TimeoutError:
            self._link_error = "link_expired"
        except ApiError:
            self._link_error = "cannot_connect"

    async def async_step_link_finish(self, user_input=None):
        if self._link_error:
            return self.async_abort(reason=self._link_error)
        if self.context.get("source") == "reauth":
            entry = self._get_reauth_entry()
            if self._user["id"] != entry.data["user_id"]:
                return self.async_abort(reason="wrong_account")
            if entry.data["workspace_id"] not in self._workspaces:
                return self.async_abort(reason="workspace_unavailable")
            return self.async_update_reload_and_abort(entry, data_updates=self._data)
        if not self._workspaces:
            return self.async_abort(reason="no_workspaces")
        return await self.async_step_workspace()


def validate_authorization(value, backend_url: str, allow_local_http: bool) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidResponseError()
    if not isinstance(value.get("device_code"), str) or not re.fullmatch(
        r"ttd_[a-f0-9]{64}", value["device_code"]
    ):
        raise InvalidResponseError()
    if not isinstance(value.get("user_code"), str) or not re.fullmatch(
        r"[A-HJ-NP-Z2-9]{5}-[A-HJ-NP-Z2-9]{5}", value["user_code"]
    ):
        raise InvalidResponseError()
    url = normalize_backend_url(value.get("verification_uri"), allow_local_http)
    if (
        backend_url == DEFAULT_BACKEND_URL
        and url != "https://track-things.com/connect/home-assistant"
    ):
        raise InvalidResponseError()
    for field, low, high in [("expires_in", 1, 600), ("interval", 5, 60)]:
        if type(value.get(field)) is not int or not low <= value[field] <= high:
            raise InvalidResponseError()
    return {**value, "verification_uri": url}
