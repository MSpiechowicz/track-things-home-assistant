"""Half-open overlap with explicit timezone and DST boundaries."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from homeassistant.components.calendar import CalendarEvent

from custom_components.track_things.calendar_mapping import calendar_event_overlaps

BERLIN = ZoneInfo("Europe/Berlin")


def test_exclusive_edges_and_containing_ranges():
    event = CalendarEvent(date(2026, 9, 8), date(2026, 9, 11), "Three days")
    for day, expected in [(7, False), (8, True), (9, True), (10, True), (11, False)]:
        start = datetime(2026, 9, day, tzinfo=BERLIN)
        assert (
            calendar_event_overlaps(event, start, start + timedelta(days=1), time_zone=BERLIN)
            is expected
        )
    assert calendar_event_overlaps(
        event,
        datetime(2026, 9, 1, tzinfo=UTC),
        datetime(2026, 10, 1, tzinfo=UTC),
        time_zone=BERLIN,
    )


@pytest.mark.parametrize(("day", "hours"), [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25)])
def test_all_day_dst_uses_local_midnights(day, hours):
    event = CalendarEvent(day, day + timedelta(days=1), "DST")
    start = datetime.combine(day, datetime.min.time(), BERLIN).astimezone(UTC)
    end = start + timedelta(hours=hours)
    assert calendar_event_overlaps(event, end - timedelta(seconds=1), end, time_zone=BERLIN)
    assert not calendar_event_overlaps(event, end, end + timedelta(seconds=1), time_zone=BERLIN)
    assert not calendar_event_overlaps(event, start - timedelta(seconds=1), start, time_zone=BERLIN)


def test_timezone_is_explicit_and_does_not_shift_period_dates():
    event = CalendarEvent(date(2026, 9, 8), date(2026, 9, 9), "Day")
    start = datetime(2026, 9, 7, 22, tzinfo=UTC)
    end = start + timedelta(minutes=1)
    assert calendar_event_overlaps(event, start, end, time_zone=BERLIN)
    assert not calendar_event_overlaps(event, start, end, time_zone=ZoneInfo("America/New_York"))


def test_fold_compares_instants_not_wall_clock():
    first = datetime(2026, 10, 25, 2, 30, tzinfo=BERLIN, fold=0)
    second = first.replace(fold=1)
    # Construct end in UTC: wall-clock arithmetic on fold=1 resets fold to zero.
    event = CalendarEvent(second, second.astimezone(UTC) + timedelta(minutes=1), "Second")
    assert not calendar_event_overlaps(event, first, first + timedelta(minutes=1), time_zone=BERLIN)
    assert calendar_event_overlaps(
        event, second, second.astimezone(UTC) + timedelta(seconds=1), time_zone=BERLIN
    )
    assert not calendar_event_overlaps(
        event, event.end, event.end + timedelta(minutes=1), time_zone=BERLIN
    )


@pytest.mark.parametrize("offset", [0, -1])
def test_empty_or_reversed_query(offset):
    event = CalendarEvent(date(2026, 9, 8), date(2026, 9, 9), "Day")
    start = datetime(2026, 9, 8, tzinfo=UTC)
    assert not calendar_event_overlaps(
        event, start, start + timedelta(days=offset), time_zone=BERLIN
    )


def test_naive_query_rejected():
    event = CalendarEvent(date(2026, 9, 8), date(2026, 9, 9), "Day")
    with pytest.raises(ValueError, match="timezone"):
        calendar_event_overlaps(event, datetime(2026, 9, 8), datetime(2026, 9, 9), time_zone=BERLIN)
