"""Read-only Todoist contract with injectable authorization and transport."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Final, Protocol, runtime_checkable
from urllib.parse import quote
from zoneinfo import ZoneInfo

from chief_of_staff.connectors.contracts import (
    ConnectorRequest,
    ConnectorResult,
    SourceCoverage,
    SourceItem,
)
from chief_of_staff.domain import CoverageStatus

TODOIST_DATA_READ_SCOPE: Final = "data:read"
TODOIST_FILTER_QUERY: Final = "overdue | 7 days | p1"
TODOIST_PAGE_LIMIT: Final = 200
DEFAULT_MAX_PAGES: Final = 100


class TodoistAuthorizationUnavailable(RuntimeError):
    """Raised by an authorization boundary with no usable approved grant."""


class TodoistAuthenticationError(RuntimeError):
    """Raised when Todoist rejects an otherwise present authorization."""


class TodoistRetrievalError(RuntimeError):
    """Expected provider retrieval failure without private response content."""


@dataclass(frozen=True, slots=True)
class TodoistAuthorization:
    """Non-secret authorization metadata supplied to a Todoist transport."""

    account_reference: str
    granted_scopes: frozenset[str]
    credential_reference: str


@dataclass(frozen=True, slots=True)
class TodoistFilterRequest:
    """Fixed, bounded parameters for the provider's task-filter operation."""

    query: str
    cursor: str | None
    limit: int = TODOIST_PAGE_LIMIT


@dataclass(frozen=True, slots=True)
class TodoistTask:
    """Minimal provider task fields needed for deterministic normalization."""

    id: str
    content: str
    priority: int
    updated_at: datetime | None = None
    due_date: str | None = None
    due_datetime: str | None = None


@dataclass(frozen=True, slots=True)
class TodoistTaskPage:
    """One provider page and its opaque continuation cursor."""

    tasks: tuple[TodoistTask, ...]
    next_cursor: str | None = None


@runtime_checkable
class TodoistAuthorizationProvider(Protocol):
    """Mockable OAuth boundary; live implementation requires approval."""

    def get_todoist_authorization(
        self,
        account_reference: str,
    ) -> TodoistAuthorization:
        """Return non-secret grant metadata or raise unavailable."""


@runtime_checkable
class TodoistTransport(Protocol):
    """Provider boundary exposing only read-only task filtering."""

    def filter_tasks(
        self,
        authorization: TodoistAuthorization,
        request: TodoistFilterRequest,
    ) -> TodoistTaskPage:
        """Return one task page without exposing mutation operations."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class TodoistConnector:
    """Retrieve a fixed subset of active tasks through injected boundaries."""

    account_reference: str
    authorization_provider: TodoistAuthorizationProvider
    transport: TodoistTransport
    filter_query: str = TODOIST_FILTER_QUERY
    max_pages: int = DEFAULT_MAX_PAGES
    clock: Callable[[], datetime] = field(
        default=_utc_now,
        repr=False,
        compare=False,
    )
    source_name: str = field(default="todoist", init=False)
    approved_scope: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.account_reference.strip():
            raise ValueError("Todoist account reference must not be empty")
        if "@" in self.account_reference or any(
            character.isspace() for character in self.account_reference
        ):
            raise ValueError("Todoist account reference must be an opaque alias")
        if self.filter_query != TODOIST_FILTER_QUERY:
            raise ValueError("the Todoist filter may not be broadened")
        if self.max_pages < 1:
            raise ValueError("Todoist max_pages must be positive")
        object.__setattr__(
            self,
            "approved_scope",
            (
                f"Todoist account alias={self.account_reference}; "
                f"filter={self.filter_query}"
            ),
        )

    def retrieve(self, request: ConnectorRequest) -> ConnectorResult:
        """Retrieve all available task pages or disclose bounded failure."""

        if request.approved_scope != self.approved_scope:
            raise ValueError("request scope does not match connector scope")
        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("connector clock must return a timezone-aware value")

        try:
            authorization = self.authorization_provider.get_todoist_authorization(
                self.account_reference
            )
        except TodoistAuthorizationUnavailable:
            return self._coverage_result(
                retrieved_at=retrieved_at,
                status=CoverageStatus.UNAUTHORIZED,
                error_category="TodoistAuthorizationUnavailable",
                page_count=0,
            )

        if (
            authorization.account_reference != self.account_reference
            or authorization.granted_scopes != frozenset({TODOIST_DATA_READ_SCOPE})
        ):
            return self._coverage_result(
                retrieved_at=retrieved_at,
                status=CoverageStatus.UNAUTHORIZED,
                error_category="TodoistAuthorizationScopeMismatch",
                page_count=0,
            )

        items: list[SourceItem] = []
        warnings: list[str] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page_number = 0
        while page_number < self.max_pages:
            page_number += 1
            filter_request = TodoistFilterRequest(
                query=self.filter_query,
                cursor=cursor,
            )
            try:
                page = self.transport.filter_tasks(authorization, filter_request)
            except TodoistAuthenticationError:
                return self._coverage_result(
                    retrieved_at=retrieved_at,
                    status=CoverageStatus.UNAUTHORIZED,
                    items=tuple(items),
                    warnings=(
                        *warnings,
                        f"Todoist authorization failed before page {page_number}",
                    ),
                    error_category="TodoistAuthenticationError",
                    page_count=page_number - 1,
                )
            except TodoistRetrievalError:
                return self._coverage_result(
                    retrieved_at=retrieved_at,
                    status=(
                        CoverageStatus.PARTIAL if items else CoverageStatus.UNAVAILABLE
                    ),
                    items=tuple(items),
                    warnings=(
                        *warnings,
                        f"Todoist retrieval stopped before page {page_number}",
                    ),
                    error_category="TodoistRetrievalError",
                    page_count=page_number - 1,
                )

            for task in page.tasks:
                try:
                    items.append(
                        _task_to_source_item(
                            task,
                            timezone=request.timezone,
                            retrieved_at=retrieved_at,
                        )
                    )
                except ValueError:
                    warnings.append(
                        f"one Todoist task on page {page_number} was invalid and omitted"
                    )

            next_cursor = page.next_cursor
            if next_cursor is None:
                return self._coverage_result(
                    retrieved_at=retrieved_at,
                    status=(
                        CoverageStatus.PARTIAL if warnings else CoverageStatus.COMPLETE
                    ),
                    items=tuple(items),
                    warnings=tuple(warnings),
                    error_category=("TodoistTaskValidationError" if warnings else None),
                    page_count=page_number,
                )
            if not next_cursor:
                warnings.append("Todoist pagination returned an empty cursor")
                return self._coverage_result(
                    retrieved_at=retrieved_at,
                    status=CoverageStatus.PARTIAL,
                    items=tuple(items),
                    warnings=tuple(warnings),
                    error_category="TodoistPaginationCursorInvalid",
                    page_count=page_number,
                )
            if next_cursor in seen_cursors:
                warnings.append("Todoist pagination returned a repeated cursor")
                return self._coverage_result(
                    retrieved_at=retrieved_at,
                    status=CoverageStatus.PARTIAL,
                    items=tuple(items),
                    warnings=tuple(warnings),
                    error_category="TodoistPaginationLoop",
                    page_count=page_number,
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        warnings.append(f"Todoist retrieval reached the {self.max_pages}-page limit")
        return self._coverage_result(
            retrieved_at=retrieved_at,
            status=CoverageStatus.PARTIAL,
            items=tuple(items),
            warnings=tuple(warnings),
            error_category="TodoistPageLimit",
            page_count=page_number,
        )

    def _coverage_result(
        self,
        *,
        retrieved_at: datetime,
        status: CoverageStatus,
        items: tuple[SourceItem, ...] = (),
        warnings: tuple[str, ...] = (),
        error_category: str | None = None,
        page_count: int | None = None,
    ) -> ConnectorResult:
        freshness_values = tuple(
            item.freshness_at for item in items if item.freshness_at is not None
        )
        return ConnectorResult(
            items=items,
            coverage=SourceCoverage(
                source=self.source_name,
                approved_scope=self.approved_scope,
                status=status,
                retrieved_at=retrieved_at,
                record_count=len(items),
                freshness_at=max(freshness_values) if freshness_values else None,
                warnings=warnings,
                error_category=error_category,
                page_count=page_count,
            ),
        )


def _task_to_source_item(
    task: TodoistTask,
    *,
    timezone: str,
    retrieved_at: datetime,
) -> SourceItem:
    task_id = task.id.strip()
    if not task_id:
        raise ValueError("Todoist task ID must not be empty")
    content = task.content.strip()
    if not content:
        raise ValueError("Todoist task content must not be empty")
    if task.priority not in {1, 2, 3, 4}:
        raise ValueError("Todoist task priority must be between 1 and 4")
    if task.due_date is not None and task.due_datetime is not None:
        raise ValueError("Todoist task may not have two due representations")

    zone = ZoneInfo(timezone)
    due_at: datetime | None = None
    all_day = False
    if task.due_datetime is not None:
        due_at = _due_datetime(task.due_datetime, zone=zone)
    elif task.due_date is not None:
        due_at = _due_date(task.due_date, zone=zone)
        all_day = True

    freshness_at = None
    if task.updated_at is not None:
        if task.updated_at.tzinfo is None or task.updated_at.utcoffset() is None:
            raise ValueError("Todoist task freshness must be timezone-aware")
        freshness_at = task.updated_at.astimezone(UTC)

    facts: dict[str, str | int | bool | None] = {
        "title": content,
        "summary": None,
        "status": "open",
        "importance": {1: 1, 2: 3, 3: 4, 4: 5}[task.priority],
        "provider_priority": task.priority,
        "explicit_commitment": False,
        "all_day": all_day,
        "due_at": None if due_at is None else due_at.isoformat(),
    }
    return SourceItem(
        id=task_id,
        source_record_id=task_id,
        item_type="task",
        facts=facts,
        retrieved_at=retrieved_at,
        freshness_at=freshness_at,
        display_url=("https://app.todoist.com/app/task/" + quote(task_id, safe="")),
    )


def _due_date(value: str, *, zone: ZoneInfo) -> datetime:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Todoist due date must be an ISO date") from None
    return datetime.combine(parsed, time.min, tzinfo=zone)


def _due_datetime(value: str, *, zone: ZoneInfo) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("Todoist due datetime must be ISO 8601") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Todoist due datetime must be timezone-aware")
    return parsed.astimezone(zone)
