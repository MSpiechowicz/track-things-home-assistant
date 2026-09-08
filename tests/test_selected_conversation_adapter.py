"""Offline four-language transcripts; proposals feed the real shared draft store."""

from dataclasses import replace

import pytest

from custom_components.track_things.conversation_adapter import AdapterContext, QuestionAdapter
from custom_components.track_things.conversation_questions import questions
from custom_components.track_things.dialogue import DraftPatch

from .dialogue_fixtures import NOW, metadata, store

TRANSCRIPTS = [
    ("en", "log headache", "yes", "seven", "change Severity to six", "review", "confirm"),
    ("pl", "zapisz headache", "tak", "siedem", "zmień Severity na sześć", "sprawdź", "potwierdź"),
    (
        "de",
        "erfasse headache",
        "ja",
        "sieben",
        "ändere Severity auf sechs",
        "Zusammenfassung",
        "bestätigen",
    ),
    ("fr", "note headache", "oui", "sept", "change Severity en six", "résumé", "confirmer"),
]


@pytest.mark.parametrize("language,start,yes,seven,correction,review,confirm", TRANSCRIPTS)
def test_transcript(language, start, yes, seven, correction, review, confirm):
    drafts = store()
    meta = metadata()
    context = AdapterContext(meta, language, NOW, "Europe/Berlin")
    adapter = QuestionAdapter(language)
    result = drafts.start("session", meta, adapter.parse(start, context).patch)
    context = replace(context, tracker_id="headache")
    for answer in ("anna", yes, seven):
        descriptor = result.descriptors[0]
        prompt = questions(result, meta, language)[0]
        assert prompt.text
        patch = adapter.parse(answer, replace(context, descriptor=descriptor)).patch
        context = replace(context, values={**context.values, **patch.values})
        result = drafts.update("session", patch)
    patch = adapter.parse(correction, context).patch
    drafts.update("session", patch)
    assert adapter.parse(review, context).action == "review"
    result = drafts.review("session")
    assert result.payload["values"] == {"pain": True, "severity": 6}
    assert adapter.parse(confirm, context).action == "confirm"
    intent = drafts.confirm("session", result.revision)
    assert intent.payload["subjectId"] == "anna"


@pytest.mark.parametrize(
    "language,command",
    [
        ("en", "calendar for yesterday"),
        ("pl", "kalendarz na wczoraj"),
        ("de", "Kalender für gestern"),
        ("fr", "calendrier pour hier"),
    ],
)
def test_calendar(language, command):
    context = AdapterContext(metadata(), language, NOW, "Europe/Berlin")
    result = QuestionAdapter(language).parse(command, context)
    assert result.day.isoformat() == "2026-09-07"
    assert result.action == "calendar"


@pytest.mark.parametrize(
    "language,commands",
    [
        ("en", ("cancel", "repeat", "more", "skip", "use defaults")),
        ("pl", ("anuluj", "powtórz", "więcej", "pomiń", "użyj domyślnych")),
        ("de", ("abbrechen", "wiederholen", "mehr", "überspringen", "Standardwerte verwenden")),
        ("fr", ("annuler", "répéter", "plus", "passer", "utiliser les valeurs par défaut")),
    ],
)
def test_controls(language, commands):
    drafts = store()
    result = drafts.start("s", metadata(), DraftPatch(tracker_id="headache", subject_id="anna"))
    context = AdapterContext(metadata(), language, NOW, "UTC", tracker_id="headache")
    adapter = QuestionAdapter(language)
    for command, expected in zip(commands[:3], ("cancel", "repeat", "more"), strict=True):
        assert adapter.parse(command, context).action == expected
    optional = result.descriptors[-1]
    parsed = adapter.parse("/" + commands[3], replace(context, descriptor=optional))
    assert parsed.patch.skip_optional == {"note"}
    assert adapter.parse(commands[4], context).patch.accept_defaults == {"pain"}


@pytest.mark.parametrize(
    "language,yes,no",
    [("en", "yes", "no"), ("pl", "tak", "nie"), ("de", "ja", "nein"), ("fr", "oui", "non")],
)
def test_defaults_answer_is_not_save_confirmation(language, yes, no):
    context = AdapterContext(
        metadata(), language, NOW, "UTC", tracker_id="headache", offering_defaults=True
    )
    adapter = QuestionAdapter(language)
    assert adapter.parse(yes, context).patch.accept_defaults == {"pain"}
    assert adapter.parse(no, context).action == "more"
