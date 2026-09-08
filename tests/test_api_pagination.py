"""Cursor traversal keeps filters stable and terminates on broken server cursors."""

import pytest

from custom_components.track_things.api_errors import InvalidResponseError

from .api_fixtures import ENTRY, SCHEMA, SUBJECT, TRACKER, WORKSPACE


@pytest.mark.parametrize(
    ("resource", "args", "path", "item"),
    [
        ("workspaces", (), "/api/workspaces", WORKSPACE),
        ("trackers", ("w",), "/api/workspaces/w/trackers", TRACKER),
        ("subjects", ("w",), "/api/workspaces/w/subjects", SUBJECT),
        ("schema_versions", ("w", "t"), "/api/workspaces/w/trackers/t/schema-versions", SCHEMA),
        ("entries", ("w",), "/api/workspaces/w/entries", ENTRY),
    ],
)
async def test_resource_pages_and_traversal(api_http, resource, args, path, item):
    client, http, _, _ = api_http
    http.respond({"items": [item], "nextCursor": "opaque+/="})
    page = await getattr(client, "list_" + resource)(*args, limit=1)
    assert page.items == [item]
    assert page.next_cursor == "opaque+/="
    assert http.request.call_args.args[1] == "https://backend.example.test" + path
    assert http.request.call_args.kwargs["params"] == {"pagination": "cursor", "limit": 1}
    http.respond({"items": [item], "nextCursor": "opaque+/="})
    http.respond({"items": [{**item, "id": "second"}], "nextCursor": None})
    result = [value async for value in getattr(client, "iter_" + resource)(*args)]
    assert [value["id"] for value in result] == [item["id"], "second"]
    assert http.request.call_args.kwargs["params"]["cursor"] == "opaque+/="


async def test_calendar_filters_survive_all_pages_and_caller_mutation(api_http):
    client, http, _, _ = api_http
    filters = {
        "startDate": "2026-09-08",
        "endDateExclusive": "2026-09-09",
        "timeZone": "Europe/Berlin",
        "subjectId": "subject-1",
        "trackerId": "tracker-1",
    }
    expected = dict(filters)
    http.respond({"items": [ENTRY], "nextCursor": "next"})
    http.respond({"items": [], "nextCursor": None})
    iterator = client.iter_entries("w", filters=filters)
    assert await anext(iterator) == ENTRY
    filters["subjectId"] = "changed"
    assert [item async for item in iterator] == []
    for call in http.request.call_args_list:
        assert expected.items() <= call.kwargs["params"].items()


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"items": [], "nextCursor": 1},
        {"items": [None], "nextCursor": None},
        {"items": [], "nextCursor": ""},
    ],
)
async def test_malformed_pages_fail_explicitly(api_http, payload):
    client, http, _, _ = api_http
    http.respond(payload)
    with pytest.raises(InvalidResponseError):
        await client.list_workspaces()


async def test_cursor_cycle_stops_before_duplicate_items(api_http):
    client, http, _, _ = api_http
    http.respond({"items": [WORKSPACE], "nextCursor": "same"})
    http.respond({"items": [WORKSPACE], "nextCursor": "same"})
    iterator = client.iter_workspaces()
    assert await anext(iterator) == WORKSPACE
    with pytest.raises(InvalidResponseError, match="repeated_cursor"):
        await anext(iterator)
    assert http.request.call_count == 2


async def test_empty_final_page(api_http):
    client, http, _, _ = api_http
    http.respond({"items": [], "nextCursor": None})
    assert [item async for item in client.iter_workspaces()] == []


async def test_invalid_pagination_and_partial_dates_do_not_send(api_http):
    client, http, _, _ = api_http
    for limit in [0, 101, True]:
        with pytest.raises(ValueError):
            await client.list_workspaces(limit=limit)
    with pytest.raises(ValueError):
        await client.list_entries("w", filters={"startDate": "2026-09-08"})
    with pytest.raises(ValueError):
        await client.list_workspaces(cursor="")
    http.request.assert_not_called()
