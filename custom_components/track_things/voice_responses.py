"""Localized write outcomes; never expose backend errors or payloads."""

VOICE_MESSAGES = {
    "en": {
        "saved": "Entry saved.",
        "changed": "Tracker or subject details changed. Review and confirm again.",
        "uncertain": "Saving could not be confirmed. Say confirm to retry the same entry. "
        "Do not start another copy; check the calendar if you stop here.",
        "abandoned": "Stopped retrying. The entry may already be saved; check the calendar.",
        "denied": "This account is not allowed to save this entry. Restore access before retrying.",
        "auth": "Sign in to Track Things again before retrying.",
        "unavailable": "Track Things is unavailable. No write was attempted. Try confirming again.",
        "rejected": "The entry was rejected. Review and confirm again.",
    },
    "pl": {
        "saved": "Wpis zapisany.",
        "changed": "Szczegóły trackera lub osoby zmieniły się. Sprawdź i potwierdź ponownie.",
        "uncertain": "Nie można potwierdzić zapisu. Powiedz potwierdź, aby ponowić ten sam wpis. "
        "Nie twórz kopii; sprawdź kalendarz, jeśli zakończysz rozmowę.",
        "abandoned": "Przerwano ponawianie. Wpis może być już zapisany; sprawdź kalendarz.",
        "denied": "To konto nie może zapisać wpisu. Przywróć uprawnienia przed ponowieniem.",
        "auth": "Zaloguj się ponownie do Track Things przed ponowieniem.",
        "unavailable": "Track Things jest niedostępny. Nie próbowano zapisu. Potwierdź ponownie.",
        "rejected": "Wpis został odrzucony. Sprawdź i potwierdź ponownie.",
    },
    "de": {
        "saved": "Eintrag gespeichert.",
        "changed": "Tracker- oder Personendetails haben sich geändert. Prüfe und bestätige erneut.",
        "uncertain": "Speichern nicht bestätigt. Sage bestätigen, um denselben Eintrag erneut "
        "zu senden. Erstelle keine Kopie; prüfe beim Beenden den Kalender.",
        "abandoned": "Gestoppt. Der Eintrag kann gespeichert sein; prüfe den Kalender.",
        "denied": "Keine Schreibberechtigung. Stelle die Berechtigung wieder her.",
        "auth": "Melde dich vor dem erneuten Versuch bei Track Things an.",
        "unavailable": "Track Things ist nicht verfügbar. Kein Schreibversuch. Bestätige erneut.",
        "rejected": "Eintrag abgelehnt. Prüfe und bestätige erneut.",
    },
    "fr": {
        "saved": "Entrée enregistrée.",
        "changed": "Tracker ou personne modifiés. Vérifie et confirme encore.",
        "uncertain": "Enregistrement non confirmé. Dis confirmer pour renvoyer la même entrée. "
        "Ne crée pas de copie ; consulte le calendrier si tu arrêtes ici.",
        "abandoned": "Arrêté. L’entrée peut être enregistrée ; consulte le calendrier.",
        "denied": "Ce compte ne peut pas enregistrer cette entrée. Rétablis les autorisations.",
        "auth": "Reconnecte-toi à Track Things avant de réessayer.",
        "unavailable": "Track Things est indisponible. Aucune écriture tentée. Confirme à nouveau.",
        "rejected": "Entrée refusée. Vérifie et confirme encore.",
    },
}
