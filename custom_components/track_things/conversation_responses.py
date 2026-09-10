"""Local recovery messages and deterministic review speech."""

from .conversation_language import WORDS
from .dialogue_rules import tracker_schema

MESSAGES = {
    "en": {
        "start": "Say log and a tracker name to start a new entry.",
        "recovery": "I could not use that answer. Try a listed choice or repeat the question.",
        "unavailable": "Track Things is unavailable. Try again after restoring the connection.",
        "saving": "Saving is not available yet. No entry was saved.",
        "calendar": "Calendar questions are not available in this agent yet.",
        "cancel": "Cancelled. No entry was saved.",
        "review": "Review this entry",
        "confirm": "Say confirm to confirm, or change a detail. Nothing has been saved.",
        "text": "For a control command in this text field, use /review, /cancel or /skip.",
    },
    "pl": {
        "start": "Powiedz zapisz i nazwę trackera, aby rozpocząć nowy wpis.",
        "recovery": "Nie mogę użyć tej odpowiedzi. Wybierz podaną opcję lub powtórz pytanie.",
        "unavailable": "Track Things jest niedostępny. Spróbuj po przywróceniu połączenia.",
        "saving": "Zapisywanie nie jest jeszcze dostępne. Nie zapisano wpisu.",
        "calendar": "Pytania o kalendarz nie są jeszcze dostępne w tym agencie.",
        "cancel": "Anulowano. Nie zapisano wpisu.",
        "review": "Sprawdź wpis",
        "confirm": "Powiedz potwierdź lub zmień szczegół. Nic nie zostało zapisane.",
        "text": "W polu tekstowym użyj /sprawdź, /anuluj lub /pomiń jako polecenia.",
    },
    "de": {
        "start": "Sage erfasse und einen Trackernamen, um einen Eintrag zu beginnen.",
        "recovery": "Ungültige Antwort. Wähle eine genannte Option oder wiederhole die Frage.",
        "unavailable": "Track Things ist nicht verfügbar. Stelle die Verbindung wieder her.",
        "saving": "Speichern ist noch nicht verfügbar. Kein Eintrag wurde gespeichert.",
        "calendar": "Kalenderfragen sind in diesem Agenten noch nicht verfügbar.",
        "cancel": "Abgebrochen. Kein Eintrag wurde gespeichert.",
        "review": "Eintrag prüfen",
        "confirm": "Sage bestätigen oder ändere ein Detail. Es wurde noch nichts gespeichert.",
        "text": "Nutze im Textfeld /Zusammenfassung, /abbrechen oder /überspringen als Befehl.",
    },
    "fr": {
        "start": "Dis note et le nom du tracker pour commencer une entrée.",
        "recovery": "Réponse invalide. Choisis une option proposée ou répète la question.",
        "unavailable": "Track Things est indisponible. Réessaie après avoir rétabli la connexion.",
        "saving": "La sauvegarde est indisponible. Aucune entrée enregistrée.",
        "calendar": "Les questions de calendrier ne sont pas encore disponibles dans cet agent.",
        "cancel": "Annulé. Aucune entrée enregistrée.",
        "review": "Vérifie cette entrée",
        "confirm": "Dis confirmer ou change un détail. Rien n'a été enregistré.",
        "text": "Dans un champ texte, utilise /résumé, /annuler ou /passer comme commande.",
    },
}


def review_speech(result, metadata, language, time_zone=None):
    """Read validated IDs as labels; labels are data and never instructions."""
    payload = result.payload
    tracker = metadata.trackers[payload["trackerId"]]
    subject = metadata.subjects[payload["subjectId"]]
    details = []
    for definition in tracker_schema(metadata, payload["trackerId"])["fields"]:
        key = definition["key"]
        if key not in payload["values"]:
            continue
        value = payload["values"][key]
        if definition["type"] == "boolean":
            value = next(
                word for word, item in WORDS[language]["booleans"].items() if item == value
            )
        elif definition["type"] in ("select", "multiselect"):
            labels = {item["id"]: item["label"] for item in definition["options"]}
            value = (
                ", ".join(labels[item] for item in value)
                if isinstance(value, list)
                else labels[value]
            )
        details.append(f"{definition['label']}: {value}")
    occurrence = payload.get("periodStart", payload["occurredAt"])
    if time_zone and language == "en":
        from datetime import date, datetime
        from zoneinfo import ZoneInfo

        if "periodStart" in payload:
            occurrence = date.fromisoformat(occurrence[:10]).strftime("%B %d, %Y")
        else:
            occurrence = (
                datetime.fromisoformat(occurrence)
                .astimezone(ZoneInfo(time_zone))
                .strftime("%B %d, %Y at %H:%M")
            )
    return (
        f"{MESSAGES[language]['review']}: {tracker.get('name', tracker['id'])}; "
        f"{subject.get('name', subject['id'])}; {occurrence}; "
        + "; ".join(details)
        + ". "
        + MESSAGES[language]["confirm"]
    )
