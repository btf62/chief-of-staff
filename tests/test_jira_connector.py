"""Synthetic contract and briefing tests for the bounded Jira design."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import UTC, date, datetime

import pytest

import chief_of_staff.connectors.jira as jira_module
from chief_of_staff.auth import (
    JIRA_OAUTH_AUDIENCE,
    JIRA_PROPOSED_READ_SCOPE,
    JiraLiveAccessNotApproved,
    JiraOAuthStateMismatch,
    MockJiraOAuthBoundary,
)
from chief_of_staff.connectors import (
    JIRA_INITIAL_FIELDS,
    ConnectorRequest,
    JiraAuthenticationError,
    JiraAuthorization,
    JiraAuthorizationUnavailable,
    JiraConnector,
    JiraIssue,
    JiraIssueLink,
    JiraIssuePage,
    JiraPermissionError,
    JiraQueryBoundary,
    JiraRateLimitError,
    JiraRetrievalError,
    JiraSearchRequest,
    JiraTransport,
    SourceItem,
    StaticConnector,
)
from chief_of_staff.domain import CoverageStatus
from chief_of_staff.pipeline import (
    BriefingSectionName,
    DeterministicBriefingPipeline,
    normalize_item,
    resolve_context,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
BRIEFING_DATE = date(2026, 7, 27)
ACCOUNT_REFERENCE = "primary-user"
ACCOUNT_IDENTITY = "synthetic-account-id"
SITE_REFERENCE = "approved-site"
PROJECT_KEY = "SYN"


def _request(connector: JiraConnector) -> ConnectorRequest:
    context = resolve_context(
        run_id="jira-connector-test",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )
    return ConnectorRequest(
        run_id=context.run_id,
        briefing_date=context.briefing_date,
        timezone=context.timezone,
        approved_scope=connector.approved_scope,
        window=context.retrieval_window,
    )


@dataclass(frozen=True, slots=True)
class _AuthorizationProvider:
    scopes: frozenset[str] = frozenset({JIRA_PROPOSED_READ_SCOPE})

    def get_jira_authorization(
        self,
        account_reference: str,
        site_reference: str,
    ) -> JiraAuthorization:
        return JiraAuthorization(
            account_reference=account_reference,
            account_identity=ACCOUNT_IDENTITY,
            site_reference=site_reference,
            cloud_resource_reference="synthetic-cloud-resource",
            granted_scopes=self.scopes,
            credential_reference="mocked-jira-credential-reference",
        )


@dataclass(frozen=True, slots=True)
class _UnavailableAuthorizationProvider:
    def get_jira_authorization(
        self,
        account_reference: str,
        site_reference: str,
    ) -> JiraAuthorization:
        del account_reference, site_reference
        raise JiraAuthorizationUnavailable


@dataclass(slots=True)
class _ReadOnlyTransport:
    pages: tuple[JiraIssuePage, ...]
    fail_on_call: int | None = None
    failure: RuntimeError = field(default_factory=JiraRetrievalError)
    calls: list[JiraSearchRequest] = field(default_factory=list, init=False)

    def search_issues(
        self,
        authorization: JiraAuthorization,
        request: JiraSearchRequest,
    ) -> JiraIssuePage:
        assert authorization.credential_reference.startswith("mocked-")
        self.calls.append(request)
        if self.fail_on_call == len(self.calls):
            raise self.failure
        return self.pages[len(self.calls) - 1]


def _issue(
    issue_id: str,
    *,
    key: str | None = None,
    summary: str | None = None,
    project_key: str = PROJECT_KEY,
    status: str = "In Progress",
    status_category: str = "In Progress",
    assignee_account_id: str | None = ACCOUNT_IDENTITY,
    priority_name: str | None = "Medium",
    due_date: date | None = None,
    links: tuple[JiraIssueLink, ...] = (),
    preparation: str | None = None,
    calendar_dependency: bool = False,
    explicit_priority_link: bool = False,
    related_source_ids: tuple[str, ...] = (),
) -> JiraIssue:
    issue_key = key or f"SYN-{issue_id}"
    return JiraIssue(
        id=issue_id,
        key=issue_key,
        summary=summary or f"Synthetic Jira issue {issue_id}",
        project_key=project_key,
        issue_type="Task",
        status=status,
        status_category=status_category,
        display_url=f"https://example.invalid/browse/{issue_key}",
        assignee_account_id=assignee_account_id,
        reporter_account_id=None,
        priority_name=priority_name,
        due_date=due_date,
        created_at=None,
        updated_at=NOW,
        parent_key=None,
        labels=(),
        links=links,
        preparation=preparation,
        calendar_dependency=calendar_dependency,
        explicit_priority_link=explicit_priority_link,
        related_source_ids=related_source_ids,
    )


def _connector(
    transport: _ReadOnlyTransport,
    *,
    authorization_provider: (
        _AuthorizationProvider | _UnavailableAuthorizationProvider | None
    ) = None,
    explicitly_linked_issue_keys: tuple[str, ...] = (),
) -> JiraConnector:
    return JiraConnector(
        account_reference=ACCOUNT_REFERENCE,
        site_reference=SITE_REFERENCE,
        approved_project_keys=(PROJECT_KEY,),
        explicitly_linked_issue_keys=explicitly_linked_issue_keys,
        authorization_provider=(
            _AuthorizationProvider()
            if authorization_provider is None
            else authorization_provider
        ),
        transport=transport,
        clock=lambda: NOW,
    )


def test_mocked_oauth_validates_state_and_rejects_live_exchange() -> None:
    boundary = MockJiraOAuthBoundary(state_factory=lambda: "unguessable-state")
    preview = boundary.prepare_preview()

    assert preview.audience == JIRA_OAUTH_AUDIENCE
    assert preview.requested_scopes == (JIRA_PROPOSED_READ_SCOPE,)
    assert preview.resource_restricted
    assert not preview.live_authorization_enabled
    with pytest.raises(JiraOAuthStateMismatch):
        boundary.validate_mock_callback(returned_state="wrong-state")
    boundary.validate_mock_callback(returned_state="unguessable-state")
    with pytest.raises(JiraOAuthStateMismatch):
        boundary.validate_mock_callback(returned_state="unguessable-state")
    with pytest.raises(JiraLiveAccessNotApproved):
        boundary.exchange_authorization_code()


def test_connector_and_transport_expose_no_mutation_capability() -> None:
    transport = _ReadOnlyTransport(pages=(JiraIssuePage(issues=()),))
    connector = _connector(transport)

    assert isinstance(transport, JiraTransport)
    assert {name for name in vars(JiraTransport) if not name.startswith("_")} == {
        "search_issues"
    }
    for operation in (
        "create_issue",
        "edit_issue",
        "add_comment",
        "transition_issue",
        "assign_issue",
        "add_worklog",
        "delete_issue",
    ):
        assert not hasattr(connector, operation)
        assert not hasattr(transport, operation)


def test_pagination_normalization_and_domain_records_preserve_fields() -> None:
    first = _issue(
        "1001",
        key="SYN-1",
        summary="Prepare synthetic release",
        due_date=BRIEFING_DATE,
        priority_name="Highest",
        links=(
            JiraIssueLink(
                relationship="is blocked by",
                issue_id="1000",
                issue_key="SYN-0",
                display_url="https://example.invalid/browse/SYN-0",
            ),
        ),
        related_source_ids=("todoist:task-1",),
    )
    second = _issue("1002", key="SYN-2", priority_name=None)
    transport = _ReadOnlyTransport(
        pages=(
            JiraIssuePage(issues=(first,), next_page_token="page-2"),
            JiraIssuePage(issues=(second,)),
        )
    )
    connector = _connector(transport)

    result = connector.retrieve(_request(connector))

    assert result.coverage.status is CoverageStatus.COMPLETE
    assert [call.next_page_token for call in transport.calls] == [None, "page-2"]
    assert all(call.fields == JIRA_INITIAL_FIELDS for call in transport.calls)
    assert all(call.max_results == 50 for call in transport.calls)
    assert all(isinstance(call.boundary, JiraQueryBoundary) for call in transport.calls)
    assert result.coverage.retrieved_count == 2
    assert result.coverage.selected_count == 2
    assert result.coverage.persisted_count == 0
    assert connector.last_audit is not None
    assert connector.last_audit.pagination_occurred
    assert connector.last_audit.connector_run.id == "jira-connector-test:jira"
    assert len(connector.last_audit.evidence) == 2

    normalized = normalize_item(
        "jira",
        result.items[0],
        timezone="America/New_York",
    )
    assert normalized.id == "jira:1001"
    assert normalized.provenance.source_record_id == "SYN-1"
    assert normalized.provenance.connector_run_id == "jira-connector-test:jira"
    assert normalized.provenance.display_url is not None
    assert normalized.provenance.display_url.endswith("/SYN-1")
    assert normalized.project_reference == PROJECT_KEY
    assert normalized.issue_type == "Task"
    assert normalized.status_category == "In Progress"
    assert normalized.assignee_reference == ACCOUNT_IDENTITY
    assert normalized.reporter_reference is None
    assert normalized.source_priority == "Highest"
    assert normalized.due_at is not None
    assert normalized.due_at.date() == BRIEFING_DATE
    assert normalized.all_day
    assert normalized.blocked
    assert normalized.source_owned_risk
    assert normalized.dependency_references == ("SYN-0",)
    assert normalized.dependency_relationships == ("is blocked by:SYN-0",)
    assert normalized.dependency_display_urls == (
        "https://example.invalid/browse/SYN-0",
    )
    assert normalized.related_source_ids == ("todoist:task-1",)
    assert normalized.source_updated_at == NOW
    assert normalized.source_created_at is None
    optional = normalize_item(
        "jira",
        result.items[1],
        timezone="America/New_York",
    )
    assert optional.source_priority is None
    assert optional.reporter_reference is None
    assert optional.parent_reference is None
    assert optional.labels == ()
    assert optional.due_at is None


def test_empty_unauthorized_and_scope_mismatch_are_distinct() -> None:
    empty = _connector(_ReadOnlyTransport(pages=(JiraIssuePage(issues=()),)))
    unavailable = _connector(
        _ReadOnlyTransport(pages=(JiraIssuePage(issues=()),)),
        authorization_provider=_UnavailableAuthorizationProvider(),
    )
    mismatch = JiraConnector(
        account_reference=ACCOUNT_REFERENCE,
        site_reference=SITE_REFERENCE,
        approved_project_keys=(PROJECT_KEY,),
        authorization_provider=_AuthorizationProvider(scopes=frozenset()),
        transport=_ReadOnlyTransport(pages=(JiraIssuePage(issues=()),)),
        clock=lambda: NOW,
    )

    empty_result = empty.retrieve(_request(empty))
    unavailable_result = unavailable.retrieve(_request(unavailable))
    mismatch_result = mismatch.retrieve(_request(mismatch))

    assert empty_result.coverage.status is CoverageStatus.COMPLETE
    assert empty_result.coverage.record_count == 0
    assert unavailable_result.coverage.status is CoverageStatus.UNAUTHORIZED
    assert unavailable_result.coverage.error_category == "JiraAuthorizationUnavailable"
    assert mismatch_result.coverage.status is CoverageStatus.UNAUTHORIZED
    assert (
        mismatch_result.coverage.error_category == "JiraAuthorizationBoundaryMismatch"
    )


@pytest.mark.parametrize(
    ("failure", "expected", "status"),
    [
        (
            JiraAuthenticationError(),
            "JiraAuthenticationError",
            CoverageStatus.UNAUTHORIZED,
        ),
        (JiraPermissionError(), "JiraPermissionError", CoverageStatus.UNAVAILABLE),
        (JiraRateLimitError(), "JiraRateLimitError", CoverageStatus.UNAVAILABLE),
    ],
)
def test_first_page_failures_remain_distinct(
    failure: RuntimeError,
    expected: str,
    status: CoverageStatus,
) -> None:
    connector = _connector(
        _ReadOnlyTransport(
            pages=(JiraIssuePage(issues=()),),
            fail_on_call=1,
            failure=failure,
        )
    )

    result = connector.retrieve(_request(connector))

    assert result.coverage.status is status
    assert result.coverage.error_category == expected


def test_partial_page_failure_preserves_completed_page() -> None:
    connector = _connector(
        _ReadOnlyTransport(
            pages=(
                JiraIssuePage(
                    issues=(_issue("1001"),),
                    next_page_token="page-2",
                ),
            ),
            fail_on_call=2,
            failure=JiraRetrievalError(),
        )
    )

    result = connector.retrieve(_request(connector))

    assert result.coverage.status is CoverageStatus.PARTIAL
    assert result.coverage.error_category == "JiraRetrievalError"
    assert result.coverage.record_count == 1
    assert result.coverage.page_count == 1


def test_repeated_pagination_token_is_reported_without_discarding_page() -> None:
    connector = _connector(
        _ReadOnlyTransport(
            pages=(
                JiraIssuePage(
                    issues=(_issue("1001"),),
                    next_page_token="repeat",
                ),
                JiraIssuePage(
                    issues=(_issue("1002"),),
                    next_page_token="repeat",
                ),
            ),
        )
    )

    result = connector.retrieve(_request(connector))

    assert result.coverage.status is CoverageStatus.PARTIAL
    assert result.coverage.error_category == "JiraPaginationError"
    assert result.coverage.record_count == 2
    assert result.coverage.page_count == 2


@pytest.mark.parametrize(
    ("page", "expected"),
    [
        (
            JiraIssuePage(
                issues=(_issue("1001"),),
                permission_denied_project_count=1,
            ),
            "JiraPermissionLimited",
        ),
        (
            JiraIssuePage(
                issues=(_issue("1001"),),
                inaccessible_fields=("assignee",),
            ),
            "JiraFieldAccessLimited",
        ),
    ],
)
def test_permission_and_field_limited_results_are_partial(
    page: JiraIssuePage,
    expected: str,
) -> None:
    connector = _connector(_ReadOnlyTransport(pages=(page,)))

    result = connector.retrieve(_request(connector))

    assert result.coverage.status is CoverageStatus.PARTIAL
    assert result.coverage.error_category == expected
    assert result.coverage.record_count == 1


def test_project_status_and_assignment_boundary_is_enforced() -> None:
    linked = _issue(
        "1002",
        key="SYN-2",
        assignee_account_id=None,
    )
    connector = _connector(
        _ReadOnlyTransport(
            pages=(
                JiraIssuePage(
                    issues=(
                        _issue("1001"),
                        linked,
                        _issue("1003", project_key="OTHER"),
                        _issue("1004", status="Done", status_category="Done"),
                        _issue("1005", assignee_account_id=None),
                    )
                ),
            )
        ),
        explicitly_linked_issue_keys=(linked.key,),
    )

    result = connector.retrieve(_request(connector))

    assert {item.source_record_id for item in result.items} == {"SYN-1001", "SYN-2"}
    assert result.coverage.retrieved_count == 5
    assert result.coverage.selected_count == 2
    assert result.coverage.status is CoverageStatus.PARTIAL


def test_jira_priority_assignment_and_overdue_state_do_not_create_priority() -> None:
    issue = _issue(
        "1001",
        priority_name="Highest",
        due_date=date(2026, 7, 20),
    )
    connector = _connector(_ReadOnlyTransport(pages=(JiraIssuePage(issues=(issue,)),)))

    result = DeterministicBriefingPipeline().run(
        resolve_context(
            run_id="jira-no-automatic-priority",
            briefing_date=BRIEFING_DATE,
            timezone="America/New_York",
        ),
        (connector,),
    )
    audit = result.plan.task_candidate_audits[0]

    assert audit.available_count == 1
    assert audit.candidate_count == 0
    assert audit.excluded_reasons == (
        ("overdue Jira issue without another current signal", 1),
    )
    assert result.plan.coverage[0].displayed_count == 0
    assert "high priority in the source" not in result.rendered.text


def test_blocked_jira_work_is_not_a_people_waiting_or_human_promise_claim() -> None:
    issue = _issue(
        "1001",
        links=(
            JiraIssueLink(
                relationship="blocked by",
                issue_id="999",
                issue_key="SYN-999",
            ),
        ),
    )
    connector = _connector(_ReadOnlyTransport(pages=(JiraIssuePage(issues=(issue,)),)))

    result = DeterministicBriefingPipeline().run(
        resolve_context(
            run_id="jira-risk",
            briefing_date=BRIEFING_DATE,
            timezone="America/New_York",
        ),
        (connector,),
    )
    names = {section.name for section in result.plan.sections}

    assert BriefingSectionName.COMMITMENTS_AT_RISK in names
    assert BriefingSectionName.PEOPLE_WAITING not in names
    assert "not a human-promise claim" in result.rendered.text
    record = result.deduplication.records[0]
    assert not record.explicit_commitment
    assert record.dependency_references == ("SYN-999",)


def test_jira_todoist_association_preserves_conflicting_records_and_links() -> None:
    jira_issue = _issue(
        "1001",
        summary="Shared source-owned work",
        due_date=BRIEFING_DATE,
        related_source_ids=("todoist:todo-1",),
    )
    jira = _connector(_ReadOnlyTransport(pages=(JiraIssuePage(issues=(jira_issue,)),)))
    todoist = StaticConnector(
        source_name="todoist",
        approved_scope="synthetic Todoist",
        status=CoverageStatus.COMPLETE,
        items=(
            SourceItem(
                id="todo-1",
                source_record_id="todo-1",
                item_type="task",
                facts={
                    "title": "Shared source-owned work",
                    "status": "open",
                    "importance": 1,
                    "provider_priority": 1,
                    "all_day": True,
                    "due_at": "2026-07-28T00:00:00-04:00",
                },
                display_url="https://example.invalid/todoist/todo-1",
                retrieved_at=NOW,
                freshness_at=NOW,
            ),
        ),
    )

    result = DeterministicBriefingPipeline().run(
        resolve_context(
            run_id="jira-todoist-association",
            briefing_date=BRIEFING_DATE,
            timezone="America/New_York",
        ),
        (jira, todoist),
    )

    assert len(result.deduplication.records) == 2
    assert len(result.deduplication.associations) == 1
    association = result.deduplication.associations[0]
    assert association.member_ids == ("jira:1001", "todoist:todo-1")
    assert association.basis == "explicit cross-source reference"
    assert association.conflicting_fields == ("status", "due_at")
    assert {
        record.provenance.display_url for record in result.deduplication.records
    } == {
        "https://example.invalid/browse/SYN-1001",
        "https://example.invalid/todoist/todo-1",
    }


def test_synthetic_jira_records_support_bounded_briefing_sections_and_funnel() -> None:
    blocked_link = JiraIssueLink(
        relationship="is blocked by",
        issue_id="9000",
        issue_key="SYN-9000",
    )
    issues = (
        _issue("today", due_date=BRIEFING_DATE),
        _issue(
            "next-1",
            due_date=date(2026, 7, 28),
            preparation="Review the source-owned acceptance evidence.",
            calendar_dependency=True,
            related_source_ids=("synthetic_calendar:meeting",),
        ),
        _issue("next-2", due_date=date(2026, 7, 29), calendar_dependency=True),
        _issue("next-3", due_date=date(2026, 7, 30), calendar_dependency=True),
        _issue("ahead", due_date=date(2026, 7, 31), calendar_dependency=True),
        _issue("risk", links=(blocked_link,)),
        _issue("important", explicit_priority_link=True, priority_name="High"),
    )
    connector = _connector(_ReadOnlyTransport(pages=(JiraIssuePage(issues=issues),)))
    calendar = StaticConnector(
        source_name="synthetic_calendar",
        approved_scope="synthetic Calendar",
        status=CoverageStatus.COMPLETE,
        items=(
            SourceItem(
                id="meeting",
                source_record_id="meeting",
                item_type="calendar_event",
                facts={
                    "title": "Synthetic planning meeting",
                    "status": "confirmed",
                    "start_at": "2026-07-27T13:00:00-04:00",
                    "end_at": "2026-07-27T14:00:00-04:00",
                },
                display_url="https://example.invalid/calendar/meeting",
                retrieved_at=NOW,
                freshness_at=NOW,
            ),
        ),
    )

    result = DeterministicBriefingPipeline().run(
        resolve_context(
            run_id="jira-section-integration",
            briefing_date=BRIEFING_DATE,
            timezone="America/New_York",
        ),
        (calendar, connector),
    )
    names = tuple(section.name for section in result.plan.sections)
    jira_coverage = next(
        report for report in result.plan.coverage if report.source == "jira"
    )
    jira_audit = next(
        audit for audit in result.plan.task_candidate_audits if audit.source == "jira"
    )

    assert BriefingSectionName.TODAYS_OUTCOMES in names
    assert BriefingSectionName.UP_NEXT in names
    assert BriefingSectionName.PREPARATION_NEEDED in names
    assert BriefingSectionName.COMMITMENTS_AT_RISK in names
    assert BriefingSectionName.IMPORTANT_TASKS in names
    assert BriefingSectionName.LOOKING_AHEAD in names
    assert BriefingSectionName.PEOPLE_WAITING not in names
    assert "Review the source-owned acceptance evidence." in result.rendered.text
    assert "SYN-9000" in result.rendered.text
    assert "mocked-jira-credential-reference" not in result.rendered.text
    assert result.rendered.word_count <= 1000
    assert jira_coverage.retrieved_count == 7
    assert jira_coverage.selected_count == 7
    assert jira_coverage.persisted_count == 0
    assert jira_coverage.candidate_count == 7
    assert jira_coverage.displayed_count == 7
    assert jira_audit.available_count == 7
    assert jira_audit.candidate_count == 7
    assert "1 page (no pagination)" in result.rendered.text
    assert result.deduplication.associations[0].member_ids == (
        "jira:next-1",
        "synthetic_calendar:meeting",
    )


def test_initial_jira_models_exclude_broad_or_write_resources() -> None:
    issue_fields = {item.name for item in fields(JiraIssue)}
    excluded = {
        "description",
        "comments",
        "attachments",
        "changelog",
        "worklogs",
        "votes",
        "watches",
    }

    assert issue_fields.isdisjoint(excluded)
    assert set(JIRA_INITIAL_FIELDS).isdisjoint(excluded)
    assert not hasattr(jira_module, "JiraHttpTransport")
    assert not hasattr(jira_module, "StoredJiraAuthorizationProvider")
    assert not hasattr(jira_module, "MacOSKeychain")
    assert not hasattr(jira_module, "OpenAI")
