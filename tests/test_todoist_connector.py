"""Synthetic contract tests for the bounded Todoist connector."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from chief_of_staff.connectors import (
    TODOIST_ACTIVE_TASK_ENDPOINT,
    TODOIST_DATA_READ_SCOPE,
    ConnectorRequest,
    TodoistAuthorization,
    TodoistAuthorizationUnavailable,
    TodoistConnector,
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
    task_calls: list[TodoistPageRequest] = field(default_factory=list, init=False)
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

    def list_tasks(
        self,
        authorization: TodoistAuthorization,
        request: TodoistPageRequest,
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
        return TodoistProject(
            id=project_id,
            name="Synthetic project",
            is_shared=project_id != "project-personal",
            can_assign_tasks=project_id != "project-personal",
        )

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
            priority=1,
            due_date="2026-07-24",
            project_id="project-1",
        ),
        TodoistTask(
            id="today",
            content="Today synthetic",
            priority=1,
            due_date="2026-07-25",
            section_id="section-1",
        ),
        TodoistTask(
            id="day-14",
            content="Boundary synthetic",
            priority=1,
            due_date="2026-08-08",
            label_names=("Selected",),
        ),
        TodoistTask(
            id="day-15",
            content="Outside synthetic",
            priority=1,
            due_date="2026-08-09",
        ),
        TodoistTask(
            id="p1",
            content="P1 synthetic",
            priority=4,
        ),
        TodoistTask(
            id="p2",
            content="P2 synthetic",
            priority=3,
        ),
        TodoistTask(
            id="assigned",
            content="Assigned synthetic",
            priority=1,
            project_id="project-shared",
            responsible_user_id="primary-user-id",
        ),
        TodoistTask(
            id="ordinary",
            content="Ordinary synthetic",
            priority=1,
        ),
        TodoistTask(
            id="assigned-personal",
            content="Personal assignment is not distinguishing",
            priority=1,
            project_id="project-personal",
            responsible_user_id="primary-user-id",
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
    assert [call.cursor for call in transport.task_calls] == [
        None,
        "task-page-2",
    ]
    assert all(call.limit == 200 for call in transport.task_calls)
    assert transport.project_calls == [
        "project-1",
        "project-personal",
        "project-shared",
    ]
    assert transport.section_calls == ["section-1"]
    assert len(transport.label_calls) == 2
    assert connector.last_audit is not None
    assert connector.last_audit.active_task_count == 9
    assert connector.last_audit.selected_task_count == 6
    assert connector.last_audit.labels_retrieved == 2
    assert len(connector.last_audit.labels) == 1
    assert connector.last_audit.pagination_occurred
    assert result.coverage.retrieved_count == 9
    assert result.coverage.selected_count == 6
    assert tuple(
        (resource.resource, resource.retrieved_count)
        for resource in result.coverage.context_resources
    ) == (("projects", 3), ("sections", 1), ("labels", 2))
    assert dict(connector.last_audit.qualification_counts) == {
        "overdue": 1,
        "due_today": 1,
        "due_within_14_days": 1,
        "p1": 1,
        "p2": 1,
        "shared_assignment": 1,
        "explicit_priority_link": 0,
    }


def test_todoist_qualification_counts_preserve_rule_overlaps() -> None:
    transport = _ReadOnlyTransport(
        pages=(
            TodoistTaskPage(
                tasks=(
                    TodoistTask(
                        id="overlap",
                        content="Overlapping qualification",
                        priority=4,
                        due_date="2026-07-25",
                        project_id="project-shared",
                        responsible_user_id="primary-user-id",
                    ),
                )
            ),
        )
    )
    connector = _connector(transport)

    connector.retrieve(_request(connector.approved_scope))

    assert connector.last_audit is not None
    assert dict(connector.last_audit.qualification_counts) == {
        "overdue": 0,
        "due_today": 1,
        "due_within_14_days": 0,
        "p1": 1,
        "p2": 0,
        "shared_assignment": 1,
        "explicit_priority_link": 0,
    }
    assert dict(connector.last_audit.qualification_overlaps) == {
        "due_today+p1+shared_assignment": 1
    }


def test_todoist_explicit_active_priority_link_selects_undated_task() -> None:
    transport = _ReadOnlyTransport(
        pages=(
            TodoistTaskPage(
                tasks=(
                    TodoistTask(
                        id="linked-priority",
                        content="Explicit active priority",
                        priority=1,
                    ),
                )
            ),
        )
    )
    connector = TodoistConnector(
        account_reference="primary-user",
        authorization_provider=_MockAuthorizationProvider(),
        transport=transport,
        relevant_task_ids=frozenset({"linked-priority"}),
        clock=lambda: NOW,
    )

    result = connector.retrieve(_request(connector.approved_scope))

    assert [item.source_record_id for item in result.items] == ["linked-priority"]
    normalized = normalize_item(
        connector.source_name,
        result.items[0],
        timezone="America/New_York",
    )
    assert normalized.explicit_priority_link


def test_todoist_deduplicates_stable_ids_across_cursor_pages() -> None:
    transport = _ReadOnlyTransport(
        pages=(
            TodoistTaskPage(
                tasks=(
                    TodoistTask(
                        id="duplicate",
                        content="First observed version",
                        priority=4,
                    ),
                ),
                next_cursor="page-2",
            ),
            TodoistTaskPage(
                tasks=(
                    TodoistTask(
                        id="duplicate",
                        content="Second observed version",
                        priority=4,
                    ),
                )
            ),
        )
    )
    connector = _connector(transport)

    result = connector.retrieve(_request(connector.approved_scope))

    assert result.coverage.retrieved_count == 1
    assert result.coverage.selected_count == 1
    assert [call.cursor for call in transport.task_calls] == [None, "page-2"]
    assert all(call.limit == 200 for call in transport.task_calls)
    assert connector.last_audit is not None
    assert connector.last_audit.duplicate_task_id_count == 1
    assert connector.last_audit.full_active_task_collection_retrieved
    assert connector.last_audit.concurrent_changes_cannot_be_excluded


def test_todoist_priority_is_source_signal_with_current_api_mapping() -> None:
    transport = _ReadOnlyTransport(
        pages=(
            TodoistTaskPage(
                tasks=(
                    TodoistTask(
                        id="p1",
                        content="P1 synthetic",
                        priority=4,
                        updated_at=datetime(2026, 7, 24, 15, 0, tzinfo=UTC),
                        due_date="2026-07-25",
                    ),
                    TodoistTask(
                        id="p2",
                        content="P2 synthetic",
                        priority=3,
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
    assert p1.provider_priority == 4
    assert p2.provider_priority == 3
    assert p1.explicit_commitment is False
    assert p1.due_at == datetime(
        2026,
        7,
        25,
        0,
        0,
        tzinfo=ZoneInfo("America/New_York"),
    )
    assert result.items[0].facts["provider_priority"] == 4


def test_todoist_rejects_scope_expansion_and_endpoint_changes() -> None:
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
            task_endpoint="/api/v1/tasks/filter",
        )
    except ValueError as error:
        assert "may not be changed" in str(error)
    else:
        raise AssertionError("TodoistConnector accepted another task endpoint")
    assert expanded.task_endpoint == TODOIST_ACTIVE_TASK_ENDPOINT


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
                        priority=4,
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
