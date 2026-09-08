"""Literal name, typed value and timezone-aware date parsing; no fuzzy guesses."""

import math
import re
import unicodedata
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from .conversation_contract import Clarification
from .conversation_language import WORDS


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def resolve(text, resources, aliases=None):
    """Aliases map resource IDs to literal spellings, scoped by the caller."""
    aliases = aliases or {}
    found = tuple(
        key
        for key, label in resources.items()
        if normalized(text) in {normalized(v) for v in (key, label, *aliases.get(key, ()))}
    )
    if len(found) != 1:
        raise Clarification("ambiguous_name" if found else "unknown_name", found)
    return found[0]


def occurrence(text, language, now, zone):
    if now.utcoffset() is None:
        raise Clarification("timezone_required")
    local = now.astimezone(ZoneInfo(zone))
    offsets = WORDS[language]["days"]
    raw = normalized(text)
    if raw in offsets:
        return local.date() + timedelta(days=offsets[raw])
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return date.fromisoformat(raw)
        stamp = datetime.fromisoformat(raw)
        if stamp.utcoffset() is not None:
            return stamp
        candidates = {
            candidate.astimezone(UTC)
            for fold in (0, 1)
            if (candidate := stamp.replace(tzinfo=local.tzinfo, fold=fold))
            .astimezone(UTC)
            .astimezone(local.tzinfo)
            .replace(tzinfo=None)
            == stamp
        }
        if len(candidates) != 1:
            raise Clarification("ambiguous_time" if candidates else "nonexistent_time")
        return candidates.pop().astimezone(local.tzinfo)
    except ValueError as error:
        if isinstance(error, Clarification):
            raise
        raise Clarification("invalid_date") from None


def value(text, definition, language, now, zone, aliases=None):
    kind = definition["type"]
    raw = normalized(text)
    if kind in ("text", "textarea"):
        return text
    if kind == "boolean":
        options = WORDS[language]["booleans"]
        if raw not in options:
            raise Clarification("invalid_boolean")
        return options[raw]
    if kind in ("number", "slider"):
        words = WORDS[language]["numbers"].split()
        if raw in words:
            return words.index(raw)
        try:
            number = float(raw.replace(",", "."))
            if not math.isfinite(number):
                raise ValueError
            return number
        except ValueError:
            raise Clarification("invalid_number") from None
    if kind == "date":
        parsed = occurrence(text, language, now, zone)
        if isinstance(parsed, datetime):
            raise Clarification("date_required")
        return parsed.isoformat()
    options = {item["id"]: item["label"] for item in definition["options"]}
    if kind == "select":
        return resolve(text, options, aliases)
    # Semicolons are an explicit separator; labels containing commas remain intact.
    values = [resolve(part.strip(), options, aliases) for part in text.split(";")]
    if len(set(values)) != len(values):
        raise Clarification("duplicate_choice")
    return values
