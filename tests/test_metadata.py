"""Offline metadata refresh, historical resolution, and schema cache contracts."""

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.track_things.api_errors import NotFoundError, ServerError
from custom_components.track_things.metadata import MetadataStore

from .api_fixtures import SCHEMA, SUBJECT, TRACKER


def metadata_api(trackers=None, subjects=None):
    api = MagicMock()

    async def iter_trackers(_):
        for item in trackers if trackers is not None else [TRACKER]:
            yield deepcopy(item)

    async def iter_subjects(_):
        for item in subjects if subjects is not None else [SUBJECT]:
            yield deepcopy(item)

    api.iter_trackers = iter_trackers
    api.iter_subjects = iter_subjects
    api.get_schema_version = AsyncMock(return_value=deepcopy(SCHEMA))
    api.get_subject = AsyncMock(return_value={**SUBJECT, "id": "subject-2", "archivedAt": "past"})
    api.get_tracker = AsyncMock(return_value={**TRACKER, "id": "old", "archivedAt": "past"})
    return api


async def test_refresh_assignments_renames_and_schema_cache():
    trackers = [deepcopy(TRACKER)]
    subjects = [deepcopy(SUBJECT)]
    api = metadata_api(trackers, subjects)
    store = MetadataStore(api, "workspace-1")
    first = await store.async_refresh()
    assert set(first.subjects) == {"subject-1", "subject-2"}
    assert first.subjects["subject-2"]["archivedAt"] == "past"
    trackers[0].update(name="Renamed", archivedAt="past")
    subjects[0]["name"] = "New name"
    trackers.append({**TRACKER, "id": "new", "currentSchemaVersionId": None})
    second = await store.async_refresh()
    assert second.trackers["tracker-1"]["name"] == "Renamed"
    assert second.trackers["tracker-1"]["archivedAt"] == "past"
    assert second.subjects["subject-1"]["name"] == "New name"
    assert "new" in second.trackers
    assert first.trackers["tracker-1"]["name"] == "Headache"
    api.get_schema_version.assert_awaited_once()


async def test_missing_schema_is_retried_and_transient_failure_is_atomic():
    api = metadata_api()
    store = MetadataStore(api, "workspace-1")
    api.get_schema_version.side_effect = NotFoundError()
    first = await store.async_refresh()
    assert first.missing_schema_ids == {"schema-1"}
    api.get_schema_version.side_effect = ServerError()
    with pytest.raises(ServerError):
        await store.async_refresh()
    assert store.snapshot is first
    api.get_schema_version.side_effect = None
    assert not (await store.async_refresh()).missing_schema_ids


async def test_historical_lookup_and_concurrent_immutable_versions():
    api = metadata_api([], [])
    store = MetadataStore(api, "workspace-1")
    assert (await store.async_tracker("old"))["archivedAt"] == "past"
    assert (await store.async_subject("subject-2"))["archivedAt"] == "past"
    await store.async_tracker("old")
    await store.async_subject("subject-2")
    api.get_tracker.assert_awaited_once()
    api.get_subject.assert_awaited_once()
    versions = await asyncio.gather(
        *(store.async_schema("tracker-1", "schema-1") for _ in range(3))
    )
    versions[0]["schema"]["fields"].clear()
    assert (await store.async_schema("tracker-1", "schema-1"))["schema"]["fields"]
    api.get_schema_version.assert_awaited_once()


async def test_schema_identity_cannot_cross_trackers():
    from custom_components.track_things.api_errors import InvalidResponseError

    store = MetadataStore(metadata_api(), "workspace-1")
    await store.async_schema("tracker-1", "schema-1")
    with pytest.raises(InvalidResponseError):
        await store.async_schema("another-tracker", "schema-1")


async def test_missing_subject_does_not_invent_metadata():
    api = metadata_api()
    api.get_subject.side_effect = NotFoundError()
    snapshot = await MetadataStore(api, "workspace-1").async_refresh()
    assert snapshot.trackers["tracker-1"]["subjectIds"] == ["subject-1", "subject-2"]
    assert set(snapshot.subjects) == {"subject-1"}
