"""Bounded read-only Todoist retrieval and normalization contract."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Final, Protocol, runtime_checkable
from urllib.parse import quote
from zoneinfo import ZoneInfo

from chief_of_staff.connectors.contracts import (
    ConnectorRequest,
    ConnectorResult,
    ContextResourceCoverage,
    SourceCoverage,
    SourceItem,
)
from chief_of_staff.domain import CoverageStatus

TODOIST_DATA_READ_SCOPE: Final = "data:read"
TODOIST_FILTER_QUERY: Final = "overdue | 15 days | p1 | p2 | assigned to: me"
TODOIST_ACTIVE_TASK_ENDPOINT: Final = "/api/v1/tasks"
TODOIST_DUE_LOOKAHEAD_DAYS: Final = 14
TODOIST_PAGE_LIMIT: Final = 200
DEFAULT_MAX_PAGES: Final = 100


class TodoistAuthorizationUnavailable(RuntimeError):
    """Raised by an authorization boundary with no usable approved grant."""


class TodoistAuthenticationError(RuntimeError):
    """Raised when Todoist rejects an otherwise present authorization."""


class TodoistRetrievalError(RuntimeError):
    """Expected provider retrieval failure without private response content."""


class TodoistRateLimitError(TodoistRetrievalError):
    """Raised when Todoist applies a provider rate limit."""


@dataclass(frozen=True, slots=True)
class TodoistAuthorization:
    """Non-secret authorization metadata supplied to a Todoist transport."""

    account_reference: str
    account_identity: str
    granted_scopes: frozenset[str]
    credential_reference: str


@dataclass(frozen=True, slots=True)
class TodoistFilterRequest:
    """Fixed, bounded parameters for the provider's task-filter operation."""

    query: str
    cursor: str | None
    limit: int = TODOIST_PAGE_LIMIT


@dataclass(frozen=True, slots=True)
class TodoistPageRequest:
    """Cursor parameters for a read-only context collection."""

    cursor: str | None
    limit: int = TODOIST_PAGE_LIMIT


@dataclass(frozen=True, slots=True)
class TodoistUser:
    """Minimum current-user identity needed to confirm the selected account."""

    id: str
    email: str
    timezone: str | None = None


@dataclass(frozen=True, slots=True)
class TodoistTask:
    """Provider task facts permitted by the bounded trial."""

    id: str
    content: str
    priority: int
    project_id: str | None = None
    section_id: str | None = None
    label_names: tuple[str, ...] = ()
    responsible_user_id: str | None = None
    parent_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    due_date: str | None = None
    due_datetime: str | None = None
    due_timezone: str | None = None
    recurring: bool = False


@dataclass(frozen=True, slots=True)
class TodoistTaskPage:
    """One provider task page and its opaque continuation cursor."""

    tasks: tuple[TodoistTask, ...]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class TodoistProject:
    """Minimum project context for a selected task."""

    id: str
    name: str
    is_shared: bool = False
    can_assign_tasks: bool = False


@dataclass(frozen=True, slots=True)
class TodoistSection:
    """Minimum section context for a selected task."""

    id: str
    project_id: str
    name: str


@dataclass(frozen=True, slots=True)
class TodoistLabel:
    """Minimum personal-label context for a selected task."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class TodoistLabelPage:
    """One provider label page and its opaque continuation cursor."""

    labels: tuple[TodoistLabel, ...]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class TodoistRetrievalAudit:
    """Transient private details plus safe counts for lifecycle reporting."""

    active_task_count: int
    task_page_count: int
    label_page_count: int
    projects_retrieved: int
    sections_retrieved: int
    labels_retrieved: int
    duplicate_task_id_count: int
    qualification_counts: tuple[tuple[str, int], ...]
    qualification_overlaps: tuple[tuple[str, int], ...]
    retrieved_tasks: tuple[TodoistTask, ...] = field(repr=False)
    selected_tasks: tuple[TodoistTask, ...] = field(repr=False)
    projects: tuple[TodoistProject, ...] = field(repr=False)
    sections: tuple[TodoistSection, ...] = field(repr=False)
    labels: tuple[TodoistLabel, ...] = field(repr=False)
    full_active_task_collection_retrieved: bool = False
    concurrent_changes_cannot_be_excluded: bool = False

    @property
    def selected_task_count(self) -> int:
        return len(self.selected_tasks)

    @property
    def pagination_occurred(self) -> bool:
        return self.task_page_count > 1 or self.label_page_count > 1


@runtime_checkable
class TodoistAuthorizationProvider(Protocol):
    """OAuth boundary that returns only approved non-secret grant metadata."""

    def get_todoist_authorization(
        self,
        account_reference: str,
    ) -> TodoistAuthorization:
        """Return non-secret grant metadata or raise unavailable."""


@runtime_checkable
class TodoistTransport(Protocol):
    """Read-only Todoist resources reachable by the bounded connector."""

    def get_authenticated_user(
        self,
        authorization: TodoistAuthorization,
    ) -> TodoistUser:
        """Return only identity needed to confirm the connected account."""

    def list_tasks(
        self,
        authorization: TodoistAuthorization,
        request: TodoistPageRequest,
    ) -> TodoistTaskPage:
        """Return one page from the complete active-task collection."""

    def get_project(
        self,
        authorization: TodoistAuthorization,
        project_id: str,
    ) -> TodoistProject:
        """Return one project referenced by a selected task."""

    def get_section(
        self,
        authorization: TodoistAuthorization,
        section_id: str,
    ) -> TodoistSection:
        """Return one section referenced by a selected task."""

    def list_labels(
        self,
        authorization: TodoistAuthorization,
        request: TodoistPageRequest,
    ) -> TodoistLabelPage:
        """Return one page of labels when selected tasks require them."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class TodoistConnector:
    """Retrieve only approved active tasks and their necessary context."""

    account_reference: str
    authorization_provider: TodoistAuthorizationProvider
    transport: TodoistTransport
    task_endpoint: str = TODOIST_ACTIVE_TASK_ENDPOINT
    relevant_task_ids: frozenset[str] = frozenset()
    max_pages: int = DEFAULT_MAX_PAGES
    clock: Callable[[], datetime] = field(
        default=_utc_now,
        repr=False,
        compare=False,
    )
    source_name: str = field(default="todoist", init=False)
    approved_scope: str = field(init=False)
    last_audit: TodoistRetrievalAudit | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if not self.account_reference.strip():
            raise ValueError("Todoist account reference must not be empty")
        if "@" in self.account_reference or any(
            character.isspace() for character in self.account_reference
        ):
            raise ValueError("Todoist account reference must be an opaque alias")
        if self.task_endpoint != TODOIST_ACTIVE_TASK_ENDPOINT:
            raise ValueError("the Todoist active-task endpoint may not be changed")
        if self.max_pages < 1:
            raise ValueError("Todoist max_pages must be positive")
        self.approved_scope = (
            f"Todoist account alias={self.account_reference}; "
            f"endpoint={self.task_endpoint}; active tasks only"
        )

    def retrieve(self, request: ConnectorRequest) -> ConnectorResult:
        """Retrieve selected tasks, resolve minimal context, and disclose gaps."""

        self.last_audit = None
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

        try:
            user = self.transport.get_authenticated_user(authorization)
        except TodoistAuthenticationError:
            return self._coverage_result(
                retrieved_at=retrieved_at,
                status=CoverageStatus.UNAUTHORIZED,
                error_category="TodoistAuthenticationError",
                page_count=0,
            )
        except TodoistRetrievalError as error:
            return self._coverage_result(
                retrieved_at=retrieved_at,
                status=CoverageStatus.UNAVAILABLE,
                error_category=type(error).__name__,
                page_count=0,
            )
        if user.email.casefold() != authorization.account_identity.casefold():
            return self._coverage_result(
                retrieved_at=retrieved_at,
                status=CoverageStatus.UNAUTHORIZED,
                error_category="TodoistAccountIdentityMismatch",
                page_count=0,
            )

        warnings: list[str] = []
        if user.timezone is not None and user.timezone != request.timezone:
            warnings.append(
                "Todoist account timezone differs from the briefing timezone"
            )

        (
            active_tasks,
            active_task_count,
            duplicate_task_id_count,
            task_pages,
            task_error,
        ) = self._retrieve_tasks(
            authorization,
            warnings=warnings,
        )
        if task_error is not None and not active_tasks:
            status = (
                CoverageStatus.UNAUTHORIZED
                if task_error == "TodoistAuthenticationError"
                else CoverageStatus.UNAVAILABLE
            )
            return self._coverage_result(
                retrieved_at=retrieved_at,
                status=status,
                warnings=tuple(warnings),
                error_category=task_error,
                page_count=task_pages,
                retrieved_count=active_task_count,
                selected_count=0,
            )

        try:
            (
                tasks,
                projects,
                sections,
                labels,
                label_pages,
                context_error,
            ) = self._resolve_context(
                authorization,
                candidate_tasks=active_tasks,
                request=request,
                user=user,
                warnings=warnings,
            )
        except TodoistAuthenticationError:
            return self._coverage_result(
                retrieved_at=retrieved_at,
                status=CoverageStatus.UNAUTHORIZED,
                warnings=(
                    *warnings,
                    "Todoist authorization failed during context retrieval",
                ),
                error_category="TodoistAuthenticationError",
                page_count=task_pages,
                retrieved_count=active_task_count,
                selected_count=0,
            )
        items: list[SourceItem] = []
        for task in tasks:
            try:
                items.append(
                    _task_to_source_item(
                        task,
                        projects=projects,
                        sections=sections,
                        labels=labels,
                        timezone=request.timezone,
                        retrieved_at=retrieved_at,
                    )
                )
            except ValueError:
                warnings.append("one selected Todoist task was invalid and omitted")
        usable_task_ids = {item.source_record_id for item in items}
        tasks = tuple(task for task in tasks if task.id in usable_task_ids)

        error_category = task_error or context_error
        status = (
            CoverageStatus.PARTIAL
            if warnings or error_category is not None
            else CoverageStatus.COMPLETE
        )
        used_label_names = {
            label.casefold() for task in tasks for label in task.label_names
        }
        used_labels = tuple(
            label for label in labels if label.name.casefold() in used_label_names
        )
        project_by_id = {project.id: project for project in projects}
        qualifications = tuple(
            qualify_todoist_task(
                task,
                briefing_date=request.briefing_date,
                timezone=request.timezone,
                user_id=user.id,
                projects=project_by_id,
                relevant_task_ids=self.relevant_task_ids,
            )
            for task in active_tasks
        )
        self.last_audit = TodoistRetrievalAudit(
            active_task_count=active_task_count,
            task_page_count=task_pages,
            label_page_count=label_pages,
            projects_retrieved=len(projects),
            sections_retrieved=len(sections),
            labels_retrieved=len(labels),
            duplicate_task_id_count=duplicate_task_id_count,
            qualification_counts=_qualification_counts(qualifications),
            qualification_overlaps=_qualification_overlaps(qualifications),
            retrieved_tasks=active_tasks,
            selected_tasks=tasks,
            projects=projects,
            sections=sections,
            labels=used_labels,
            full_active_task_collection_retrieved=task_error is None,
            concurrent_changes_cannot_be_excluded=task_pages > 1,
        )
        return self._coverage_result(
            retrieved_at=retrieved_at,
            status=status,
            items=tuple(items),
            warnings=tuple(warnings),
            error_category=error_category,
            page_count=task_pages + label_pages,
            retrieved_count=active_task_count,
            selected_count=len(items),
            context_resources=(
                ContextResourceCoverage(
                    resource="projects",
                    retrieved_count=len(projects),
                ),
                ContextResourceCoverage(
                    resource="sections",
                    retrieved_count=len(sections),
                ),
                ContextResourceCoverage(
                    resource="labels",
                    retrieved_count=len(labels),
                ),
            ),
        )

    def _retrieve_tasks(
        self,
        authorization: TodoistAuthorization,
        *,
        warnings: list[str],
    ) -> tuple[tuple[TodoistTask, ...], int, int, int, str | None]:
        active_tasks: dict[str, TodoistTask] = {}
        duplicate_task_id_count = 0
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page_number = 0
        while page_number < self.max_pages:
            page_number += 1
            try:
                page = self.transport.list_tasks(
                    authorization,
                    TodoistPageRequest(cursor=cursor),
                )
            except TodoistAuthenticationError:
                warnings.append(
                    f"Todoist authorization failed before task page {page_number}"
                )
                return (
                    tuple(active_tasks.values()),
                    len(active_tasks),
                    duplicate_task_id_count,
                    page_number - 1,
                    "TodoistAuthenticationError",
                )
            except TodoistRetrievalError as error:
                warnings.append(
                    f"Todoist task retrieval stopped before page {page_number}"
                )
                return (
                    tuple(active_tasks.values()),
                    len(active_tasks),
                    duplicate_task_id_count,
                    page_number - 1,
                    type(error).__name__,
                )

            for task in page.tasks:
                if task.id in active_tasks:
                    duplicate_task_id_count += 1
                active_tasks[task.id] = task

            cursor_error = _next_cursor_error(
                page.next_cursor,
                seen_cursors=seen_cursors,
            )
            if cursor_error is None and page.next_cursor is None:
                return (
                    tuple(active_tasks.values()),
                    len(active_tasks),
                    duplicate_task_id_count,
                    page_number,
                    None,
                )
            if cursor_error is not None:
                warnings.append(cursor_error)
                return (
                    tuple(active_tasks.values()),
                    len(active_tasks),
                    duplicate_task_id_count,
                    page_number,
                    "TodoistPaginationError",
                )
            cursor = page.next_cursor

        warnings.append(
            f"Todoist task retrieval reached the {self.max_pages}-page limit"
        )
        return (
            tuple(active_tasks.values()),
            len(active_tasks),
            duplicate_task_id_count,
            page_number,
            "TodoistPageLimit",
        )

    def _resolve_context(
        self,
        authorization: TodoistAuthorization,
        *,
        candidate_tasks: tuple[TodoistTask, ...],
        request: ConnectorRequest,
        user: TodoistUser,
        warnings: list[str],
    ) -> tuple[
        tuple[TodoistTask, ...],
        tuple[TodoistProject, ...],
        tuple[TodoistSection, ...],
        tuple[TodoistLabel, ...],
        int,
        str | None,
    ]:
        projects: list[TodoistProject] = []
        sections: list[TodoistSection] = []
        context_error: str | None = None
        for project_id in sorted(
            {task.project_id for task in candidate_tasks if task.project_id}
        ):
            try:
                projects.append(self.transport.get_project(authorization, project_id))
            except TodoistAuthenticationError:
                raise
            except TodoistRetrievalError as error:
                warnings.append("one selected Todoist project could not be resolved")
                context_error = type(error).__name__
        project_by_id = {project.id: project for project in projects}
        selected_tasks = tuple(
            task
            for task in candidate_tasks
            if _task_matches_boundary(
                task,
                briefing_date=request.briefing_date,
                timezone=request.timezone,
                user_id=user.id,
                projects=project_by_id,
                relevant_task_ids=self.relevant_task_ids,
            )
        )
        for section_id in sorted(
            {task.section_id for task in selected_tasks if task.section_id}
        ):
            try:
                sections.append(self.transport.get_section(authorization, section_id))
            except TodoistAuthenticationError:
                raise
            except TodoistRetrievalError as error:
                warnings.append("one selected Todoist section could not be resolved")
                context_error = type(error).__name__

        if not any(task.label_names for task in selected_tasks):
            return (
                selected_tasks,
                tuple(projects),
                tuple(sections),
                (),
                0,
                context_error,
            )

        labels: list[TodoistLabel] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page_number = 0
        while page_number < self.max_pages:
            page_number += 1
            try:
                page = self.transport.list_labels(
                    authorization,
                    TodoistPageRequest(cursor=cursor),
                )
            except TodoistAuthenticationError:
                raise
            except TodoistRetrievalError as error:
                warnings.append(
                    f"Todoist label retrieval stopped before page {page_number}"
                )
                return (
                    selected_tasks,
                    tuple(projects),
                    tuple(sections),
                    tuple(labels),
                    page_number - 1,
                    type(error).__name__,
                )
            labels.extend(page.labels)
            cursor_error = _next_cursor_error(
                page.next_cursor,
                seen_cursors=seen_cursors,
            )
            if cursor_error is None and page.next_cursor is None:
                return (
                    selected_tasks,
                    tuple(projects),
                    tuple(sections),
                    tuple(labels),
                    page_number,
                    context_error,
                )
            if cursor_error is not None:
                warnings.append(cursor_error)
                return (
                    selected_tasks,
                    tuple(projects),
                    tuple(sections),
                    tuple(labels),
                    page_number,
                    "TodoistPaginationError",
                )
            cursor = page.next_cursor
        warnings.append(
            f"Todoist label retrieval reached the {self.max_pages}-page limit"
        )
        return (
            selected_tasks,
            tuple(projects),
            tuple(sections),
            tuple(labels),
            page_number,
            "TodoistPageLimit",
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
        retrieved_count: int | None = None,
        selected_count: int | None = None,
        context_resources: tuple[ContextResourceCoverage, ...] = (),
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
                retrieved_count=retrieved_count,
                selected_count=selected_count,
                context_resources=context_resources,
            ),
        )


def _next_cursor_error(
    next_cursor: str | None,
    *,
    seen_cursors: set[str],
) -> str | None:
    if next_cursor is None:
        return None
    if not next_cursor:
        return "Todoist pagination returned an empty cursor"
    if next_cursor in seen_cursors:
        return "Todoist pagination returned a repeated cursor"
    seen_cursors.add(next_cursor)
    return None


@dataclass(frozen=True, slots=True)
class TodoistQualification:
    """Independent deterministic reasons one active task may be selected."""

    overdue: bool
    due_today: bool
    due_within_14_days: bool
    p1: bool
    p2: bool
    shared_assignment: bool
    explicit_priority_link: bool

    @property
    def selected(self) -> bool:
        return any(self.as_pairs().values())

    def as_pairs(self) -> dict[str, bool]:
        return {
            "overdue": self.overdue,
            "due_today": self.due_today,
            "due_within_14_days": self.due_within_14_days,
            "p1": self.p1,
            "p2": self.p2,
            "shared_assignment": self.shared_assignment,
            "explicit_priority_link": self.explicit_priority_link,
        }


def qualify_todoist_task(
    task: TodoistTask,
    *,
    briefing_date: date,
    timezone: str,
    user_id: str,
    projects: dict[str, TodoistProject],
    relevant_task_ids: frozenset[str],
) -> TodoistQualification:
    """Attribute every accepted selection rule independently."""

    due_at, _all_day = _task_due_at(task, zone=ZoneInfo(timezone))
    due_date = None if due_at is None else due_at.date()
    project = None if task.project_id is None else projects.get(task.project_id)
    return TodoistQualification(
        overdue=due_date is not None and due_date < briefing_date,
        due_today=due_date == briefing_date,
        due_within_14_days=(
            due_date is not None
            and briefing_date
            < due_date
            <= briefing_date + timedelta(days=TODOIST_DUE_LOOKAHEAD_DAYS)
        ),
        p1=task.priority == 4,
        p2=task.priority == 3,
        shared_assignment=bool(
            task.responsible_user_id == user_id
            and project is not None
            and project.is_shared
            and project.can_assign_tasks
        ),
        explicit_priority_link=task.id in relevant_task_ids,
    )


def _task_matches_boundary(
    task: TodoistTask,
    *,
    briefing_date: date,
    timezone: str,
    user_id: str,
    projects: dict[str, TodoistProject],
    relevant_task_ids: frozenset[str],
) -> bool:
    return qualify_todoist_task(
        task,
        briefing_date=briefing_date,
        timezone=timezone,
        user_id=user_id,
        projects=projects,
        relevant_task_ids=relevant_task_ids,
    ).selected


def _qualification_counts(
    qualifications: tuple[TodoistQualification, ...],
) -> tuple[tuple[str, int], ...]:
    return tuple(
        (rule, sum(qualification.as_pairs()[rule] for qualification in qualifications))
        for rule in TodoistQualification(
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        ).as_pairs()
    )


def _qualification_overlaps(
    qualifications: tuple[TodoistQualification, ...],
) -> tuple[tuple[str, int], ...]:
    overlaps: dict[str, int] = {}
    for qualification in qualifications:
        rules = tuple(
            rule for rule, matched in qualification.as_pairs().items() if matched
        )
        if len(rules) < 2:
            continue
        key = "+".join(rules)
        overlaps[key] = overlaps.get(key, 0) + 1
    return tuple(sorted(overlaps.items()))


def stored_task_matches_selection_boundary(
    *,
    source_record_id: str,
    provider_priority: int,
    due_at: datetime | None,
    briefing_date: date,
    relevant_task_ids: frozenset[str] = frozenset(),
    assignment_is_distinguishing: bool = False,
) -> bool:
    """Evaluate minimal persisted facts without performing source retrieval."""

    if source_record_id in relevant_task_ids or provider_priority in {3, 4}:
        return True
    if due_at is not None and due_at.date() <= briefing_date + timedelta(
        days=TODOIST_DUE_LOOKAHEAD_DAYS
    ):
        return True
    return assignment_is_distinguishing


def _task_to_source_item(
    task: TodoistTask,
    *,
    projects: tuple[TodoistProject, ...],
    sections: tuple[TodoistSection, ...],
    labels: tuple[TodoistLabel, ...],
    timezone: str,
    retrieved_at: datetime,
) -> SourceItem:
    task_id = task.id.strip()
    content = task.content.strip()
    if not task_id or not content:
        raise ValueError("Todoist task ID and content must not be empty")
    if task.priority not in {1, 2, 3, 4}:
        raise ValueError("Todoist task priority must be between 1 and 4")

    due_at, all_day = _task_due_at(task, zone=ZoneInfo(timezone))
    freshness_at = _optional_utc(task.updated_at)
    project = next(
        (item for item in projects if item.id == task.project_id),
        None,
    )
    section = next(
        (item for item in sections if item.id == task.section_id),
        None,
    )
    label_by_name = {item.name.casefold(): item for item in labels}
    resolved_labels = tuple(
        label_by_name[name.casefold()]
        for name in task.label_names
        if name.casefold() in label_by_name
    )
    context_parts = [
        value
        for value in (
            None if project is None else f"Project: {project.name}",
            None if section is None else f"Section: {section.name}",
            (
                None
                if not resolved_labels
                else "Labels: " + ", ".join(label.name for label in resolved_labels)
            ),
        )
        if value is not None
    ]
    facts: dict[str, str | int | bool | None] = {
        "title": content,
        "summary": "; ".join(context_parts) or None,
        "status": "open",
        "importance": {1: 1, 2: 2, 3: 4, 4: 5}[task.priority],
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


def task_due_at(task: TodoistTask, *, timezone: str) -> tuple[datetime | None, bool]:
    """Expose normalized due timing for persistence without source payloads."""

    return _task_due_at(task, zone=ZoneInfo(timezone))


def _task_due_at(
    task: TodoistTask,
    *,
    zone: ZoneInfo,
) -> tuple[datetime | None, bool]:
    if task.due_date is not None and task.due_datetime is not None:
        raise ValueError("Todoist task may not have two due representations")
    if task.due_datetime is not None:
        return _due_datetime(task.due_datetime, zone=zone), False
    if task.due_date is not None:
        return _due_date(task.due_date, zone=zone), True
    return None, False


def _optional_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Todoist task timestamp must be timezone-aware")
    return value.astimezone(UTC)


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
        return parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)
