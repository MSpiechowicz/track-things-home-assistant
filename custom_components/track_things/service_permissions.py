"""Authorize service access against the targeted workspace's calendar entity."""

from homeassistant.exceptions import Unauthorized, UnknownUser
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN


async def async_check_access(hass, call, entry, permission):
    """Preserve trusted internal calls; fail closed for user-scoped requests."""
    if call.context.user_id is None:
        return
    user = await hass.auth.async_get_user(call.context.user_id)
    if user is None:
        raise UnknownUser(context=call.context, permission=permission)
    entity_id = er.async_get(hass).async_get_entity_id(
        "calendar", DOMAIN, f"{entry.entry_id}_calendar"
    )
    if (
        not user.is_active
        or entity_id is None
        or not user.permissions.check_entity(entity_id, permission)
    ):
        raise Unauthorized(
            context=call.context,
            entity_id=entity_id,
            config_entry_id=entry.entry_id,
            permission=permission,
        )
