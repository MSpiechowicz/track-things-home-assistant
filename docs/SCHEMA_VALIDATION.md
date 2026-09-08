# Dynamic field validation

`custom_components/track_things/schema.py` validates serialized schema objects
(the `schema` inside a schema-version response) and entry `values` without runtime,
network, or third-party imports. Integration callers can import these functions:

```python
from custom_components.track_things.schema import (
    normalize_draft_values,
    resolve_field_visibility,
    validate_entry_values,
)

visibility = resolve_field_visibility(schema, draft)  # keyed by field ID
# After changing a controlling answer, explicitly drop now-hidden descendants.
normalized = normalize_draft_values(schema, draft)
validate_entry_values(normalized, schema)  # None on success
```

Validation never mutates the schema or values. Normalization returns a deep copy,
removes only hidden fields, and preserves unknown keys and invalid visible values
so validation can report them. It does not insert required/default answers.
Do not normalize submitted entries to bypass hidden-value rejection: normalization
is an explicit draft-editing operation.

`EntryValueError` has `code="invalid_request"`, a `key`, and a `reason`
(`required`, `hidden`, `unknown`, `invalid`, or `type` for a non-object input).
`SchemaUnavailableError` has `code="tracker_schema_unavailable"`. Messages do not
include supplied values; no logging or submission occurs. The module validates
backend runtime schema structure, including ordered conditional references,
required boolean/select controllers, and unique field/option identifiers.

## Backend compatibility

The contract was checked against backend commit
`4b3217a35578fcdd6061e046fce3a245ed2c9fde` on 2026-09-08:

- `src/api/shared/tracker_schema.ts`: runtime schema parsing and visibility.
- `src/api/shared/tracker_values.ts`: entry values and slider/date checks.

Use field **keys** for values, field **IDs** for conditional references, and
option **IDs** for choices. Labels may change without changing saved values.
Conditions run in schema array order, ignoring the presentation `order` property.
A controller must be visible and have a supplied value for either `equals` or
`not_equals` to activate a child. Boolean comparison is strict: `0` is not `false`.

Compatibility intentionally preserves the runtime's existing policy:

- Required means present. Empty text, empty multiselect, zero, and false are
  accepted when their type is correct. Supplied null is invalid, even if optional.
- Number/slider inputs must be finite numbers; booleans are not numbers.
- Only sliders enforce `validation.min`, `max`, and positive `step`; step is based
  on min (or zero) with a quotient tolerance of `1e-9`. Malformed step is a schema
  error; malformed min/max is a value error when that slider is supplied.
- Text length and ordinary number bounds are not enforced by the backend runtime.
- Dates are exact, real `YYYY-MM-DD` strings, including ECMAScript's year `0000`.
  Timestamps, timezone suffixes, and invalid leap days are rejected.
- Choices must contain option IDs. Multiselect rejects duplicates and unknown IDs.
- Hidden values are rejected even if null. Visible required fields must be present.
- Unknown keys are rejected, preserving the backend's existing empty-string-key
  exception (its first unknown-key truthiness check). This helper does not add a
  new backend validation policy.
- Runtime schema parsing does not enforce the schema envelope's version; version
  conflict handling remains the entry submission API's responsibility.

The API accepts serialized JSON objects; callers should not supply arbitrary Python
objects. Importing through the integration package initializes the existing HA
package; the module itself can also be loaded directly using standard-library
`importlib`, as the isolated subprocess test demonstrates with site packages off.

## Reproducible verification

In the repository's test environment, with no Home Assistant server or backend
running and internet sockets disabled by the test configuration:

```sh
python -m pytest -q tests/test_schema.py tests/test_schema_visibility.py
python -m ruff check .
python -m ruff format --check .
python scripts/check_file_sizes.py
python -m pytest -q
```

The focused tests replay `tests/fixtures/schema_contract.json` and inspect a
representative conditional transport/delay schema, including label changes,
serialized key/option preservation, and pruning a complete hidden chain. The
isolated subprocess verifies that the module loads without Home Assistant,
site packages, or socket access.

To check fixture expectations independently against a local backend checkout,
using Deno without network permission:

```sh
deno run --no-config --allow-read scripts/verify_schema_contract.ts \
  /absolute/path/to/track-things-backend
```

This optional cross-repository check is not required for ordinary Python CI.
On 2026-09-08 it reported **157 schema contract cases match the backend runtime**.
The focused Python tests passed **188 cases**. Fixture replay is the manual
inspection for this pure module: train/true/zero remains valid after translating
labels; switching to car rejects stale hidden details until explicit normalization
removes both descendants. No hardware or production data is involved.
