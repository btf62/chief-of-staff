"""Synthetic tests for the future read-only Asana task contract."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime

from chief_of_staff.connectors import (
    ASANA_PRIMARY_INSTANCE,
    ASANA_TASK_ENDPOINT,
    ASANA_TASK_FIELDS,
    ASANA_TASK_SCOPES,
    AsanaAuthorization,
    AsanaAuthorizationUnavailable,
    AsanaConnector,
    AsanaMembership,
    AsanaRetrievalError,
    AsanaTask,
    AsanaTaskPage,
    AsanaTaskRequest,
    ConnectorRequest,
)
from chief_of_staff.domain import CoverageStatus
from chief_of_staff.pipeline import normalize_item, resolve_context

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
PROJECT_GID = "6000000000000001"


@dataclass(frozen=True, slots=True)
class _AuthorizationProvider:
    def get_asana_authorization(
        self,
        account_reference: str,
    ) -> AsanaAuthorization:
        return AsanaAuthorization(
            account_reference=account_reference,
            project_gid=PROJECT_GID,
            granted_scopes=ASANA_TASK_SCOPES,
            credential_reference="synthetic-keychain-reference",
        )


@dataclass(frozen=True, slots=True)
class _UnavailableAuthorizationProvider:
    def get_asana_authorization(
        self,
        account_reference: str,
    ) -> AsanaAuthorization:
        del account_reference
        raise AsanaAuthorizationUnavailable


@dataclass(slots=True)
class _TaskTransport:
    pages: tuple[AsanaTaskPage, ...]
    fail_on_call: int | None = None
    calls: list[AsanaTaskRequest] = field(default_factory=list)

    def list_tasks(
        self,
        authorization: AsanaAuthorization,
        request: AsanaTaskRequest,
    ) -> AsanaTaskPage:
        assert authorization.credential_reference == "synthetic-keychain-reference"
        self.calls.append(request)
        if self.fail_on_call == len(self.calls):
            raise AsanaRetrievalError("synthetic partial retrieval")
        return self.pages[len(self.calls) - 1]


def _request(connector: AsanaConnector) -> ConnectorRequest:
    context = resolve_context(
        run_id="synthetic-asana",
        briefing_date=date(2026, 7, 27),
        timezone="America/New_York",
    )
    return ConnectorRequest(
        run_id=context.run_id,
        briefing_date=context.briefing_date,
        timezone=context.timezone,
        approved_scope=connector.approved_scope,
        window=context.retrieval_window,
    )


def _task(gid: str = "8000000000000001") -> AsanaTask:
    return AsanaTask(
        gid=gid,
        name="Prepare synthetic launch",
        completed=False,
        assignee_gid="7000000000000001",
        due_on=date(2026, 7, 28),
        start_on=date(2026, 7, 27),
        created_at=NOW,
        modified_at=NOW,
        resource_subtype="default_task",
        parent_gid="8000000000000000",
        memberships=(
            AsanaMembership(
                project_gid="6000000000000001",
                section_gid="5000000000000001",
            ),
        ),
        dependency_gids=("8000000000000002",),
        dependent_gids=("8000000000000003",),
        tags=(("4000000000000001", "Synthetic tag"),),
        permalink_url=f"https://app.asana.com/0/0/{gid}",
    )


def test_synthetic_task_pagination_and_normalization_preserve_approved_facts() -> None:
    transport = _TaskTransport(
        pages=(
            AsanaTaskPage(tasks=(_task(),), next_offset="provider-offset-2"),
            AsanaTaskPage(tasks=(_task("8000000000000004"),)),
        )
    )
    connector = AsanaConnector(
        account_reference="primary-user",
        project_gid=PROJECT_GID,
        authorization_provider=_AuthorizationProvider(),
        transport=transport,
        clock=lambda: NOW,
    )

    result = connector.retrieve(_request(connector))
    normalized = normalize_item(
        "asana",
        result.items[0],
        timezone="America/New_York",
    )

    assert result.coverage.status is CoverageStatus.COMPLETE
    assert result.coverage.page_count == 2
    assert result.coverage.connector_instance_id == ASANA_PRIMARY_INSTANCE
    assert [call.offset for call in transport.calls] == [
        None,
        "provider-offset-2",
    ]
    assert all(call.project_gid == PROJECT_GID for call in transport.calls)
    assert all(call.fields == ASANA_TASK_FIELDS for call in transport.calls)
    assert normalized.provenance.connector_instance_id == ASANA_PRIMARY_INSTANCE
    assert normalized.assignee_reference == "7000000000000001"
    assert normalized.parent_reference == "8000000000000000"
    assert normalized.project_reference == "6000000000000001"
    assert normalized.membership_references == ("6000000000000001:5000000000000001",)
    assert normalized.dependency_references == ("8000000000000002",)
    assert normalized.dependent_references == ("8000000000000003",)
    assert normalized.labels == ("Synthetic tag",)
    assert normalized.due_at is not None
    assert normalized.due_at.date() == date(2026, 7, 28)
    assert normalized.start_at is not None
    assert normalized.start_at.date() == date(2026, 7, 27)
    assert "notes" not in result.items[0].facts


def test_authorization_failure_is_distinct_from_an_empty_task_result() -> None:
    unauthorized = AsanaConnector(
        account_reference="primary-user",
        project_gid=PROJECT_GID,
        authorization_provider=_UnavailableAuthorizationProvider(),
        transport=_TaskTransport(pages=()),
        clock=lambda: NOW,
    )
    empty = AsanaConnector(
        account_reference="primary-user",
        project_gid=PROJECT_GID,
        authorization_provider=_AuthorizationProvider(),
        transport=_TaskTransport(pages=(AsanaTaskPage(tasks=()),)),
        clock=lambda: NOW,
    )

    unauthorized_result = unauthorized.retrieve(_request(unauthorized))
    empty_result = empty.retrieve(_request(empty))

    assert unauthorized_result.coverage.status is CoverageStatus.UNAUTHORIZED
    assert empty_result.coverage.status is CoverageStatus.COMPLETE
    assert empty_result.coverage.record_count == 0


def test_partial_task_retrieval_preserves_successful_pages_and_coverage() -> None:
    transport = _TaskTransport(
        pages=(AsanaTaskPage(tasks=(_task(),), next_offset="provider-offset-2"),),
        fail_on_call=2,
    )
    connector = AsanaConnector(
        account_reference="primary-user",
        project_gid=PROJECT_GID,
        authorization_provider=_AuthorizationProvider(),
        transport=transport,
        clock=lambda: NOW,
    )

    result = connector.retrieve(_request(connector))

    assert result.coverage.status is CoverageStatus.PARTIAL
    assert result.coverage.error_category == "AsanaRetrievalError"
    assert result.coverage.page_count == 1
    assert result.coverage.record_count == 1
    assert result.items[0].source_record_id == "8000000000000001"


def test_task_outside_exact_project_is_omitted() -> None:
    outside = replace(
        _task(),
        memberships=(
            AsanaMembership(
                project_gid="9999999999999999",
                section_gid="5000000000000001",
            ),
        ),
    )
    connector = AsanaConnector(
        account_reference="primary-user",
        project_gid=PROJECT_GID,
        authorization_provider=_AuthorizationProvider(),
        transport=_TaskTransport(pages=(AsanaTaskPage(tasks=(outside,)),)),
        clock=lambda: NOW,
    )

    result = connector.retrieve(_request(connector))

    assert result.coverage.status is CoverageStatus.PARTIAL
    assert result.items == ()
    assert result.coverage.warnings == (
        "Asana task outside the exact approved project was omitted",
    )


def test_task_contract_has_no_live_transport_or_mutation_surface() -> None:
    transport = _TaskTransport(pages=(AsanaTaskPage(tasks=()),))
    connector = AsanaConnector(
        account_reference="primary-user",
        project_gid=PROJECT_GID,
        authorization_provider=_AuthorizationProvider(),
        transport=transport,
    )

    assert ASANA_TASK_ENDPOINT == "GET /api/1.0/projects/{project_gid}/tasks"
    for operation in (
        "create",
        "update",
        "delete",
        "complete",
        "comment",
        "attach",
        "write",
    ):
        assert not hasattr(connector, operation)
        assert not hasattr(transport, operation)
