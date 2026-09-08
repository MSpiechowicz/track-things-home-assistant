"""Conditional draft visibility and explicit pruning, independent of a runtime."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from custom_components.track_things.schema import (
    EntryValueError,
    normalize_draft_values,
    resolve_field_visibility,
    validate_entry_values,
)


@pytest.fixture
def schema():
    return json.loads((Path(__file__).parent / "fixtures/schema_chain.json").read_text())


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({}, [True, False, False]),
        ({"transport_key": "car"}, [True, False, False]),
        ({"transport_key": "train"}, [True, True, False]),
        ({"transport_key": "train", "delay_key": False}, [True, True, False]),
        ({"transport_key": "train", "delay_key": True}, [True, True, True]),
        ({"transport_key": "train", "delay_key": 1}, [True, True, False]),
        ({"transport_key": "car", "delay_key": True}, [True, False, False]),
    ],
)
def test_visibility_follows_array_order_and_controller_visibility(schema, values, expected):
    assert list(resolve_field_visibility(schema, values).values()) == expected


@pytest.mark.parametrize(
    ("value", "present", "expected"),
    [
        (False, True, True),
        (True, True, False),
        (0, True, True),
        (None, True, True),
        (False, False, False),
    ],
)
def test_not_equals_requires_present_visible_controller(schema, value, present, expected):
    schema["fields"][2]["visibleWhen"]["operator"] = "not_equals"
    values = {"transport_key": "train"}
    if present:
        values["delay_key"] = value
    assert resolve_field_visibility(schema, values)["minutes-id"] is expected
    values["transport_key"] = "car"
    assert resolve_field_visibility(schema, values)["minutes-id"] is False


def test_equals_false_uses_strict_boolean_equality(schema):
    schema["fields"][2]["visibleWhen"]["value"] = False
    assert resolve_field_visibility(schema, {"transport_key": "train", "delay_key": False})[
        "minutes-id"
    ]
    assert not resolve_field_visibility(schema, {"transport_key": "train", "delay_key": 0})[
        "minutes-id"
    ]


def test_controller_change_prunes_entire_chain_without_mutation(schema):
    values = {"transport_key": "train", "delay_key": True, "minutes_key": 15}
    validate_entry_values(values, schema)
    values["transport_key"] = "car"
    before = deepcopy(values)
    with pytest.raises(EntryValueError) as error:
        validate_entry_values(values, schema)
    assert error.value.reason == "hidden"
    normalized = normalize_draft_values(schema, values)
    assert normalized == {"transport_key": "car"}
    assert values == before
    validate_entry_values(normalized, schema)
    assert normalize_draft_values(schema, normalized) == normalized


def test_normalization_preserves_invalid_visible_and_unknown_values(schema):
    values = {
        "transport_key": "train",
        "delay_key": False,
        "minutes_key": 15,
        "unknown": ["sentinel"],
    }
    normalized = normalize_draft_values(schema, values)
    assert normalized == {"transport_key": "train", "delay_key": False, "unknown": ["sentinel"]}
    normalized["unknown"].append("changed")
    assert values["unknown"] == ["sentinel"]
    with pytest.raises(EntryValueError) as error:
        validate_entry_values(normalized, schema)
    assert error.value.reason == "unknown"
    invalid = {"transport_key": "missing-option"}
    assert normalize_draft_values(schema, invalid) == invalid
    with pytest.raises(EntryValueError):
        validate_entry_values(invalid, schema)


def test_normalization_does_not_default_newly_visible_required_values(schema):
    schema["fields"][1]["defaultValue"] = False
    normalized = normalize_draft_values(schema, {"transport_key": "train"})
    assert normalized == {"transport_key": "train"}
    with pytest.raises(EntryValueError) as error:
        validate_entry_values(normalized, schema)
    assert error.value.key == "delay_key"
    assert error.value.reason == "required"
