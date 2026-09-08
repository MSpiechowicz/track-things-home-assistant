"""Session isolation, cancellation, and frozen-clock five-minute idle expiry."""

from datetime import timedelta

import pytest

from custom_components.track_things.dialogue import DraftError, DraftPatch, DraftStore

from .dialogue_fixtures import NOW, complete, metadata, store


def test_interleaved_drafts_and_cancellation():
    drafts = store()
    complete(drafts, "one")
    complete(drafts, "two")
    drafts.update("two", DraftPatch(subject_id="ben", values={"severity": 3}))
    one = drafts.review("one")
    two = drafts.review("two")
    assert one.payload["subjectId"] == "anna"
    assert one.payload["values"]["severity"] == 7
    assert two.payload["subjectId"] == "ben"
    assert two.payload["values"]["severity"] == 3
    with pytest.raises(DraftError, match="review_required"):
        drafts.confirm("two", one.revision)
    drafts.cancel("one")
    with pytest.raises(DraftError, match="draft_unavailable"):
        drafts.confirm("one", one.revision)
    assert drafts.confirm("two", two.revision).payload == two.payload


def test_expiry_boundary_and_activity_are_per_draft():
    elapsed = [0.0]
    drafts = DraftStore(clock=lambda: NOW, idle_clock=lambda: elapsed[0])
    complete(drafts, "one")
    complete(drafts, "two")
    elapsed[0] = 299
    assert drafts.inspect("one").state == "ready"
    drafts.update("two", DraftPatch(values={"severity": 4}))
    elapsed[0] = 300
    assert drafts.expire() == ("one",)
    with pytest.raises(DraftError, match="draft_unavailable"):
        drafts.review("one")
    assert drafts.inspect("two").state == "ready"
    elapsed[0] = 599
    assert drafts.expire() == ("two",)


def test_confirmation_cannot_revive_expired_review():
    elapsed = [0.0]
    drafts = DraftStore(clock=lambda: NOW, idle_clock=lambda: elapsed[0])
    complete(drafts)
    review = drafts.review("one")
    elapsed[0] = 300
    with pytest.raises(DraftError, match="draft_unavailable"):
        drafts.confirm("one", review.revision)


def test_now_is_frozen_until_explicit_reset_and_review_is_user_activity():
    wall = [NOW]
    elapsed = [0.0]
    drafts = DraftStore(clock=lambda: wall[0], idle_clock=lambda: elapsed[0])
    complete(drafts)
    elapsed[0] = 299
    wall[0] += timedelta(minutes=4)
    assert drafts.review("one").payload["occurredAt"] == NOW.isoformat()
    elapsed[0] = 301
    drafts.update("one", DraftPatch(reset_occurrence=True))
    assert drafts.review("one").payload["occurredAt"] == wall[0].isoformat()


def test_clearing_or_reusing_an_id_never_reuses_confirmation():
    drafts = store()
    complete(drafts)
    old = drafts.review("one")
    with pytest.raises(DraftError, match="draft_id_unavailable"):
        complete(drafts)
    drafts.clear()
    with pytest.raises(DraftError, match="draft_unavailable"):
        drafts.inspect("one")
    complete(drafts)
    new = drafts.review("one")
    assert new.revision != old.revision
    with pytest.raises(DraftError, match="review_required"):
        drafts.confirm("one", old.revision)
    drafts.confirm("one", new.revision)
    assert DraftStore().expire() == ()


def test_incomplete_conversation_cancel_replay_emits_no_intent():
    drafts = store()
    drafts.start("one", metadata(), DraftPatch(tracker_id="headache"))
    drafts.update("one", DraftPatch(subject_id="anna", values={"pain": True}))
    drafts.cancel("one")
    with pytest.raises(DraftError, match="draft_unavailable"):
        drafts.review("one")
