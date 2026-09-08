"""Recorded entry mapping and historical label contract."""

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta

import pytest

from custom_components.track_things.calendar_mapping import entry_to_calendar_event

from .api_fixtures import ENTRY, SCHEMA, SUBJECT, TRACKER


def mapped(entry=None, schema=None, tracker=None, subject=None):
    return entry_to_calendar_event(
        entry or deepcopy(ENTRY),
        schema or deepcopy(SCHEMA),
        tracker=tracker or deepcopy(TRACKER),
        subject=subject or deepcopy(SUBJECT),
    )


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2026-09-08T00:00:00.000Z", None, date(2026, 9, 9)),
        ("2026-09-08", "2026-09-08", date(2026, 9, 9)),
        ("2026-09-08T00:00:00Z", "2026-09-10T00:00:00Z", date(2026, 9, 11)),
    ],
)
def test_periods(start, end, expected):
    event = mapped({**ENTRY, "periodStart": start, "periodEnd": end})
    assert event.start == date(2026, 9, 8)
    assert event.end == expected
    assert event.summary == "Anna · Headache"
    assert event.uid == "entry-1"


@pytest.mark.parametrize("occurred", ["2026-09-08T00:30:00+02:00", "2026-09-07T22:30:00Z"])
def test_timestamp_is_one_elapsed_minute(occurred):
    event = mapped({**ENTRY, "occurredAt": occurred})
    assert event.start == datetime(2026, 9, 7, 22, 30, tzinfo=UTC)
    assert event.end - event.start == timedelta(minutes=1)


def test_historical_types_and_metadata_are_preserved():
    entry, schema, tracker, subject = deepcopy((ENTRY, SCHEMA, TRACKER, SUBJECT))
    tracker["currentSchemaVersionId"] = "new-schema"
    subject["archivedAt"] = "2026-09-09T00:00:00Z"
    entry["title"] = "Ból głowy"
    types = ["text", "textarea", "number", "slider", "boolean", "date", "select", "multiselect"]
    values = ["Text", "Two\nlines", 0, 6.5, False, "2026-09-08", "old", ["old", "other"]]
    schema["schema"]["fields"] = [
        {
            "id": kind,
            "key": kind,
            "label": kind.title(),
            "type": kind,
            "order": index,
            "options": [{"id": "old", "label": "Historical label"}],
        }
        for index, kind in enumerate(types)
    ]
    entry["values"] = dict(zip(types, values, strict=True))
    before = deepcopy((entry, schema, tracker, subject))
    event = mapped(entry, schema, tracker, subject)
    assert event.summary == "Anna · Headache · Ból głowy"
    assert event.description == (
        "sentinel-note\nText: Text\nTextarea: Two\nlines\nNumber: 0\nSlider: 6.5\n"
        "Boolean: No\nDate: 2026-09-08\nSelect: Historical label\n"
        "Multiselect: Historical label, other"
    )
    assert (entry, schema, tracker, subject) == before
    assert mapped({**entry, "title": "Changed"}, schema).uid == event.uid


def test_missing_optional_values_and_note():
    assert mapped({**ENTRY, "values": {}, "note": None}).description is None


@pytest.mark.parametrize("target", ["schema", "tracker", "subject"])
def test_wrong_metadata_rejected(target):
    metadata = {
        "schema": deepcopy(SCHEMA),
        "tracker": deepcopy(TRACKER),
        "subject": deepcopy(SUBJECT),
    }
    metadata[target]["id"] = "wrong"
    with pytest.raises(ValueError, match="metadata"):
        mapped(**metadata)


@pytest.mark.parametrize(
    "changes",
    [
        {"periodStart": "2026-09-09", "periodEnd": "2026-09-08"},
        {"periodEnd": "2026-09-08"},
        {"occurredAt": "2026-09-08T12:00:00"},
        {"periodStart": "2026-02-30"},
    ],
)
def test_invalid_dates_rejected(changes):
    with pytest.raises(ValueError):
        mapped({**ENTRY, **changes})
