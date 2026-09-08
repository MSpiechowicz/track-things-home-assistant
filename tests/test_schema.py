"""Replay serialized cases verified against the backend runtime validators."""

import importlib.util
import json
import math
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from custom_components.track_things.schema import (
    EntryValueError,
    SchemaUnavailableError,
    validate_entry_values,
)

FIXTURES = Path(__file__).parent / "fixtures"
CASES = json.loads((FIXTURES / "schema_contract.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_backend_contract(case):
    """Schema parsing and values have the same result/error code as the backend."""
    before = deepcopy(case)
    if case["error"]:
        with pytest.raises((EntryValueError, SchemaUnavailableError)) as error:
            validate_entry_values(case["values"], case["schema"])
        assert error.value.code == case["error"]
    else:
        assert validate_entry_values(case["values"], case["schema"]) is None
    assert case == before


@pytest.mark.parametrize("kind", ["number", "slider"])
@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan, 10**400])
def test_nonfinite_numbers(kind, value):
    schema = {"fields": [{"id": "n", "key": "n", "label": "N", "type": kind}]}
    with pytest.raises(EntryValueError):
        validate_entry_values({"n": value}, schema)


@pytest.mark.parametrize("values", [None, [], "text", {1: "value"}])
def test_values_must_be_an_object(values):
    with pytest.raises(EntryValueError, match="JSON object"):
        validate_entry_values(values, {"fields": []})


def test_key_and_option_ids_survive_label_changes():
    schema = json.loads((FIXTURES / "schema_chain.json").read_text())
    values = {"transport_key": "train", "delay_key": True, "minutes_key": 0}
    serialized = json.dumps(values)
    for field in schema["fields"]:
        field["label"] = "Zmieniona etykieta"
        for option in field.get("options", []):
            option["label"] = "Zmieniona opcja"
    validate_entry_values(values, schema)
    assert json.dumps(values) == serialized


def test_errors_identify_field_and_reason_without_echoing_value():
    schema = {"fields": [{"id": "n", "key": "amount", "label": "N", "type": "number"}]}
    with pytest.raises(EntryValueError) as error:
        validate_entry_values({"amount": "sentinel-private-value"}, schema)
    assert error.value.key == "amount"
    assert error.value.reason == "invalid"
    assert "sentinel-private-value" not in str(error.value)


def test_module_runs_without_home_assistant_or_site_packages():
    """Load the pure module directly, avoiding the HA integration package initializer."""
    spec = importlib.util.find_spec("custom_components.track_things.schema")
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            """
import importlib.util
import socket
import sys

def forbidden(*args, **kwargs):
    raise AssertionError('Network access is forbidden')
socket.socket = forbidden
spec = importlib.util.spec_from_file_location('pure_schema', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.validate_entry_values({}, {'fields': []})
assert not any(name.startswith('homeassistant') for name in sys.modules)
""",
            spec.origin,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
