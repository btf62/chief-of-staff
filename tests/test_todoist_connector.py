"""Synthetic contract tests for the bounded Todoist connector."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from chief_of_staff.connectors import (
    TODOIST_DATA_READ_SCOPE,
    TODOIST_FILTER_QUERY,
    ConnectorRequest,
    TodoistAuthorization,
    TodoistAuthorizationUnavailable,
    TodoistConnector,
    TodoistFilterRequest,
    TodoistLabel,
    TodoistLabelPage,
    TodoistPageRequest,
    TodoistProject,
    TodoistRetrievalError,
    TodoistSection,
    TodoistTask,
    TodoistTaskPage,
    TodoistUser,
)
from chief_of_staff.domain import CoverageStatus
from chief_of_staff.pipeline import normalize_item, resolve_context

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
BRIEFING_DATE = date(2026, 7, 25)
ACCOUNT_IDENTITY = "selected@example.invalid"


def _request(scope: str) -> ConnectorRequest:
    context = resolve_context(
        run_id="todoist-connector-test",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )
    return ConnectorRequest(
        run_id=context.run_id,
        briefing_date=context.briefing_date,
        timezone=context.timezone,
        approved_scope=scope,
        window=context.retrieval_window,
    )


@dataclass(frozen=True, slots=True)
class _MockAuthorizationProvider:
    scopes: frozenset[str] = frozenset({TODOIST_DATA_READ_SCOPE})
    account_identity: str = ACCOUNT_IDENTITY

    def get_todoist_authorization(
        self,
        account_reference: str,
    ) -> TodoistAuthorization:
        return TodoistAuthorization(
            account_reference=account_reference,
            account_identity=self.account_identity,
            granted_scopes=self.scopes,
            credential_reference="mock-todoist-grant",
        )


@dataclass(frozen=True, slots=True)
class _UnavailableAuthorizationProvider:
    def get_todoist_authorization(
        self,
        account_reference: str,
    ) -> TodoistAuthorization:
        del account_reference
        raise TodoistAuthorizationUnavailable


@dataclass(slots=True)
class _ReadOnlyTransport:
    pages: tuple[TodoistTaskPage, ...]
    label_pages: tuple[TodoistLabelPage, ...] = ()
    fail_on_task_call: int | None = None
    task_calls: list[TodoistFilterRequest] = field(default_factory=list, init=False)
    label_calls: list[TodoistPageRequest] = field(default_factory=list, init=False)
    project_calls: list[str] = field(default_factory=list, init=False)
    section_calls: list[str] = field(default_factory=list, init=False)

    def get_authenticated_user(
        self,
        authorization: TodoistAuthorization,
    ) -> TodoistUser:
        assert authorization.credential_reference == "mock-todoist-grant"
        return TodoistUser(
            id="primary-user-id",
            email=ACCOUNT_IDENTITY,
            timezone="America/New_York",
        )

    def filter_tasks(
        self,
        authorization: TodoistAuthorization,
        request: TodoistFilterRequest,
    ) -> TodoistTaskPage:
        assert authorization.credential_reference == "mock-todoist-grant"
        self.task_calls.append(request)
        if (
            self.fail_on_task_call is not None
            and len(self.task_calls) == self.fail_on_task_call
        ):
            raise TodoistRetrievalError
        return self.pages[len(self.task_calls) - 1]

    def get_project(
        self,
        authorization: TodoistAuthorization,
        project_id: str,
    ) -> TodoistProject:
        del authorization
        self.project_calls.append(project_id)
        return TodoistProject(id=project_id, name="Synthetic project")

    def get_section(
        self,
        authorization: TodoistAuthorization,
        section_id: str,
    ) -> TodoistSection:
        del authorization
        self.section_calls.append(section_id)
        return TodoistSection(
            id=section_id,
            project_id="project-1",
            name="Synthetic section",
        )

    def list_labels(
        self,
        authorization: TodoistAuthorization,
        request: TodoistPageRequest,
    ) -> TodoistLabelPage:
        del authorization
        self.label_calls.append(request)
        return self.label_pages[len(self.label_calls) - 1]


def _boundary_tasks() -> tuple[TodoistTask, ...]:
    return (
        TodoistTask(
            id="overdue",
            content="Overdue synthetic",
            priority=4,
            due_date="2026-07-24",
            project_id="project-1",
        ),
        TodoistTask(
            id="today",
            content="Today synthetic",
            priority=4,
            due_date="2026-07-25",
            section_id="section-1",
        ),
        TodoistTask(
            id="day-14",
            content="Boundary synthetic",
            priority=4,
            due_date="2026-08-08",
            label_names=("Selected",),
        ),
        TodoistTask(
            id="day-15",
            content="Outside synthetic",
            priority=4,
            due_date="2026-08-09",
        ),
        TodoistTask(
            id="p1",
            content="P1 synthetic",
            priority=1,
        ),
        TodoistTask(
            id="p2",
            content="P2 synthetic",
            priority=2,
        ),
        TodoistTask(
            id="assigned",
            content="Assigned synthetic",
            priority=4,
            responsible_user_id="primary-user-id",
        ),
        TodoistTask(
            id="ordinary",
            content="Ordinary synthetic",
            priority=3,
        ),
    )


def _connector(
    transport: _ReadOnlyTransport,
    *,
    authorization_provider: (
        _MockAuthorizationProvider | _UnavailableAuthorizationProvider | None
    ) = None,
) -> TodoistConnector:
    return TodoistConnector(
        account_reference="primary-user",
        authorization_provider=(
            _MockAuthorizationProvider()
            if authorization_provider is None
            else authorization_provider
        ),
        transport=transport,
        clock=lambda: NOW,
    )


def test_todoist_enforces_selection_boundary_and_resolves_minimum_context() -> None:
    transport = _ReadOnlyTransport(
        pages=(
            TodoistTaskPage(
                tasks=_boundary_tasks()[:4],
                next_cursor="task-page-2",
            ),
            TodoistTaskPage(tasks=_boundary_tasks()[4:]),
        ),
        label_pages=(
            TodoistLabelPage(
                labels=(TodoistLabel(id="label-1", name="Unused"),),
                next_cursor="label-page-2",
            ),
            TodoistLabelPage(
                labels=(TodoistLabel(id="label-2", name="Selected"),),
            ),
        ),
    )
    connector = _connector(transport)

    result = connector.retrieve(_request(connector.approved_scope))

    assert result.coverage.status is CoverageStatus.COMPLETE
    assert {item.source_record_id for item in result.items} == {
        "overdue",
        "today",
        "day-14",
        "p1",
        "p2",
        "assigned",
    }
    assert [call.query for call in transport.task_calls] == [
        TODOIST_FILTER_QUERY,
        TODOIST_FILTER_QUERY,
    ]
    assert [call.cursor for call in transport.task_calls] == [
        None,
        "task-page-2",
    ]
    assert all(call.limit == 200 for call in transport.task_calls)
    assert transport.project_calls == ["project-1"]
    assert transport.section_calls == ["section-1"]
    assert len(transport.label_calls) == 2
    assert connector.last_audit is not None
    assert connector.last_audit.active_task_count == 8
    assert connector.last_audit.selected_task_count == 6
    assert connector.last_audit.labels_retrieved == 2
    assert len(connector.last_audit.labels) == 1
    assert connector.last_audit.pagination_occurred


def test_todoist_priority_is_source_signal_with_current_api_mapping() -> None:
    transport = _ReadOnlyTransport(
        pages=(
            TodoistTaskPage(
                tasks=(
                    TodoistTask(
                        id="p1",
                        content="P1 synthetic",
                        priority=1,
                        updated_at=datetime(2026, 7, 24, 15, 0, tzinfo=UTC),
                        due_date="2026-07-25",
                    ),
                    TodoistTask(
                        id="p2",
                        content="P2 synthetic",
                        priority=2,
                        due_datetime="2026-07-27T09:00:00-04:00",
                    ),
                )
            ),
        ),
    )
    connector = _connector(transport)

    result = connector.retrieve(_request(connector.approved_scope))

    p1 = normalize_item(
        connector.source_name,
        result.items[0],
        timezone="America/New_York",
    )
    p2 = normalize_item(
        connector.source_name,
        result.items[1],
        timezone="America/New_York",
    )
    assert p1.importance == 5
    assert p2.importance == 4
    assert p1.explicit_commitment is False
    assert p1.due_at == datetime(
        2026,
        7,
        25,
        0,
        0,
        tzinfo=ZoneInfo("America/New_York"),
    )
    assert result.items[0].facts["provider_priority"] == 1


def test_todoist_rejects_scope_expansion_and_filter_broadening() -> None:
    transport = _ReadOnlyTransport((TodoistTaskPage(tasks=()),))
    expanded = _connector(
        transport,
        authorization_provider=_MockAuthorizationProvider(
            scopes=frozenset({TODOIST_DATA_READ_SCOPE, "data:read_write"})
        ),
    )

    result = expanded.retrieve(_request(expanded.approved_scope))

    assert result.coverage.status is CoverageStatus.UNAUTHORIZED
    assert result.coverage.error_category == "TodoistAuthorizationScopeMismatch"
    assert transport.task_calls == []
    try:
        TodoistConnector(
            account_reference="primary-user",
            authorization_provider=_MockAuthorizationProvider(),
            transport=transport,
            filter_query="view all",
        )
    except ValueError as error:
        assert "may not be broadened" in str(error)
    else:
        raise AssertionError("TodoistConnector accepted a broader task filter")


def test_todoist_distinguishes_unauthorized_from_empty() -> None:
    pages = (TodoistTaskPage(tasks=()),)
    unauthorized_transport = _ReadOnlyTransport(pages)
    unauthorized = _connector(
        unauthorized_transport,
        authorization_provider=_UnavailableAuthorizationProvider(),
    )
    empty_transport = _ReadOnlyTransport(pages)
    empty = _connector(empty_transport)

    unauthorized_result = unauthorized.retrieve(_request(unauthorized.approved_scope))
    empty_result = empty.retrieve(_request(empty.approved_scope))

    assert unauthorized_result.coverage.status is CoverageStatus.UNAUTHORIZED
    assert unauthorized_result.coverage.error_category == (
        "TodoistAuthorizationUnavailable"
    )
    assert unauthorized_transport.task_calls == []
    assert empty_result.coverage.status is CoverageStatus.COMPLETE
    assert empty_result.coverage.record_count == 0


def test_todoist_retains_first_page_during_partial_failure() -> None:
    transport = _ReadOnlyTransport(
        pages=(
            TodoistTaskPage(
                tasks=(
                    TodoistTask(
                        id="p1",
                        content="P1 synthetic",
                        priority=1,
                    ),
                ),
                next_cursor="task-page-2",
            ),
        ),
        fail_on_task_call=2,
    )
    connector = _connector(transport)

    result = connector.retrieve(_request(connector.approved_scope))

    assert result.coverage.status is CoverageStatus.PARTIAL
    assert result.coverage.record_count == 1
    assert result.coverage.error_category == "TodoistRetrievalError"
    assert "stopped before page 2" in result.coverage.warnings[0]


def test_todoist_contract_exposes_no_mutation_operations() -> None:
    connector = _connector(_ReadOnlyTransport((TodoistTaskPage(tasks=()),)))

    for boundary in (connector, connector.transport):
        for operation in (
            "add",
            "close",
            "complete",
            "create",
            "delete",
            "move",
            "reopen",
            "update",
            "write",
        ):
            assert not hasattr(boundary, operation)
