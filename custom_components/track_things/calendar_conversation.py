"""Isolated, expiring daily-query snapshots and deterministic spoken pages."""

from dataclasses import dataclass, field
from time import monotonic

from homeassistant.exceptions import HomeAssistantError

from .conversation_contract import Clarification, Proposal
from .conversation_language import SENTENCES
from .conversation_values import resolve
from .daily_calendar import async_daily_records

MESSAGES = {
    "en": {
        "heading": "{day}: {total} {noun}.",
        "empty": "No entries for {day}.",
        "more": "Say more for the next entries.",
        "end": "No more entries.",
        "missing": "Ask for a calendar day first.",
        "unavailable": "The calendar is unavailable. Restore access and ask again.",
        "choose": "Which {kind}? Reply with a name or ID: {names}.",
        "tracker": "tracker",
        "subject": "subject",
    },
    "pl": {
        "heading": "{day}: liczba wpisów: {total}.",
        "empty": "Brak wpisów na {day}.",
        "more": "Powiedz więcej, aby usłyszeć kolejne wpisy.",
        "end": "Nie ma więcej wpisów.",
        "missing": "Najpierw zapytaj o dzień w kalendarzu.",
        "unavailable": "Kalendarz jest niedostępny. Przywróć dostęp i zapytaj ponownie.",
        "choose": "Wybierz ({kind}). Podaj nazwę lub ID: {names}.",
        "tracker": "tracker",
        "subject": "osoba",
    },
    "de": {
        "heading": "{day}: {total} {noun}.",
        "empty": "Keine Einträge für {day}.",
        "more": "Sage mehr für die nächsten Einträge.",
        "end": "Keine weiteren Einträge.",
        "missing": "Frage zuerst nach einem Kalendertag.",
        "unavailable": "Der Kalender ist nicht verfügbar. Stelle den Zugriff wieder her.",
        "choose": "Welche Auswahl ({kind})? Antworte mit Name oder ID: {names}.",
        "tracker": "Tracker",
        "subject": "Person",
    },
    "fr": {
        "heading": "{day} : {total} {noun}.",
        "empty": "Aucune entrée pour {day}.",
        "more": "Dis plus pour les entrées suivantes.",
        "end": "Aucune autre entrée.",
        "missing": "Demande d’abord un jour du calendrier.",
        "unavailable": "Le calendrier est indisponible. Rétablis l’accès et réessaie.",
        "choose": "Quel choix ({kind}) ? Réponds avec un nom ou ID : {names}.",
        "tracker": "tracker",
        "subject": "personne",
    },
}


@dataclass(repr=False)
class CalendarSession:
    proposal: Proposal
    expires: float
    filters: dict = field(default_factory=dict)
    pending: str | None = None
    candidates: tuple[str, ...] = ()
    records: tuple = ()
    position: int = 0
    last_speech: str = ""
    selection: tuple | None = None


class CalendarConversation:
    def __init__(self, agent, *, clock=None):
        self.agent = agent
        self.clock = clock or (lambda: monotonic())
        self.sessions = {}

    def expire(self):
        for key, session in tuple(self.sessions.items()):
            if self.clock() >= session.expires:
                del self.sessions[key]

    def _selection(self):
        ids = self.agent.entry.options.get("tracker_ids")
        return None if ids is None else tuple(sorted(ids))

    def _resources(self, kind):
        coordinator = self.agent.entry.runtime_data.coordinator
        resources = (
            coordinator.calendar_trackers
            if kind == "tracker"
            else coordinator.store.snapshot.subjects
        )
        return {
            key: item.get("name", key)
            for key, item in resources.items()
            if item["workspaceId"] == self.agent.entry.data["workspace_id"]
        }

    async def start(self, key, proposal, language):
        self.sessions[key] = CalendarSession(
            proposal, self.clock() + 300, selection=self._selection()
        )
        return await self._query(key, language)

    async def follow_up(self, key, text, language):
        session = self.sessions.get(key)
        if session is None:
            return None
        words = MESSAGES[language]
        if (
            not self.agent.entry.runtime_data.coordinator.last_update_success
            or session.selection != self._selection()
        ):
            self.sessions.pop(key, None)
            return words["unavailable"], False
        command = text.strip().casefold().removeprefix("/")
        if command in SENTENCES[language]["cancel"]:
            self.sessions.pop(key, None)
            from .conversation_responses import MESSAGES as RESPONSES

            return RESPONSES[language]["cancel"], False
        if command in SENTENCES[language]["repeat"]:
            return session.last_speech, bool(
                session.pending or session.position < len(session.records)
            )
        if command in SENTENCES[language]["more"]:
            if session.pending:
                return session.last_speech, True
            return self._page(session, language)
        if session.pending:
            resources = self._resources(session.pending)
            resources = {key: resources[key] for key in session.candidates if key in resources}
            try:
                chosen = resolve(text, resources)
            except Clarification:
                return session.last_speech, True
            session.filters[session.pending] = chosen
            session.pending = None
            return await self._query(key, language)
        return None

    async def _query(self, key, language):
        session = self.sessions[key]
        words = MESSAGES[language]
        for kind in ("tracker", "subject"):
            name = getattr(session.proposal, f"{kind}_name")
            if name is None or kind in session.filters:
                continue
            resources = self._resources(kind)
            try:
                session.filters[kind] = resolve(name, resources)
            except Clarification as error:
                session.pending = kind
                session.candidates = error.candidates or tuple(resources)
                names = ", ".join(f"{resources[key]} ({key})" for key in session.candidates)
                if not names:
                    self.sessions.pop(key, None)
                    return words["unavailable"], False
                session.last_speech = words["choose"].format(kind=words[kind], names=names)
                return session.last_speech, True
        try:
            records = await async_daily_records(
                self.agent.hass,
                self.agent.entry,
                session.proposal.day,
                session.filters.get("tracker"),
                session.filters.get("subject"),
            )
        except HomeAssistantError, ValueError, TypeError, OverflowError:
            self.sessions.pop(key, None)
            return words["unavailable"], False
        # Copy only immutable display strings/IDs; never retain entry values or notes.
        session.records = tuple((item["id"], str(event.summary)) for item, event in records)
        return self._page(session, language)

    def _page(self, session, language):
        words = MESSAGES[language]
        total = len(session.records)
        if not total:
            speech = words["empty"].format(day=session.proposal.day)
        elif session.position >= total:
            speech = words["end"]
        else:
            page = session.records[session.position : session.position + 5]
            session.position += len(page)
            nouns = {
                "en": ("entry", "entries"),
                "de": ("Eintrag", "Einträge"),
                "fr": ("entrée", "entrées"),
                "pl": ("", ""),
            }
            heading = words["heading"].format(
                day=session.proposal.day, total=total, noun=nouns[language][total != 1]
            )
            speech = " ".join([heading, *(summary for _, summary in page)])
            if session.position < total:
                speech += " " + words["more"]
        session.last_speech = speech
        return speech, session.position < total
