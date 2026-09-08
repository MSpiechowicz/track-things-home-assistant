"""Pure validation of serialized tracker schemas and entry values.

Matches backend shared/tracker_schema.ts and shared/tracker_values.ts. No values
are coerced, defaulted, or mutated. Field visibility uses array order, not order.
"""

import calendar
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

_FIELD_TYPES = frozenset(
    {"text", "textarea", "number", "slider", "boolean", "date", "select", "multiselect"}
)
# ECMAScript String.trim whitespace (Python's str.strip differs at the edges).
_JS_WHITESPACE = "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680" + (
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)


class SchemaUnavailableError(ValueError):
    """The backend runtime would reject this schema (409)."""

    code = "tracker_schema_unavailable"

    def __init__(self) -> None:
        super().__init__("The tracker schema is invalid.")


class EntryValueError(ValueError):
    """A value fails the backend contract (400), without including its content."""

    code = "invalid_request"

    def __init__(self, key: str | None, reason: str, message: str) -> None:
        self.key = key
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True)
class _Field:
    id: str
    key: str
    type: str
    required: bool
    definition: dict[str, Any]
    option_ids: frozenset[str]
    condition: dict[str, Any] | None


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip(_JS_WHITESPACE))


def _number(value: Any) -> bool:
    return type(value) in (int, float)


def _finite_number(value: Any) -> bool:
    if not _number(value):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        # JSON integers outside the JS Number range become nonfinite upstream.
        return False


def _integer(value: Any) -> bool:
    return _finite_number(value) and value == math.trunc(value)


def _fields(schema: Any) -> list[_Field]:
    if not isinstance(schema, dict) or not isinstance(schema.get("fields"), list):
        raise SchemaUnavailableError
    fields: list[_Field] = []
    earlier: dict[str, _Field] = {}
    keys: set[str] = set()
    for raw in schema["fields"]:
        if not isinstance(raw, dict):
            raise SchemaUnavailableError
        if not all(_nonempty(raw.get(key)) for key in ("id", "key", "label")):
            raise SchemaUnavailableError
        kind = raw.get("type")
        if not isinstance(kind, str) or kind not in _FIELD_TYPES:
            raise SchemaUnavailableError
        if raw["id"] in earlier or raw["key"] in keys:
            raise SchemaUnavailableError
        if "required" in raw and type(raw["required"]) is not bool:
            raise SchemaUnavailableError
        if "order" in raw and (not _integer(raw["order"]) or raw["order"] < 0):
            raise SchemaUnavailableError
        options: set[str] = set()
        if kind in ("select", "multiselect"):
            if not isinstance(raw.get("options"), list):
                raise SchemaUnavailableError
            for option in raw["options"]:
                if not isinstance(option, dict) or not all(
                    _nonempty(option.get(key)) for key in ("id", "label")
                ):
                    raise SchemaUnavailableError
                if option["id"] in options:
                    raise SchemaUnavailableError
                options.add(option["id"])
        condition = None
        if "visibleWhen" in raw:
            condition = raw["visibleWhen"]
            if not isinstance(condition, dict) or set(condition) != {
                "fieldId",
                "operator",
                "value",
            }:
                raise SchemaUnavailableError
            if not _nonempty(condition["fieldId"]) or condition["operator"] not in (
                "equals",
                "not_equals",
            ):
                raise SchemaUnavailableError
            controller = earlier.get(condition["fieldId"])
            if controller is None or not controller.required:
                raise SchemaUnavailableError
            value = condition["value"]
            if controller.type == "boolean":
                if type(value) is not bool:
                    raise SchemaUnavailableError
            elif controller.type == "select":
                if not isinstance(value, str) or value not in controller.option_ids:
                    raise SchemaUnavailableError
            else:
                raise SchemaUnavailableError
        field = _Field(
            raw["id"],
            raw["key"],
            kind,
            raw.get("required", False),
            raw,
            frozenset(options),
            condition,
        )
        fields.append(field)
        earlier[field.id] = field
        keys.add(field.key)
    return fields


def _visibility(fields: list[_Field], values: dict[str, Any]) -> dict[str, bool]:
    by_id = {field.id: field for field in fields}
    visible: dict[str, bool] = {}
    for field in fields:
        condition = field.condition
        if condition is None:
            visible[field.id] = True
            continue
        controller = by_id[condition["fieldId"]]
        present = controller.key in values
        value = values.get(controller.key)
        # JS strict equality: Python would otherwise consider 0 == False.
        matches = type(value) is type(condition["value"]) and value == condition["value"]
        visible[field.id] = (
            visible[controller.id]
            and present
            and (matches if condition["operator"] == "equals" else not matches)
        )
    return visible


def _values_object(values: Any) -> None:
    if not isinstance(values, dict) or any(not isinstance(key, str) for key in values):
        raise EntryValueError(None, "type", "values must be a JSON object.")


def resolve_field_visibility(schema: Any, values: dict[str, Any]) -> dict[str, bool]:
    """Return visibility by field ID, even for incomplete/unvalidated drafts."""
    _values_object(values)
    return _visibility(_fields(schema), values)


def normalize_draft_values(schema: Any, values: dict[str, Any]) -> dict[str, Any]:
    """Copy a draft, dropping hidden fields and descendants after a controller edit.

    Unknown keys and invalid visible values remain for validation to report.
    Required defaults are never inserted. The original and nested values survive.
    """
    _values_object(values)
    fields = _fields(schema)
    visible = _visibility(fields, values)
    hidden = {field.key for field in fields if not visible[field.id]}
    return deepcopy({key: value for key, value in values.items() if key not in hidden})


def validate_entry_values(values: dict[str, Any], schema: Any) -> None:
    """Raise SchemaUnavailableError or EntryValueError; return None on success."""
    _values_object(values)
    fields = _fields(schema)
    visible = _visibility(fields, values)
    for field in fields:
        key = field.key
        if not visible[field.id]:
            if key in values:
                raise EntryValueError(
                    key, "hidden", f"The entry value {key} belongs to a hidden detail."
                )
        elif key not in values:
            if field.required:
                raise EntryValueError(
                    key, "required", f"The required entry value {key} is missing."
                )
        else:
            _validate_value(field, values[key])
    known = {field.key for field in fields}
    for key in values:
        # Match the backend's truthy unknownKey check, including its empty-key edge case.
        if key not in known:
            if key:
                raise EntryValueError(
                    key, "unknown", f"The entry value {key} is not defined by the tracker schema."
                )
            break


def _invalid(key: str) -> None:
    raise EntryValueError(key, "invalid", f"The entry value {key} is invalid.")


def _iso_date(value: Any) -> bool:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        return False
    year, month, day = map(int, value.split("-"))
    # ECMAScript accepts ISO year 0000; datetime.date does not.
    return 1 <= month <= 12 and 1 <= day <= calendar.monthrange(year, month)[1]


def _validate_value(field: _Field, value: Any) -> None:
    kind, key = field.type, field.key
    if value is None:
        _invalid(key)
    if kind in ("text", "textarea") and not isinstance(value, str):
        _invalid(key)
    if kind in ("number", "slider") and not _finite_number(value):
        _invalid(key)
    if kind == "boolean" and type(value) is not bool:
        _invalid(key)
    if kind == "date" and not _iso_date(value):
        _invalid(key)
    if kind == "select" and (not isinstance(value, str) or value not in field.option_ids):
        _invalid(key)
    if kind == "multiselect":
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) for item in value)
            or len(set(value)) != len(value)
            or any(item not in field.option_ids for item in value)
        ):
            _invalid(key)
    if kind == "slider":
        _validate_slider(key, value, field.definition.get("validation"))


def _validate_slider(key: str, value: int | float, rules: Any) -> None:
    if not isinstance(rules, dict):
        return
    if "min" in rules and (not _number(rules["min"]) or value < rules["min"]):
        _invalid(key)
    if "max" in rules and (not _number(rules["max"]) or value > rules["max"]):
        _invalid(key)
    if "step" in rules:
        step = rules["step"]
        if not _number(step) or step <= 0:
            raise SchemaUnavailableError
        minimum = rules.get("min", 0)
        quotient = (value - minimum) / step
        # JS Math.round(±Infinity/NaN) preserves it; its comparison is false.
        if math.isfinite(quotient) and abs(quotient - round(quotient)) > 1e-9:
            _invalid(key)
