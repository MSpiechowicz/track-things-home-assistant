"""Synthetic backend serializer fixtures and an offline HTTP boundary."""

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import aiohttp

NOW = "2026-09-08T10:00:00.000Z"
USER = {"id": "user-1", "email": "synthetic@example.test", "createdAt": NOW, "updatedAt": NOW}
WORKSPACE = {
    "id": "workspace-1",
    "ownerUserId": "user-1",
    "name": "Synthetic",
    "type": "family",
    "isDefault": True,
    "createdAt": NOW,
    "updatedAt": NOW,
}
SUBJECT = {
    "id": "subject-1",
    "workspaceId": "workspace-1",
    "name": "Anna",
    "type": "person",
    "relationship": None,
    "avatarUrl": None,
    "metadata": {},
    "createdAt": NOW,
    "updatedAt": NOW,
    "archivedAt": None,
}
TRACKER = {
    "id": "tracker-1",
    "workspaceId": "workspace-1",
    "subjectIds": ["subject-1", "subject-2"],
    "subjectId": "subject-1",
    "name": "Headache",
    "kind": "manual",
    "currentSchemaVersionId": "schema-1",
    "createdByUserId": "user-1",
    "createdAt": NOW,
    "updatedAt": NOW,
    "archivedAt": None,
}
SCHEMA = {
    "id": "schema-1",
    "trackerId": "tracker-1",
    "version": 1,
    "schema": {
        "version": 1,
        "fields": [
            {
                "id": "field-1",
                "key": "severity",
                "label": "Severity",
                "type": "slider",
                "required": True,
                "validation": {"min": 1, "max": 10, "step": 1},
            },
        ],
    },
    "createdByUserId": "user-1",
    "createdAt": NOW,
}
ENTRY = {
    "id": "entry-1",
    "workspaceId": "workspace-1",
    "trackerId": "tracker-1",
    "subjectId": "subject-1",
    "schemaVersionId": "schema-1",
    "occurredAt": NOW,
    "values": {"severity": 6, "boolean": False, "zero": 0, "date": "2026-09-08"},
    "tagIds": [],
    "source": "manual",
    "alertSeverity": None,
    "version": 1,
    "createdByUserId": "user-1",
    "updatedByUserId": "user-1",
    "createdAt": NOW,
    "updatedAt": NOW,
    "periodStart": None,
    "periodEnd": None,
    "note": "sentinel-note",
}
SESSION = {
    "access_token": "sentinel-access",
    "refresh_token": "sentinel-refresh",
    "expires_at": 2000000000,
}
CREATE = {
    "trackerId": "tracker-1",
    "subjectId": "subject-1",
    "occurredAt": NOW,
    "values": deepcopy(ENTRY["values"]),
    "source": "manual",
    "expectedSchemaVersionId": "schema-1",
    "clientMutationId": "mutation-1",
    "title": "Ból głowy",
    "note": "sentinel-note",
}


class MockHttp:
    """Replace aiohttp's network boundary while keeping its request context manager."""

    def __init__(self, monkeypatch):
        self.request = AsyncMock()
        monkeypatch.setattr(aiohttp.ClientSession, "_request", self.request)
        self.results = []
        self.request.side_effect = self.results

    def respond(self, payload=None, *, status=200, headers=None, error=None):
        response = MagicMock(spec=aiohttp.ClientResponse)
        response.status = status
        response.headers = headers or {}
        response.json = AsyncMock(return_value=deepcopy(payload), side_effect=error)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        self.results.append(response)
        return response

    def fail(self, error):
        self.results.append(error)
