"""Typed fixture replays from incomplete commands through explicit confirmation."""

from datetime import date, datetime, timedelta, timezone

import pytest

from custom_components.track_things.dialogue import DraftError, DraftPatch
from custom_components.track_things.schema import EntryValueError

from .dialogue_fixtures import NOW, complete, metadata, store


def test_fixture_replay_through_subject_details_correction_and_confirmation():
    drafts = store()
    result = drafts.start("one", metadata())
    assert result.descriptors[0].candidates == ("headache",)
    result = drafts.update("one", DraftPatch(tracker_id="headache"))
    assert result.descriptors[0].kind == "subject"
    assert result.descriptors[0].candidates == ("anna", "ben")
    assert [d.key for d in result.descriptors] == [None, "pain", "note"]
    result = drafts.update("one", DraftPatch(subject_id="anna", values={"pain": True}))
    assert [(d.kind, d.key) for d in result.descriptors] == [
        ("required", "severity"),
        ("optional", "note"),
    ]
    drafts.update("one", DraftPatch(values={"severity": 7}))
    drafts.update("one", DraftPatch(values={"severity": 6}, skip_optional=frozenset({"note"})))
    result = drafts.review("one")
    assert result.descriptors == ()
    assert result.state == "review"
    intent = drafts.confirm("one", result.revision)
    assert intent.workspace_id == "workspace"
    assert intent.payload == {
        "trackerId": "headache",
        "subjectId": "anna",
        "values": {"pain": True, "severity": 6},
        "expectedSchemaVersionId": "schema-1",
        "source": "manual",
        "occurredAt": NOW.isoformat(),
    }
    with pytest.raises(DraftError, match="draft_unavailable"):
        drafts.confirm("one", result.revision)


@pytest.mark.parametrize(
    "subjects,expected", [((), "collecting"), (("anna",), "ready"), (("anna", "ben"), "collecting")]
)
def test_missing_sole_and_ambiguous_subjects(subjects, expected):
    drafts = store()
    result = drafts.start(
        "one",
        metadata(subjects),
        DraftPatch(
            tracker_id="headache",
            values={"pain": False},
        ),
    )
    assert result.state == expected
    if expected == "ready":
        assert drafts.review("one").payload["subjectId"] == "anna"
    else:
        assert result.descriptors[0].candidates == subjects
        with pytest.raises(DraftError, match="draft_incomplete"):
            drafts.review("one")


def test_defaults_require_explicit_acceptance_and_multi_field_turns_work():
    drafts = store()
    result = drafts.start("one", metadata(("anna",)), DraftPatch(tracker_id="headache"))
    assert result.descriptors[0].key == "pain"
    with pytest.raises(DraftError, match="draft_incomplete"):
        drafts.review("one")
    result = drafts.update(
        "one",
        DraftPatch(
            accept_defaults=frozenset({"pain"}),
            values={"severity": 8, "note": "Keep exact text"},
        ),
    )
    assert result.state == "ready"
    assert drafts.review("one").payload["values"] == {
        "pain": True,
        "severity": 8,
        "note": "Keep exact text",
    }


@pytest.mark.parametrize(
    "occurrence,expected",
    [
        (None, {"occurredAt": NOW.isoformat()}),
        (
            date(2026, 9, 7),
            {
                "occurredAt": "2026-09-07T00:00:00+00:00",
                "periodStart": "2026-09-07T00:00:00+00:00",
                "periodEnd": "2026-09-07T00:00:00+00:00",
            },
        ),
        (
            datetime(2026, 9, 7, 23, tzinfo=timezone(timedelta(hours=-4))),
            {"occurredAt": "2026-09-08T03:00:00+00:00"},
        ),
    ],
)
def test_occurrence_serialization(occurrence, expected):
    drafts = store()
    complete(drafts)
    drafts.update("one", DraftPatch(occurrence=occurrence))
    payload = drafts.review("one").payload
    assert {
        key: value
        for key, value in payload.items()
        if key in {"occurredAt", "periodStart", "periodEnd"}
    } == expected


def test_naive_timestamp_rejected_and_reset_now_removes_period():
    drafts = store()
    complete(drafts)
    with pytest.raises(DraftError, match="timezone_required"):
        drafts.update("one", DraftPatch(occurrence=datetime(2026, 9, 8)))
    drafts.update("one", DraftPatch(occurrence=date(2026, 9, 7)))
    drafts.update("one", DraftPatch(reset_occurrence=True))
    assert drafts.review("one").payload["occurredAt"] == NOW.isoformat()
    assert "periodStart" not in drafts.review("one").payload


@pytest.mark.parametrize(
    "values", [{"pain": 1}, {"pain": True, "severity": 11}, {"pain": True, "severity": "7"}]
)
def test_invalid_visible_values_rejected_despite_missing_required_fields(values):
    drafts = store()
    with pytest.raises(EntryValueError):
        drafts.start("one", metadata(), DraftPatch(tracker_id="headache", values=values))
    # Failed start did not reserve the ID.
    complete(drafts)
