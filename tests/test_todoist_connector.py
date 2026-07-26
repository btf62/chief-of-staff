"""Synthetic contract tests for the proposed Todoist connector."""

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
    TodoistRetrievalError,
    TodoistTask,
    TodoistTaskPage,
)
from chief_of_staff.domain import CoverageStatus
from chief_of_staff.pipeline import normalize_item, resolve_context

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
BRIEFING_DATE = date(2026, 7, 25)


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

    def get_todoist_authorization(
        self,
        account_reference: str,
    ) -> TodoistAuthorization:
        return TodoistAuthorization(
            account_reference=account_reference,
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
class _PagedTransport:
    pages: tuple[TodoistTaskPage, ...]
    fail_on_call: int | None = field(default=None, kw_only=True)
    calls: list[TodoistFilterRequest] = field(default_factory=list, init=False)

    def filter_tasks(
        self,
        authorization: TodoistAuthorization,
        request: TodoistFilterRequest,
    ) -> TodoistTaskPage:
        assert authorization.credential_reference == "mock-todoist-grant"
        self.calls.append(request)
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise TodoistRetrievalError
        index = 0 if request.cursor is None else 1
        return self.pages[index]


def _pages() -> tuple[TodoistTaskPage, ...]:
    return (
        TodoistTaskPage(
            tasks=(
                TodoistTask(
                    id="task-1",
                    content="Review synthetic proposal",
                    priority=4,
                    updated_at=datetime(2026, 7, 24, 15, 0, tzinfo=UTC),
                    due_date="2026-07-25",
                ),
            ),
            next_cursor="synthetic-page-2",
        ),
        TodoistTaskPage(
            tasks=(
                TodoistTask(
                    id="task-2",
                    content="Prepare synthetic agenda",
                    priority=2,
                    due_datetime="2026-07-27T09:00:00-04:00",
                ),
            ),
        ),
    )


def _connector(
    transport: _PagedTransport,
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


def test_todoist_uses_fixed_filter_paginates_and_normalizes_tasks() -> None:
    transport = _PagedTransport(_pages())
    connector = _connector(transport)

    result = connector.retrieve(_request(connector.approved_scope))

    assert result.coverage.status is CoverageStatus.COMPLETE
    assert result.coverage.record_count == 2
    assert [call.query for call in transport.calls] == [
        TODOIST_FILTER_QUERY,
        TODOIST_FILTER_QUERY,
    ]
    assert [call.cursor for call in transport.calls] == [
        None,
        "synthetic-page-2",
    ]
    assert all(call.limit == 200 for call in transport.calls)
    date_only = normalize_item(
        connector.source_name,
        result.items[0],
        timezone="America/New_York",
    )
    assert date_only.due_at == datetime(
        2026,
        7,
        25,
        0,
        0,
        tzinfo=ZoneInfo("America/New_York"),
    )
    assert date_only.all_day is True
    assert date_only.importance == 5
    assert result.items[0].display_url == ("https://app.todoist.com/app/task/task-1")


def test_todoist_rejects_scope_expansion_and_filter_broadening() -> None:
    transport = _PagedTransport((TodoistTaskPage(tasks=()),))
    expanded = _connector(
        transport,
        authorization_provider=_MockAuthorizationProvider(
            scopes=frozenset({TODOIST_DATA_READ_SCOPE, "data:read_write"})
        ),
    )

    result = expanded.retrieve(_request(expanded.approved_scope))

    assert result.coverage.status is CoverageStatus.UNAUTHORIZED
    assert result.coverage.error_category == "TodoistAuthorizationScopeMismatch"
    assert transport.calls == []

    try:
        TodoistConnector(
            account_reference="primary-user",
            authorization_provider=_MockAuthorizationProvider(),
            transport=transport,
            filter_query="all",
        )
    except ValueError as error:
        assert "may not be broadened" in str(error)
    else:
        raise AssertionError("TodoistConnector accepted a broader task filter")


def test_todoist_distinguishes_unauthorized_from_empty() -> None:
    pages = (TodoistTaskPage(tasks=()),)
    unauthorized_transport = _PagedTransport(pages)
    unauthorized = _connector(
        unauthorized_transport,
        authorization_provider=_UnavailableAuthorizationProvider(),
    )
    empty_transport = _PagedTransport(pages)
    empty = _connector(empty_transport)

    unauthorized_result = unauthorized.retrieve(_request(unauthorized.approved_scope))
    empty_result = empty.retrieve(_request(empty.approved_scope))

    assert unauthorized_result.coverage.status is CoverageStatus.UNAUTHORIZED
    assert unauthorized_result.coverage.error_category == (
        "TodoistAuthorizationUnavailable"
    )
    assert unauthorized_transport.calls == []
    assert empty_result.coverage.status is CoverageStatus.COMPLETE
    assert empty_result.coverage.record_count == 0


def test_todoist_retains_first_page_during_partial_failure() -> None:
    connector = _connector(_PagedTransport(_pages(), fail_on_call=2))

    result = connector.retrieve(_request(connector.approved_scope))

    assert result.coverage.status is CoverageStatus.PARTIAL
    assert result.coverage.record_count == 1
    assert result.coverage.error_category == "TodoistRetrievalError"
    assert "stopped before page 2" in result.coverage.warnings[0]


def test_todoist_omits_invalid_tasks_and_discloses_partial_coverage() -> None:
    page = TodoistTaskPage(
        tasks=(
            TodoistTask(
                id="",
                content="Invalid synthetic task",
                priority=1,
            ),
        )
    )
    connector = _connector(_PagedTransport((page,)))

    result = connector.retrieve(_request(connector.approved_scope))

    assert result.coverage.status is CoverageStatus.PARTIAL
    assert result.coverage.record_count == 0
    assert result.coverage.error_category == "TodoistTaskValidationError"


def test_todoist_contract_exposes_no_mutation_operations() -> None:
    connector = _connector(_PagedTransport((TodoistTaskPage(tasks=()),)))

    for boundary in (connector, connector.transport):
        for operation in (
            "add",
            "close",
            "create",
            "delete",
            "move",
            "reopen",
            "update",
            "write",
        ):
            assert not hasattr(boundary, operation)
