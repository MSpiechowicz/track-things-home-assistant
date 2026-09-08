"""Synthetic account/config-flow fixture replays."""

from .api_fixtures import SESSION, USER, WORKSPACE

ENTRY_DATA = {
    "backend_url": "https://backend.example.test",
    "allow_local_http": False,
    "user_id": USER["id"],
    "workspace_id": WORKSPACE["id"],
    **SESSION,
}
LOGIN = {
    "backend_url": "https://backend.example.test/",
    "identifier": "synthetic@example.test",
    "password": "sentinel-password",
}


def login_responses(http, *, user=None, workspaces=None, credentials=None):
    http.respond(SESSION if credentials is None else credentials)
    http.respond(USER if user is None else user)
    http.respond(USER if user is None else user)
    http.respond({"items": [WORKSPACE] if workspaces is None else workspaces, "nextCursor": None})


def setup_responses(http):
    http.respond(USER)
    http.respond(WORKSPACE)
    http.respond({"items": [], "nextCursor": None})
    http.respond({"items": [], "nextCursor": None})
