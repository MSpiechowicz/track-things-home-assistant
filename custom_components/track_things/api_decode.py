"""Validate wire shapes without implementing dynamic-field business validation."""

from types import UnionType
from typing import Any, Literal, NotRequired, get_args, get_origin, get_type_hints, is_typeddict

from .api_errors import InvalidResponseError
from .api_models import CursorPage, Session


def matches(value: Any, model: Any) -> bool:
    """Check the JSON shape, tolerating future additional response properties."""
    if model is Any:
        return True
    origin = get_origin(model)
    args = get_args(model)
    if origin is NotRequired:
        return matches(value, args[0])
    if origin is UnionType:
        return any(matches(value, item) for item in args)
    if origin is Literal:
        return any(type(value) is type(item) and value == item for item in args)
    if is_typeddict(model):
        hints = get_type_hints(model, include_extras=True)
        return (
            isinstance(value, dict)
            and model.__required_keys__ <= value.keys()
            and all(matches(value[key], hint) for key, hint in hints.items() if key in value)
        )
    if origin is list:
        return isinstance(value, list) and all(matches(item, args[0]) for item in value)
    if origin is dict:
        return isinstance(value, dict) and all(
            matches(key, args[0]) and matches(item, args[1]) for key, item in value.items()
        )
    return type(value) is model


def decode[T](value: Any, model: type[T]) -> T:
    """Reject malformed records without including their contents in errors."""
    if not matches(value, model):
        raise InvalidResponseError(code="invalid_response")
    return value


def decode_session(value: Any) -> Session:
    """Validate credentials before allowing callers to replace stored tokens."""
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("access_token"), str)
        or not value["access_token"]
        or not isinstance(value.get("refresh_token"), str)
        or not value["refresh_token"]
        or type(value.get("expires_at")) is not int
        or value["expires_at"] <= 0
    ):
        raise InvalidResponseError(code="invalid_session_response")
    return Session(value["access_token"], value["refresh_token"], value["expires_at"])


def decode_page[T](value: Any, model: type[T]) -> CursorPage[T]:
    """Cursor mode must return an envelope, never a silent legacy-array fallback."""
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("items"), list)
        or "nextCursor" not in value
        or not (
            value["nextCursor"] is None
            or isinstance(value["nextCursor"], str)
            and 0 < len(value["nextCursor"]) <= 1024
        )
    ):
        raise InvalidResponseError(code="invalid_page")
    return CursorPage([decode(item, model) for item in value["items"]], value["nextCursor"])
