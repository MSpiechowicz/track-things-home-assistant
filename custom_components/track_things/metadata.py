"""Workspace metadata snapshots and immutable schema caching."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass

from .api import TrackThingsApi
from .api_errors import InvalidResponseError, NotFoundError
from .api_models import SchemaVersion, Subject, Tracker


@dataclass(frozen=True)
class MetadataSnapshot:
    trackers: dict[str, Tracker]
    subjects: dict[str, Subject]
    missing_schema_ids: frozenset[str]


class MetadataStore:
    """Publish complete refreshes; historical reads are explicit async operations."""

    def __init__(self, api: TrackThingsApi, workspace_id: str) -> None:
        self.api = api
        self.workspace_id = workspace_id
        self.snapshot = MetadataSnapshot({}, {}, frozenset())
        self._schemas: dict[str, SchemaVersion] = {}
        self._trackers: dict[str, Tracker] = {}
        self._subjects: dict[str, Subject] = {}
        self._schema_lock = asyncio.Lock()

    async def async_schema(self, tracker_id: str, version_id: str) -> SchemaVersion:
        """Fetch successful versions once, including concurrent historical requests."""
        async with self._schema_lock:
            if version_id not in self._schemas:
                schema = await self.api.get_schema_version(
                    self.workspace_id, tracker_id, version_id
                )
                if schema["id"] != version_id or schema["trackerId"] != tracker_id:
                    raise InvalidResponseError(code="schema_identity_mismatch")
                self._schemas[version_id] = deepcopy(schema)
            schema = self._schemas[version_id]
            if schema["trackerId"] != tracker_id:
                raise InvalidResponseError(code="schema_identity_mismatch")
            return deepcopy(schema)

    async def async_tracker(self, tracker_id: str) -> Tracker:
        """Resolve archived resources omitted from discovery lists by ID."""
        if tracker_id not in self._trackers:
            self._trackers[tracker_id] = await self.api.get_tracker(self.workspace_id, tracker_id)
        return deepcopy(self._trackers[tracker_id])

    async def async_subject(self, subject_id: str) -> Subject:
        if subject_id not in self._subjects:
            self._subjects[subject_id] = await self.api.get_subject(self.workspace_id, subject_id)
        return deepcopy(self._subjects[subject_id])

    async def async_refresh(self) -> MetadataSnapshot:
        trackers = {item["id"]: item async for item in self.api.iter_trackers(self.workspace_id)}
        subjects = {item["id"]: item async for item in self.api.iter_subjects(self.workspace_id)}
        missing = set()
        for tracker in trackers.values():
            # subjectIds is authoritative; the legacy singular field is insufficient.
            for subject_id in tracker["subjectIds"]:
                if subject_id not in subjects:
                    try:
                        subjects[subject_id] = await self.api.get_subject(
                            self.workspace_id, subject_id
                        )
                    except NotFoundError:
                        continue
            if version_id := tracker["currentSchemaVersionId"]:
                try:
                    await self.async_schema(tracker["id"], version_id)
                except NotFoundError:
                    missing.add(version_id)
        snapshot = MetadataSnapshot(trackers, subjects, frozenset(missing))
        self._trackers = deepcopy(trackers)
        self._subjects = deepcopy(subjects)
        self.snapshot = snapshot
        return snapshot
