"""Read-only Asana task contract exercised only with synthetic transports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Final, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from chief_of_staff.connectors.contracts import (
    ConnectorRequest,
    ConnectorResult,
    SourceCoverage,
    SourceItem,
)
from chief_of_staff.connectors.instances import ASANA_PRIMARY_INSTANCE
from chief_of_staff.domain import ConnectorDomain, CoverageStatus

ASANA_TASK_ENDPOINT: Final = "GET /api/1.0/projects/{project_gid}/tasks"
ASANA_TASK_SCOPES: Final = frozenset({"tasks:read", "workspaces:read", "projects:read"})
ASANA_TASK_PAGE_SIZE: Final = 100
ASANA_TASK_MAX_PAGES: Final = 20
ASANA_TASK_FIELDS: Final = (
    "gid",
    "name",
    "completed",
    "assignee.gid",
    "due_on",
    "due_at",
    "start_on",
    "start_at",
    "created_at",
    "modified_at",
    "resource_subtype",
    "parent.gid",
    "dependencies",
    "dependents",
    "memberships.project.gid",
    "permalink_url",
)


class AsanaAuthorizationUnavailable(RuntimeError):
    """Raised when the approved mocked task authorization is unavailable."""


class AsanaAuthenticationError(RuntimeError):
    """Raised when Asana rejects a mocked task authorization."""


class AsanaRetrievalError(RuntimeError):
    """Raised when a mocked Asana task page cannot be retrieved."""


@dataclass(frozen=True, slots=True)
class AsanaAuthorization:
    """Non-secret handle for one independently authorized Asana instance."""

    account_reference: str
    project_gid: str
    granted_scopes: frozenset[str]
    credential_reference: str
    connector_instance_id: str = ASANA_PRIMARY_INSTANCE


class AsanaAuthorizationProvider(Protocol):
    """Return one mocked or stored read-only task authorization."""

    def get_asana_authorization(
        self,
        account_reference: str,
    ) -> AsanaAuthorization:
        """Return an authorization without exposing a token value."""


@dataclass(frozen=True, slots=True)
class AsanaMembership:
    """Minimum task membership facts used to enforce the exact project."""

    project_gid: str
    section_gid: str | None = None


@dataclass(frozen=True, slots=True)
class AsanaTask:
    """Approved source-owned task facts; notes and private expansions excluded."""

    gid: str
    name: str
    completed: bool
    permalink_url: str
    assignee_gid: str | None = None
    due_on: date | None = None
    due_at: datetime | None = None
    start_on: date | None = None
    start_at: datetime | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None
    resource_subtype: str | None = None
    parent_gid: str | None = None
    memberships: tuple[AsanaMembership, ...] = ()
    dependency_gids: tuple[str, ...] = ()
    dependent_gids: tuple[str, ...] = ()
    tags: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.gid.strip() or not self.name.strip():
            raise ValueError("Asana task identity and name must not be empty")
        if not self.permalink_url.startswith("https://"):
            raise ValueError("Asana task permalink must use HTTPS")
        for timestamp in (
            self.due_at,
            self.start_at,
            self.created_at,
            self.modified_at,
        ):
            if timestamp is not None and (
                timestamp.tzinfo is None or timestamp.utcoffset() is None
            ):
                raise ValueError("Asana task timestamps must be timezone-aware")


@dataclass(frozen=True, slots=True)
class AsanaTaskRequest:
    """Exact-project task query proposed for a later live gate."""

    project_gid: str
    fields: tuple[str, ...]
    limit: int
    offset: str | None = None


@dataclass(frozen=True, slots=True)
class AsanaTaskPage:
    """One synthetic provider page with an opaque next offset."""

    tasks: tuple[AsanaTask, ...]
    next_offset: str | None = None


@runtime_checkable
class AsanaTaskTransport(Protocol):
    """Retrieval-only transport; no live implementation exists."""

    def list_tasks(
        self,
        authorization: AsanaAuthorization,
        request: AsanaTaskRequest,
    ) -> AsanaTaskPage:
        """Return one standard assigned-task page."""


@dataclass(frozen=True, slots=True)
class AsanaConnector:
    """Normalize synthetic Asana tasks without enabling live task access."""

    account_reference: str
    project_gid: str
    authorization_provider: AsanaAuthorizationProvider
    transport: AsanaTaskTransport
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    @property
    def source_name(self) -> str:
        return "asana"

    @property
    def approved_scope(self) -> str:
        return (
            "synthetic Asana tasks; one exact approved project; "
            "no workspace-wide or unassigned-project retrieval; no notes, "
            "stories, attachments, custom fields, time tracking, or mutation"
        )

    def retrieve(self, request: ConnectorRequest) -> ConnectorResult:
        """Retrieve synthetic pages through the future read-only contract."""

        retrieved_at = self.clock()
        if request.approved_scope != self.approved_scope:
            raise ValueError("request scope does not match Asana connector scope")
        try:
            authorization = self.authorization_provider.get_asana_authorization(
                self.account_reference
            )
        except AsanaAuthorizationUnavailable:
            return self._result(
                retrieved_at=retrieved_at,
                status=CoverageStatus.UNAUTHORIZED,
                error_category="AsanaAuthorizationUnavailable",
            )
        if (
            authorization.account_reference != self.account_reference
            or authorization.project_gid != self.project_gid
            or authorization.granted_scopes != ASANA_TASK_SCOPES
            or authorization.connector_instance_id != ASANA_PRIMARY_INSTANCE
        ):
            return self._result(
                retrieved_at=retrieved_at,
                status=CoverageStatus.UNAUTHORIZED,
                error_category="AsanaAuthorizationBoundaryMismatch",
            )

        tasks: dict[str, AsanaTask] = {}
        duplicate_count = 0
        offset: str | None = None
        seen_offsets: set[str] = set()
        page_count = 0
        warnings: list[str] = []
        error_category: str | None = None
        for _ in range(ASANA_TASK_MAX_PAGES):
            try:
                page = self.transport.list_tasks(
                    authorization,
                    AsanaTaskRequest(
                        project_gid=self.project_gid,
                        fields=ASANA_TASK_FIELDS,
                        limit=ASANA_TASK_PAGE_SIZE,
                        offset=offset,
                    ),
                )
            except AsanaAuthenticationError:
                error_category = "AsanaAuthenticationError"
                break
            except AsanaRetrievalError:
                error_category = "AsanaRetrievalError"
                break
            page_count += 1
            for task in page.tasks:
                if not any(
                    membership.project_gid == self.project_gid
                    for membership in task.memberships
                ):
                    warnings.append(
                        "Asana task outside the exact approved project was omitted"
                    )
                    continue
                existing = tasks.get(task.gid)
                if existing is None:
                    tasks[task.gid] = task
                elif existing == task:
                    duplicate_count += 1
                else:
                    warnings.append("conflicting duplicate Asana task GID was omitted")
                    tasks.pop(task.gid, None)
            if page.next_offset is None:
                break
            if not page.next_offset or page.next_offset in seen_offsets:
                error_category = "AsanaPaginationError"
                break
            seen_offsets.add(page.next_offset)
            offset = page.next_offset
        else:
            error_category = "AsanaPageLimitError"

        items = tuple(
            _task_item(
                task,
                retrieved_at=retrieved_at,
                timezone=request.timezone,
            )
            for task in sorted(tasks.values(), key=lambda item: item.gid)
        )
        if error_category is not None and not items:
            status = (
                CoverageStatus.UNAUTHORIZED
                if error_category == "AsanaAuthenticationError"
                else CoverageStatus.UNAVAILABLE
            )
        elif error_category is not None or warnings:
            status = CoverageStatus.PARTIAL
        else:
            status = CoverageStatus.COMPLETE
        if duplicate_count:
            warnings.append(
                f"{duplicate_count} identical duplicate Asana task GIDs were deduplicated"
            )
        return self._result(
            retrieved_at=retrieved_at,
            status=status,
            items=items,
            warnings=tuple(warnings),
            error_category=error_category,
            page_count=page_count,
            retrieved_count=len(tasks) + duplicate_count,
        )

    def _result(
        self,
        *,
        retrieved_at: datetime,
        status: CoverageStatus,
        items: tuple[SourceItem, ...] = (),
        warnings: tuple[str, ...] = (),
        error_category: str | None = None,
        page_count: int | None = None,
        retrieved_count: int | None = None,
    ) -> ConnectorResult:
        return ConnectorResult(
            items=items,
            coverage=SourceCoverage(
                source=self.source_name,
                approved_scope=self.approved_scope,
                status=status,
                retrieved_at=retrieved_at,
                record_count=len(items),
                warnings=warnings,
                error_category=error_category,
                page_count=page_count,
                retrieved_count=retrieved_count,
                selected_count=len(items),
                persisted_count=0,
                connector_instance_id=ASANA_PRIMARY_INSTANCE,
                account_alias="Asana",
                domain_classification=ConnectorDomain.WORK,
            ),
        )


def _task_item(
    task: AsanaTask,
    *,
    retrieved_at: datetime,
    timezone: str,
) -> SourceItem:
    zone = ZoneInfo(timezone)
    due_at = task.due_at
    all_day = False
    due_at_value: str | None
    if due_at is None and task.due_on is not None:
        due_at_value = datetime.combine(
            task.due_on,
            time.min,
            tzinfo=zone,
        ).isoformat()
        all_day = True
    else:
        due_at_value = None if due_at is None else due_at.isoformat()
    facts: dict[str, str | int | bool | tuple[str, ...] | None] = {
        "title": task.name,
        "status": "completed" if task.completed else "open",
        "importance": 0,
        "all_day": all_day,
        "due_at": due_at_value,
        "start_at": (
            task.start_at.isoformat()
            if task.start_at is not None
            else (
                None
                if task.start_on is None
                else datetime.combine(
                    task.start_on,
                    time.min,
                    tzinfo=zone,
                ).isoformat()
            )
        ),
        "assignee_reference": task.assignee_gid,
        "issue_type": task.resource_subtype,
        "parent_reference": task.parent_gid,
        "project_reference": (
            None if not task.memberships else task.memberships[0].project_gid
        ),
        "membership_references": tuple(
            (
                membership.project_gid
                if membership.section_gid is None
                else f"{membership.project_gid}:{membership.section_gid}"
            )
            for membership in task.memberships
        ),
        "dependency_references": task.dependency_gids,
        "dependent_references": task.dependent_gids,
        "labels": tuple(name for _gid, name in task.tags),
        "source_created_at": (
            None if task.created_at is None else task.created_at.isoformat()
        ),
        "source_updated_at": (
            None if task.modified_at is None else task.modified_at.isoformat()
        ),
    }
    return SourceItem(
        id=task.gid,
        source_record_id=task.gid,
        item_type="task",
        facts=facts,
        retrieved_at=retrieved_at,
        freshness_at=task.modified_at,
        display_url=task.permalink_url,
        connector_instance_id=ASANA_PRIMARY_INSTANCE,
        account_alias="Asana",
        domain_classification=ConnectorDomain.WORK,
    )
