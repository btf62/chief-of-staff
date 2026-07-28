"""Bounded read-only Jira issue contract for synthetic and approved live use."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Final, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from chief_of_staff.auth.jira_oauth import JIRA_PROPOSED_READ_SCOPE
from chief_of_staff.connectors.contracts import (
    ConnectorRequest,
    ConnectorResult,
    SourceCoverage,
    SourceItem,
)
from chief_of_staff.connectors.instances import JIRA_PRIMARY_INSTANCE
from chief_of_staff.domain import (
    ConnectorRun,
    ConnectorStatus,
    CoverageStatus,
    SourceEvidence,
)

JIRA_ENHANCED_SEARCH_OPERATION: Final = "POST /rest/api/3/search/jql"
JIRA_PAGE_LIMIT: Final = 50
JIRA_DEFAULT_MAX_PAGES: Final = 20
JIRA_APPROVED_PROJECT_KEY: Final = "NRC"
JIRA_APPROVED_JQL: Final = (
    "project = NRC\n"
    "AND statusCategory != Done\n"
    "AND assignee = currentUser()\n"
    "ORDER BY updated DESC, key ASC"
)
JIRA_INITIAL_FIELDS: Final = (
    "summary",
    "project",
    "issuetype",
    "status",
    "assignee",
    "priority",
    "duedate",
    "created",
    "updated",
    "parent",
    "labels",
    "issuelinks",
)


class JiraAuthorizationUnavailable(RuntimeError):
    """Raised when no approved Jira grant exists."""


class JiraAuthenticationError(RuntimeError):
    """Raised when Jira rejects otherwise present authorization."""


class JiraRetrievalError(RuntimeError):
    """Expected provider retrieval failure without response content."""


class JiraPermissionError(JiraRetrievalError):
    """Raised when the approved account cannot search the bounded projects."""


class JiraRateLimitError(JiraRetrievalError):
    """Raised when Jira rate-limits the bounded retrieval."""


class JiraInvalidJqlError(JiraRetrievalError):
    """Raised when Jira rejects the exact approved JQL."""


@dataclass(frozen=True, slots=True)
class JiraAuthorization:
    """Non-secret mocked authorization metadata supplied to a transport."""

    account_reference: str
    account_identity: str
    site_reference: str
    cloud_resource_reference: str
    granted_scopes: frozenset[str]
    credential_reference: str
    current_user_assignment_prevalidated: bool = False


@dataclass(frozen=True, slots=True)
class JiraQueryBoundary:
    """Structured boundary that intentionally contains no executable JQL."""

    approved_project_keys: tuple[str, ...]
    assigned_to_current_user: bool = True
    unresolved_only: bool = True
    explicitly_linked_issue_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JiraSearchRequest:
    """Stable read-only search parameters for one synthetic transport call."""

    boundary: JiraQueryBoundary
    fields: tuple[str, ...]
    next_page_token: str | None = field(repr=False)
    max_results: int = JIRA_PAGE_LIMIT


@dataclass(frozen=True, slots=True)
class JiraIssueLink:
    """One preserved Jira issue relationship."""

    relationship: str
    issue_id: str
    issue_key: str
    display_url: str | None = None


@dataclass(frozen=True, slots=True)
class JiraIssue:
    """Provider facts permitted by the proposed initial Jira boundary."""

    id: str
    key: str
    summary: str
    project_key: str
    issue_type: str
    status: str
    status_category: str
    display_url: str
    assignee_account_id: str | None = None
    priority_name: str | None = None
    due_date: date | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    parent_key: str | None = None
    labels: tuple[str, ...] = ()
    links: tuple[JiraIssueLink, ...] = ()
    preparation: str | None = None
    calendar_dependency: bool = False
    explicit_priority_link: bool = False
    related_source_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JiraIssuePage:
    """One synthetic Jira search page plus safe coverage limitations."""

    issues: tuple[JiraIssue, ...]
    next_page_token: str | None = field(default=None, repr=False)
    permission_denied_project_count: int = 0
    inaccessible_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JiraRetrievalAudit:
    """Inspectable synthetic lifecycle without descriptions or credentials."""

    connector_run: ConnectorRun
    evidence: tuple[SourceEvidence, ...]
    retrieved_count: int
    selected_count: int
    page_count: int
    duplicate_issue_count: int
    retrieved_issues: tuple[JiraIssue, ...] = field(repr=False)
    selected_issues: tuple[JiraIssue, ...] = field(repr=False)

    @property
    def pagination_occurred(self) -> bool:
        return self.page_count > 1


@runtime_checkable
class JiraAuthorizationProvider(Protocol):
    """Mocked boundary returning only non-secret approved-grant metadata."""

    def get_jira_authorization(
        self,
        account_reference: str,
        site_reference: str,
    ) -> JiraAuthorization:
        """Return mocked metadata or raise authorization unavailable."""


@runtime_checkable
class JiraTransport(Protocol):
    """The only provider-shaped operation reachable by this connector."""

    def search_issues(
        self,
        authorization: JiraAuthorization,
        request: JiraSearchRequest,
    ) -> JiraIssuePage:
        """Return one bounded read-only issue page."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class JiraConnector:
    """Retrieve synthetic Jira issues through a non-live read-only contract."""

    account_reference: str
    site_reference: str
    approved_project_keys: tuple[str, ...]
    authorization_provider: JiraAuthorizationProvider
    transport: JiraTransport
    explicitly_linked_issue_keys: tuple[str, ...] = ()
    fields: tuple[str, ...] = JIRA_INITIAL_FIELDS
    max_pages: int = JIRA_DEFAULT_MAX_PAGES
    clock: Callable[[], datetime] = field(
        default=_utc_now,
        repr=False,
        compare=False,
    )
    source_name: str = field(default="jira", init=False)
    approved_scope: str = field(init=False)
    last_audit: JiraRetrievalAudit | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_alias(self.account_reference, "account")
        _validate_alias(self.site_reference, "site")
        if not self.approved_project_keys or any(
            not key.strip() for key in self.approved_project_keys
        ):
            raise ValueError("at least one synthetic Jira project key is required")
        if self.fields != JIRA_INITIAL_FIELDS:
            raise ValueError("Jira initial fields may not be broadened")
        if self.max_pages < 1:
            raise ValueError("Jira max_pages must be positive")
        self.approved_scope = (
            f"Jira account={self.account_reference}; "
            f"site={self.site_reference}; projects="
            f"{','.join(self.approved_project_keys)}; "
            f"operation={JIRA_ENHANCED_SEARCH_OPERATION}; read-only"
        )

    def retrieve(self, request: ConnectorRequest) -> ConnectorResult:
        """Retrieve synthetic issues while preserving bounded failure semantics."""

        self.last_audit = None
        if request.approved_scope != self.approved_scope:
            raise ValueError("request scope does not match connector scope")
        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("connector clock must return a timezone-aware value")
        connector_run_id = f"{request.run_id}:jira"

        try:
            authorization = self.authorization_provider.get_jira_authorization(
                self.account_reference,
                self.site_reference,
            )
        except JiraAuthorizationUnavailable:
            return self._coverage_result(
                retrieved_at=retrieved_at,
                status=CoverageStatus.UNAUTHORIZED,
                error_category="JiraAuthorizationUnavailable",
                page_count=0,
            )
        if not self._authorization_matches(authorization):
            return self._coverage_result(
                retrieved_at=retrieved_at,
                status=CoverageStatus.UNAUTHORIZED,
                error_category="JiraAuthorizationBoundaryMismatch",
                page_count=0,
            )

        issues, page_count, duplicate_count, warnings, error_category = (
            self._retrieve_pages(authorization)
        )
        selected = tuple(
            issue
            for issue in issues
            if self._issue_is_selected(
                issue,
                account_identity=authorization.account_identity,
                current_user_assignment_prevalidated=(
                    authorization.current_user_assignment_prevalidated
                ),
            )
        )
        omitted_count = len(issues) - len(selected)
        if omitted_count:
            warnings.append(
                f"{omitted_count} Jira issues fell outside the approved boundary"
            )

        items: list[SourceItem] = []
        usable_issues: list[JiraIssue] = []
        for issue in selected:
            try:
                items.append(
                    _issue_to_source_item(
                        issue,
                        request=request,
                        connector_run_id=connector_run_id,
                        retrieved_at=retrieved_at,
                    )
                )
                usable_issues.append(issue)
            except ValueError:
                warnings.append("one selected Jira issue was invalid and omitted")
                error_category = error_category or "JiraFieldValidationError"

        if error_category is not None and not items:
            status = (
                CoverageStatus.UNAUTHORIZED
                if error_category == "JiraAuthenticationError"
                else CoverageStatus.UNAVAILABLE
            )
        elif warnings or error_category is not None:
            status = CoverageStatus.PARTIAL
        else:
            status = CoverageStatus.COMPLETE

        evidence = tuple(
            _source_evidence(
                item,
                connector_run_id=connector_run_id,
            )
            for item in items
        )
        completed_at = self.clock()
        connector_run = ConnectorRun(
            id=connector_run_id,
            source=self.source_name,
            approved_scope=self.approved_scope,
            started_at=retrieved_at,
            completed_at=completed_at,
            status=(
                ConnectorStatus.SUCCEEDED
                if status is CoverageStatus.COMPLETE
                else (ConnectorStatus.PARTIAL if items else ConnectorStatus.FAILED)
            ),
            coverage_status=status,
            retrieval_window_start=request.window.starts_at,
            retrieval_window_end=request.window.ends_at,
            freshness_at=max(
                (item.freshness_at for item in items if item.freshness_at is not None),
                default=None,
            ),
            error_category=error_category,
            page_count=page_count,
            connector_instance_id=JIRA_PRIMARY_INSTANCE,
        )
        self.last_audit = JiraRetrievalAudit(
            connector_run=connector_run,
            evidence=evidence,
            retrieved_count=len(issues),
            selected_count=len(items),
            page_count=page_count,
            duplicate_issue_count=duplicate_count,
            retrieved_issues=issues,
            selected_issues=tuple(usable_issues),
        )
        return self._coverage_result(
            retrieved_at=retrieved_at,
            status=status,
            items=tuple(items),
            warnings=tuple(warnings),
            error_category=error_category,
            page_count=page_count,
            retrieved_count=len(issues),
            selected_count=len(items),
        )

    def _authorization_matches(self, authorization: JiraAuthorization) -> bool:
        return (
            authorization.account_reference == self.account_reference
            and authorization.site_reference == self.site_reference
            and authorization.granted_scopes == frozenset({JIRA_PROPOSED_READ_SCOPE})
        )

    def _retrieve_pages(
        self,
        authorization: JiraAuthorization,
    ) -> tuple[
        tuple[JiraIssue, ...],
        int,
        int,
        list[str],
        str | None,
    ]:
        issues: dict[str, JiraIssue] = {}
        duplicate_count = 0
        warnings: list[str] = []
        next_page_token: str | None = None
        seen_tokens: set[str] = set()
        page_count = 0
        error_category: str | None = None
        boundary = JiraQueryBoundary(
            approved_project_keys=self.approved_project_keys,
            explicitly_linked_issue_keys=self.explicitly_linked_issue_keys,
        )
        while page_count < self.max_pages:
            try:
                page = self.transport.search_issues(
                    authorization,
                    JiraSearchRequest(
                        boundary=boundary,
                        fields=self.fields,
                        next_page_token=next_page_token,
                    ),
                )
            except (
                JiraAuthenticationError,
                JiraPermissionError,
                JiraRateLimitError,
                JiraInvalidJqlError,
                JiraRetrievalError,
            ) as error:
                error_category = type(error).__name__
                warnings.append(
                    "Jira issue retrieval stopped before the next complete page"
                )
                break
            page_count += 1
            for issue in page.issues:
                existing = issues.get(issue.id)
                if existing is not None:
                    duplicate_count += 1
                    if _issue_order_key(existing) <= _issue_order_key(issue):
                        continue
                issues[issue.id] = issue
            if page.permission_denied_project_count:
                warnings.append(
                    f"{page.permission_denied_project_count} approved Jira "
                    "projects were permission-limited"
                )
                error_category = error_category or "JiraPermissionLimited"
            if page.inaccessible_fields:
                warnings.append(
                    f"{len(page.inaccessible_fields)} requested Jira fields "
                    "were inaccessible"
                )
                error_category = error_category or "JiraFieldAccessLimited"
            if page.next_page_token is None:
                break
            if not page.next_page_token or page.next_page_token in seen_tokens:
                warnings.append(
                    "Jira pagination returned an invalid continuation token"
                )
                error_category = "JiraPaginationError"
                break
            seen_tokens.add(page.next_page_token)
            next_page_token = page.next_page_token
        else:
            warnings.append(f"Jira retrieval reached the {self.max_pages}-page limit")
            error_category = "JiraPageLimit"
        return (
            tuple(sorted(issues.values(), key=_issue_order_key)),
            page_count,
            duplicate_count,
            warnings,
            error_category,
        )

    def _issue_is_selected(
        self,
        issue: JiraIssue,
        *,
        account_identity: str,
        current_user_assignment_prevalidated: bool,
    ) -> bool:
        if issue.project_key not in self.approved_project_keys:
            return False
        if issue.status_category.casefold() == "done":
            return False
        assigned_to_current_user = issue.assignee_account_id is not None and (
            issue.assignee_account_id == account_identity
            or current_user_assignment_prevalidated
        )
        return (
            assigned_to_current_user or issue.key in self.explicitly_linked_issue_keys
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
                persisted_count=0,
                connector_instance_id=JIRA_PRIMARY_INSTANCE,
            ),
        )


def _validate_alias(value: str, kind: str) -> None:
    if (
        not value.strip()
        or "@" in value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"Jira {kind} reference must be an opaque alias")


def _issue_to_source_item(
    issue: JiraIssue,
    *,
    request: ConnectorRequest,
    connector_run_id: str,
    retrieved_at: datetime,
) -> SourceItem:
    required = (
        issue.id,
        issue.key,
        issue.summary,
        issue.project_key,
        issue.issue_type,
        issue.status,
        issue.status_category,
        issue.display_url,
    )
    if any(not value.strip() for value in required):
        raise ValueError("required Jira issue fields must not be empty")
    _validate_optional_aware(issue.created_at)
    _validate_optional_aware(issue.updated_at)
    zone = ZoneInfo(request.timezone)
    due_at = (
        None
        if issue.due_date is None
        else datetime.combine(issue.due_date, time.min, tzinfo=zone).isoformat()
    )
    dependency_references = tuple(link.issue_key for link in issue.links)
    dependency_relationships = tuple(
        f"{link.relationship}:{link.issue_key}" for link in issue.links
    )
    dependency_display_urls = tuple(
        link.display_url for link in issue.links if link.display_url is not None
    )
    blocked = any(
        link.relationship.casefold() in {"blocked by", "is blocked by"}
        for link in issue.links
    )
    priority_importance = {
        "lowest": 1,
        "low": 2,
        "medium": 3,
        "high": 4,
        "highest": 5,
    }.get((issue.priority_name or "").casefold(), 0)
    facts: dict[str, str | int | bool | tuple[str, ...] | None] = {
        "title": issue.summary.strip(),
        "summary": f"{issue.project_key} · {issue.issue_type}",
        "status": issue.status,
        "importance": priority_importance,
        "source_priority": issue.priority_name,
        "project_reference": issue.project_key,
        "issue_type": issue.issue_type,
        "status_category": issue.status_category,
        "assignee_reference": issue.assignee_account_id,
        "parent_reference": issue.parent_key,
        "labels": issue.labels,
        "dependency_references": dependency_references,
        "dependency_relationships": dependency_relationships,
        "dependency_display_urls": dependency_display_urls,
        "related_source_ids": issue.related_source_ids,
        "blocked": blocked,
        "source_owned_risk": blocked,
        "explicit_commitment": False,
        "preparation": issue.preparation,
        "calendar_dependency": issue.calendar_dependency,
        "explicit_priority_link": issue.explicit_priority_link,
        "all_day": issue.due_date is not None,
        "due_at": due_at,
        "source_created_at": (
            None if issue.created_at is None else issue.created_at.isoformat()
        ),
        "source_updated_at": (
            None if issue.updated_at is None else issue.updated_at.isoformat()
        ),
    }
    return SourceItem(
        id=issue.id,
        source_record_id=issue.key,
        item_type="task",
        facts=facts,
        retrieved_at=retrieved_at,
        freshness_at=issue.updated_at or issue.created_at,
        display_url=issue.display_url,
        connector_run_id=connector_run_id,
        connector_instance_id=JIRA_PRIMARY_INSTANCE,
    )


def _source_evidence(
    item: SourceItem,
    *,
    connector_run_id: str,
) -> SourceEvidence:
    fingerprint = hashlib.sha256(
        (
            f"jira:{item.source_record_id}:"
            f"{item.freshness_at.isoformat() if item.freshness_at else 'unknown'}"
        ).encode()
    ).hexdigest()
    title = item.facts.get("title")
    return SourceEvidence(
        id=f"{connector_run_id}:{item.source_record_id}",
        connector_run_id=connector_run_id,
        source="jira",
        source_record_id=item.source_record_id,
        display_url=item.display_url,
        excerpt=title if isinstance(title, str) else None,
        evidence_fingerprint=fingerprint,
        retrieved_at=item.retrieved_at,
        freshness_at=item.freshness_at,
        connector_instance_id=JIRA_PRIMARY_INSTANCE,
    )


def _validate_optional_aware(value: datetime | None) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("Jira timestamps must be timezone-aware")


def _issue_order_key(issue: JiraIssue) -> tuple[float, str, str]:
    """Preserve the approved updated-descending, key-ascending order."""

    updated_timestamp = (
        issue.updated_at.timestamp() if issue.updated_at is not None else float("-inf")
    )
    return (-updated_timestamp, issue.key.casefold(), issue.id)
