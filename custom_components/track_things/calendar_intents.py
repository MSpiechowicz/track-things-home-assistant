"""Explicit date/filter calendar grammar; labels remain literal untrusted data."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .conversation_contract import Clarification, Proposal
from .conversation_language import WORDS
from .conversation_values import occurrence

GRAMMAR = {
    "en": (r"(?:show )?(?:my )?calendar(?: for (.+))?", "tracker", "subject"),
    "pl": (r"(?:pokaż )?kalendarz(?: na (.+))?", "tracker", "osoba"),
    "de": (r"(?:zeige )?(?:meinen )?Kalender(?: für (.+))?", "Tracker", "Person"),
    "fr": (r"(?:affiche )?(?:mon )?calendrier(?: pour (.+))?", "tracker", "personne"),
}


SPOKEN_FILTERS = {
    "en": ("for tracker", "for subject"),
    "pl": ("dla trackera", "dla osoby"),
    "de": ("für Tracker", "für Person"),
    "fr": ("du tracker", "de la personne"),
}


def calendar_proposal(text, context):
    """Semicolons delimit optional filters so labels cannot be mistaken for dates."""
    grammar, tracker_word, subject_word = GRAMMAR[context.language]
    # Spoken delimiters require no punctuation from STT. Explicit semicolon
    # syntax remains available for text input with labels containing delimiters.
    if ";" not in text:
        tracker_phrase, subject_phrase = SPOKEN_FILTERS[context.language]
        for phrase, key in ((tracker_phrase, tracker_word), (subject_phrase, subject_word)):
            text = re.sub(
                r"\s+" + re.escape(phrase) + r"\s+", f"; {key}:", text, flags=re.IGNORECASE
            )
    parts = text.strip().split(";")
    match = re.fullmatch(grammar, parts[0].strip(), re.IGNORECASE)
    if match is None:
        return None
    names = {}
    for part in parts[1:]:
        key, separator, name = part.strip().partition(":")
        key = key.casefold()
        if (
            not separator
            or key not in (tracker_word.casefold(), subject_word.casefold())
            or not name.strip()
            or key in names
        ):
            raise Clarification("invalid_calendar_filter")
        names[key] = name.strip()
    parsed = occurrence(
        match[1] or WORDS[context.language]["today"],
        context.language,
        context.now,
        context.time_zone,
    )
    day = (
        parsed.astimezone(ZoneInfo(context.time_zone)).date()
        if isinstance(parsed, datetime)
        else parsed
    )
    return Proposal(
        "calendar",
        day=day,
        tracker_name=names.get(tracker_word.casefold()),
        subject_name=names.get(subject_word.casefold()),
    )
