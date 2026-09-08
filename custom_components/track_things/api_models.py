"""Wire models matching the backend's public serializers; dates remain lossless strings."""

from dataclasses import dataclass, field
from typing import Any, Literal, NotRequired, TypedDict


class User(TypedDict):
    id: str
    email: str
    createdAt: str
    updatedAt: str
    username: NotRequired[str | None]
    displayName: NotRequired[str | None]
    avatarUrl: NotRequired[str | None]


class Workspace(TypedDict):
    id: str
    ownerUserId: str
    name: str
    type: Literal["personal", "family", "team"]
    isDefault: bool
    createdAt: str
    updatedAt: str


class Subject(TypedDict):
    id: str
    workspaceId: str
    name: str
    type: Literal["person", "pet", "object", "other"]
    relationship: str | None
    avatarUrl: str | None
    metadata: dict[str, Any]
    createdAt: str
    updatedAt: str
    archivedAt: str | None


class Tracker(TypedDict):
    id: str
    workspaceId: str
    subjectIds: list[str]
    subjectId: str
    name: str
    kind: Literal["manual", "integration", "computed"]
    currentSchemaVersionId: str | None
    createdByUserId: str | None
    createdAt: str
    updatedAt: str
    archivedAt: str | None
    description: NotRequired[str | None]
    icon: NotRequired[str | None]
    color: NotRequired[str | None]


class SchemaField(TypedDict):
    id: str
    key: str
    label: str
    type: Literal[
        "text", "textarea", "number", "slider", "boolean", "date", "select", "multiselect"
    ]
    required: NotRequired[bool]
    description: NotRequired[str]
    placeholder: NotRequired[str]
    order: NotRequired[int]
    defaultValue: NotRequired[Any]
    validation: NotRequired[dict[str, Any]]
    options: NotRequired[list[dict[str, Any]]]
    visibleWhen: NotRequired[dict[str, Any]]
    ui: NotRequired[dict[str, Any]]
    legacy: NotRequired[dict[str, Any]]


class TrackerSchema(TypedDict):
    version: int
    fields: list[SchemaField]


class SchemaVersion(TypedDict):
    id: str
    trackerId: str
    version: int
    schema: TrackerSchema
    createdByUserId: str | None
    createdAt: str


class EntryCreate(TypedDict):
    trackerId: str
    subjectId: str
    occurredAt: str
    values: dict[str, Any]
    expectedSchemaVersionId: NotRequired[str]
    periodStart: NotRequired[str | None]
    periodEnd: NotRequired[str | None]
    title: NotRequired[str | None]
    note: NotRequired[str | None]
    tagIds: NotRequired[list[str]]
    source: NotRequired[Literal["manual", "integration", "import", "migration"]]
    clientMutationId: NotRequired[str | None]


class Entry(TypedDict):
    id: str
    workspaceId: str
    trackerId: str
    subjectId: str
    schemaVersionId: str
    occurredAt: str
    values: dict[str, Any]
    tagIds: list[str]
    source: Literal["manual", "integration", "import", "migration"]
    alertSeverity: Literal["info", "warning", "critical"] | None
    version: int
    createdByUserId: str | None
    updatedByUserId: str | None
    createdAt: str
    updatedAt: str
    periodStart: NotRequired[str | None]
    periodEnd: NotRequired[str | None]
    title: NotRequired[str | None]
    note: NotRequired[str | None]
    clientMutationId: NotRequired[str | None]


class EntryFilters(TypedDict, total=False):
    startDate: str
    endDateExclusive: str
    timeZone: str
    trackerId: str
    subjectId: str


@dataclass(frozen=True)
class Session:
    """Rotated credentials are returned together and excluded from repr."""

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_at: int


@dataclass(frozen=True, repr=False)
class CursorPage[T]:
    """One bounded page; its cursor is opaque and scoped to the request filters."""

    items: list[T]
    next_cursor: str | None
