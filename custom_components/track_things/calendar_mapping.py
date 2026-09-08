"""Pure historical entry presentation; no fetching or backend mutations."""

from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any

from homeassistant.components.calendar import CalendarEvent

from .api_models import Entry, SchemaField, SchemaVersion, Subject, Tracker


def _aware(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("Calendar timestamps must include a timezone")
    return value.astimezone(UTC)


def _detail(field: SchemaField, value: Any) -> str:
    if field["type"] in ("select", "multiselect"):
        labels = {option["id"]: option["label"] for option in field.get("options", [])}
        selected = value if isinstance(value, list) else [value]
        return ", ".join(str(labels.get(item, item)) for item in selected)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def entry_to_calendar_event(
    entry: Entry,
    schema_version: SchemaVersion,
    *,
    tracker: Tracker,
    subject: Subject,
) -> CalendarEvent:
    """Map serialized data using the recorded schema and subject, including archived ones.

    Periods retain their serialized calendar dates, without timezone conversion.
    Timestamp events use UTC and a display-only minute of elapsed time.
    Mismatched metadata raises ValueError rather than mislabelling history.
    """
    if (
        schema_version["id"] != entry["schemaVersionId"]
        or schema_version["trackerId"] != entry["trackerId"]
        or tracker["id"] != entry["trackerId"]
        or subject["id"] != entry["subjectId"]
        or tracker["workspaceId"] != entry["workspaceId"]
        or subject["workspaceId"] != entry["workspaceId"]
    ):
        raise ValueError("Calendar metadata does not match the recorded entry")

    start: date | datetime
    end: date | datetime
    if period_start := entry.get("periodStart"):
        start = date.fromisoformat(period_start[:10])
        inclusive_end = date.fromisoformat((entry.get("periodEnd") or period_start)[:10])
        if inclusive_end < start:
            raise ValueError("Calendar period end precedes start")
        end = inclusive_end + timedelta(days=1)
    else:
        if entry.get("periodEnd"):
            raise ValueError("Calendar period end requires a start")
        start = _aware(datetime.fromisoformat(entry["occurredAt"]))
        end = start + timedelta(minutes=1)

    summary = f"{subject['name']} · {tracker['name']}"
    if title := entry.get("title"):
        summary += f" · {title}"
    description = []
    if note := entry.get("note"):
        description.append(note)
    # Sort a new list, never the caller's immutable historical schema.
    for field in sorted(schema_version["schema"]["fields"], key=lambda f: f.get("order", 0)):
        value = entry["values"].get(field["key"])
        if value is not None:
            description.append(f"{field['label']}: {_detail(field, value)}")
    return CalendarEvent(
        start=start,
        end=end,
        summary=summary,
        description="\n".join(description) or None,
        uid=entry["id"],
    )


def calendar_event_overlaps(
    event: CalendarEvent,
    range_start: datetime,
    range_end: datetime,
    *,
    time_zone: tzinfo,
) -> bool:
    """Check half-open intervals, interpreting all-day dates in the caller's zone.

    All comparisons use UTC instants, including DST folds. Empty/reversed ranges
    contain no events. Naive query timestamps are rejected.
    """
    query_start, query_end = _aware(range_start), _aware(range_end)
    if query_end <= query_start:
        return False

    def instant(value: date | datetime) -> datetime:
        if isinstance(value, datetime):
            return _aware(value)
        return _aware(datetime.combine(value, time.min, tzinfo=time_zone))

    event_start, event_end = instant(event.start), instant(event.end)
    return event_start < event_end and event_start < query_end and event_end > query_start
