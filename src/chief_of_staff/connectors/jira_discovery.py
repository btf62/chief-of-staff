"""Bounded live Jira site and project discovery without issue access."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Protocol, cast

from chief_of_staff.auth.jira_oauth import (
    JIRA_CONNECTOR,
    JIRA_GRANT_TYPE,
    JIRA_PROPOSED_READ_SCOPE,
)
from chief_of_staff.auth.keychain import (
    KeychainSecretNotFound,
    KeychainSecretReference,
    MacOSKeychain,
)
from chief_of_staff.connectors.instances import JIRA_PRIMARY_INSTANCE
from chief_of_staff.domain import (
    AuthorizationStatus,
    ConnectorRun,
    ConnectorStatus,
    CoverageStatus,
    CredentialHealth,
    SourceEvidence,
)
from chief_of_staff.persistence import StateStore

JIRA_PROJECT_SEARCH_OPERATION: Final = "GET /rest/api/3/project/search"
JIRA_PROJECT_PAGE_SIZE: Final = 50
JIRA_PROJECT_MAX_PAGES: Final = 20
JIRA_API_ROOT: Final = "https://api.atlassian.com/ex/jira"
MAX_JIRA_PROJECT_RESPONSE_BYTES: Final = 4 * 1024 * 1024
JIRA_PROPOSED_ISSUE_FIELDS: Final = (
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
JIRA_EXCLUDED_ISSUE_FIELDS: Final = (
    "description",
    "reporter",
    "comments",
    "attachments",
    "changelog",
    "worklogs",
    "votes",
    "watches",
    "rendered fields",
)


class JiraProjectDiscoveryError(RuntimeError):
    """Base class for bounded project-discovery failures."""


class JiraDiscoveryAuthorizationUnavailable(JiraProjectDiscoveryError):
    """Raised when exact-scope authorization metadata is unavailable."""


class JiraDiscoveryAuthenticationError(JiraProjectDiscoveryError):
    """Raised when Jira rejects an otherwise present access token."""


class JiraSiteBoundaryError(JiraProjectDiscoveryError):
    """Raised before any request can target an unselected site."""


class JiraProjectPermissionError(JiraProjectDiscoveryError):
    """Raised when the selected account cannot browse the project catalog."""


class JiraProjectRateLimitError(JiraProjectDiscoveryError):
    """Raised when Jira rate-limits project discovery."""


class JiraProjectRetrievalError(JiraProjectDiscoveryError):
    """Raised for a bounded provider or response failure."""


class JiraProjectPageLimitError(JiraProjectDiscoveryError):
    """Raised when the approved pagination ceiling is reached."""


class JiraPartialPaginationError(JiraProjectDiscoveryError):
    """Preserve completed-page facts while distinguishing incomplete coverage."""

    def __init__(
        self,
        *,
        completed_projects: tuple[JiraProject, ...],
        page_count: int,
        cause_category: str,
    ) -> None:
        super().__init__("Jira project pagination failed after completed pages")
        self.completed_projects = completed_projects
        self.page_count = page_count
        self.cause_category = cause_category


@dataclass(frozen=True, slots=True)
class JiraDiscoveryAuthorization:
    """Non-secret exact-site authorization plus one Keychain reference."""

    account_reference: str
    account_identity: str
    cloud_id: str
    site_url: str
    granted_scope: str
    grant_type: str
    credential_reference: str


@dataclass(frozen=True, slots=True)
class JiraProject:
    """Only project facts permitted in the private discovery report."""

    id: str
    key: str
    name: str
    project_type: str
    archived: bool | None
    browse_available: bool = True


@dataclass(frozen=True, slots=True)
class JiraProjectPageRequest:
    """One fixed current-project-search page request."""

    start_at: int = 0
    max_results: int = JIRA_PROJECT_PAGE_SIZE
    action: str = "browse"
    order_by: str = "key"


@dataclass(frozen=True, slots=True)
class JiraProjectPage:
    """One minimized provider page."""

    projects: tuple[JiraProject, ...]
    start_at: int
    max_results: int
    is_last: bool
    total: int | None


@dataclass(frozen=True, slots=True)
class JiraProjectDiscovery:
    """Complete in-memory catalog, hidden from ordinary representation."""

    projects: tuple[JiraProject, ...] = field(repr=False)
    page_count: int
    duplicate_project_count: int

    @property
    def pagination_occurred(self) -> bool:
        return self.page_count > 1


@dataclass(frozen=True, slots=True)
class JiraProjectDiscoveryReport:
    """Privacy-safe trial facts suitable for the mandatory stop report."""

    application_name: str
    application_owner: str
    account_identity: str
    account_identity_source: str
    granted_scope: str
    grant_type: str
    site_url: str
    cloud_id: str
    accessible_site_count: int
    project_count: int
    project_page_count: int
    duplicate_project_count: int
    output_path: Path
    credential_health: str
    connector_run_id: str
    raw_payload_persisted: bool = False
    project_catalog_persisted: bool = False
    issue_endpoint_called: bool = False
    refresh_token_requested: bool = False

    @property
    def pagination_occurred(self) -> bool:
        return self.project_page_count > 1


class JiraProjectHttpResponse(Protocol):
    """Minimal response surface for injectable contract tests."""

    def read(self, amount: int = -1) -> bytes:
        """Read a bounded response body."""

    def __enter__(self) -> JiraProjectHttpResponse:
        """Enter the response context."""

    def __exit__(self, *args: object) -> None:
        """Close the response context."""


class JiraProjectUrlOpener(Protocol):
    """Injectable HTTPS opener."""

    def __call__(
        self,
        request: urllib.request.Request,
        *,
        timeout: int,
    ) -> JiraProjectHttpResponse:
        """Open one fixed GET request."""


def _open_url(
    request: urllib.request.Request,
    *,
    timeout: int,
) -> JiraProjectHttpResponse:
    return cast(
        JiraProjectHttpResponse,
        urllib.request.urlopen(  # noqa: S310 - fixed HTTPS API root
            request,
            timeout=timeout,
        ),
    )


@dataclass(frozen=True, slots=True)
class StoredJiraDiscoveryAuthorizationProvider:
    """Resolve one exact-scope, exact-resource stored grant."""

    state_store: StateStore
    keychain: MacOSKeychain
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def get_authorization(
        self,
        *,
        account_reference: str,
        resource_reference: str,
    ) -> JiraDiscoveryAuthorization:
        metadata = self.state_store.get_connector_authorization(JIRA_CONNECTOR)
        resource = self.state_store.get_connector_resource(JIRA_CONNECTOR)
        if (
            metadata is None
            or resource is None
            or metadata.account_reference != account_reference
            or resource.resource_reference != resource_reference
            or metadata.granted_scope != JIRA_PROPOSED_READ_SCOPE
            or resource.grant_type != JIRA_GRANT_TYPE
            or resource.resource_type != "jira_cloud_site"
            or metadata.authorization_status is not AuthorizationStatus.AUTHORIZED
            or metadata.credential_health is not CredentialHealth.HEALTHY
            or metadata.token_expires_at <= self.clock()
            or metadata.refresh_token_account is not None
        ):
            raise JiraDiscoveryAuthorizationUnavailable
        reference = KeychainSecretReference(
            service=metadata.credential_service,
            account=metadata.access_token_account,
        )
        if not self.keychain.exists(reference):
            raise JiraDiscoveryAuthorizationUnavailable
        return JiraDiscoveryAuthorization(
            account_reference=metadata.account_reference,
            account_identity=metadata.account_identity,
            cloud_id=resource.resource_id,
            site_url=resource.resource_url,
            granted_scope=metadata.granted_scope,
            grant_type=resource.grant_type,
            credential_reference=reference.identifier,
        )


@dataclass(frozen=True, slots=True)
class JiraProjectDiscoveryHttpTransport:
    """Call only the current paginated project-search endpoint."""

    keychain: MacOSKeychain
    access_token_reference: KeychainSecretReference
    approved_cloud_id: str
    url_opener: JiraProjectUrlOpener = field(
        default=_open_url,
        repr=False,
        compare=False,
    )

    def list_projects(
        self,
        authorization: JiraDiscoveryAuthorization,
        request: JiraProjectPageRequest,
    ) -> JiraProjectPage:
        """Return one minimized browse-filtered project page."""

        if authorization.cloud_id != self.approved_cloud_id:
            raise JiraSiteBoundaryError("unselected Jira site rejected")
        if (
            authorization.credential_reference != self.access_token_reference.identifier
            or authorization.granted_scope != JIRA_PROPOSED_READ_SCOPE
            or authorization.grant_type != JIRA_GRANT_TYPE
        ):
            raise JiraDiscoveryAuthenticationError
        if (
            request.start_at < 0
            or request.max_results != JIRA_PROJECT_PAGE_SIZE
            or request.action != "browse"
            or request.order_by != "key"
        ):
            raise JiraProjectRetrievalError("project-search boundary mismatch")
        try:
            access_token = self.keychain.read(self.access_token_reference)
        except KeychainSecretNotFound:
            raise JiraDiscoveryAuthenticationError from None
        query = urllib.parse.urlencode(
            {
                "startAt": str(request.start_at),
                "maxResults": str(request.max_results),
                "orderBy": request.order_by,
                "action": request.action,
            }
        )
        request_url = (
            f"{JIRA_API_ROOT}/{urllib.parse.quote(self.approved_cloud_id, safe='')}"
            f"/rest/api/3/project/search?{query}"
        )
        http_request = urllib.request.Request(  # noqa: S310 - validated API root
            request_url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
            method="GET",
        )
        raw_response = bytearray()
        try:
            with self.url_opener(http_request, timeout=30) as response:
                raw_response = bytearray(
                    response.read(MAX_JIRA_PROJECT_RESPONSE_BYTES + 1)
                )
        except urllib.error.HTTPError as error:
            if error.code == 401:
                raise JiraDiscoveryAuthenticationError from None
            if error.code == 403:
                raise JiraProjectPermissionError from None
            if error.code == 429:
                raise JiraProjectRateLimitError from None
            raise JiraProjectRetrievalError from None
        except urllib.error.URLError, TimeoutError:
            raise JiraProjectRetrievalError from None
        finally:
            access_token = ""
        try:
            if len(raw_response) > MAX_JIRA_PROJECT_RESPONSE_BYTES:
                raise JiraProjectRetrievalError("project response exceeded its limit")
            payload = json.loads(raw_response)
        except json.JSONDecodeError, UnicodeDecodeError:
            raise JiraProjectRetrievalError("project response was invalid") from None
        finally:
            raw_response[:] = b"\x00" * len(raw_response)
        if not isinstance(payload, dict):
            raise JiraProjectRetrievalError("project response was invalid")
        try:
            return _project_page_from_payload(payload, expected_start=request.start_at)
        finally:
            payload.clear()


@dataclass(frozen=True, slots=True)
class JiraProjectDiscoveryService:
    """Paginate the sole approved endpoint without caching raw pages."""

    authorization_provider: StoredJiraDiscoveryAuthorizationProvider
    transport: JiraProjectDiscoveryHttpTransport
    account_reference: str = "primary-user"
    resource_reference: str = "approved-site"
    max_pages: int = JIRA_PROJECT_MAX_PAGES

    def discover(self) -> tuple[JiraDiscoveryAuthorization, JiraProjectDiscovery]:
        """Return one complete in-memory project catalog."""

        if self.max_pages < 1:
            raise ValueError("Jira project page limit must be positive")
        authorization = self.authorization_provider.get_authorization(
            account_reference=self.account_reference,
            resource_reference=self.resource_reference,
        )
        projects_by_id: dict[str, JiraProject] = {}
        duplicate_count = 0
        start_at = 0
        page_count = 0
        while page_count < self.max_pages:
            try:
                page = self.transport.list_projects(
                    authorization,
                    JiraProjectPageRequest(start_at=start_at),
                )
            except JiraProjectDiscoveryError as error:
                if page_count == 0:
                    raise
                raise JiraPartialPaginationError(
                    completed_projects=tuple(projects_by_id.values()),
                    page_count=page_count,
                    cause_category=type(error).__name__,
                ) from None
            page_count += 1
            for project in page.projects:
                if project.id in projects_by_id:
                    duplicate_count += 1
                projects_by_id[project.id] = project
            if page.is_last:
                return authorization, JiraProjectDiscovery(
                    projects=tuple(
                        sorted(
                            projects_by_id.values(),
                            key=lambda item: (item.key.casefold(), item.id),
                        )
                    ),
                    page_count=page_count,
                    duplicate_project_count=duplicate_count,
                )
            next_start = page.start_at + page.max_results
            if next_start <= start_at:
                raise JiraPartialPaginationError(
                    completed_projects=tuple(projects_by_id.values()),
                    page_count=page_count,
                    cause_category="JiraInvalidPagination",
                )
            start_at = next_start
        raise JiraProjectPageLimitError(
            "Jira project discovery reached its approved page limit"
        )


@dataclass(frozen=True, slots=True)
class JiraProjectDiscoveryTrialRunner:
    """Persist only run/site/provenance metadata and one private report."""

    state_store: StateStore
    discovery_service: JiraProjectDiscoveryService
    output_directory: Path
    accessible_site_count: int = 1
    account_identity_source: str = "user-confirmed"
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def run(self) -> JiraProjectDiscoveryReport:
        """Complete one bounded project-only discovery trial."""

        started_at = self.clock()
        authorization, discovery = self.discovery_service.discover()
        completed_at = self.clock()
        client = self.state_store.get_oauth_client(JIRA_CONNECTOR)
        if client is None:
            raise JiraProjectDiscoveryError("Jira OAuth client metadata is missing")
        run_id = f"jira-project-discovery-{uuid.uuid4().hex}"
        approved_scope = (
            f"{JIRA_PROPOSED_READ_SCOPE}; resource=approved-site; "
            f"operation={JIRA_PROJECT_SEARCH_OPERATION}; action=browse"
        )
        self.state_store.add_connector_run(
            ConnectorRun(
                id=run_id,
                source="jira_project_discovery",
                approved_scope=approved_scope,
                started_at=started_at,
                completed_at=completed_at,
                status=ConnectorStatus.SUCCEEDED,
                coverage_status=CoverageStatus.COMPLETE,
                freshness_at=completed_at,
                page_count=discovery.page_count,
                connector_instance_id=JIRA_PRIMARY_INSTANCE,
            )
        )
        fingerprint = hashlib.sha256(
            (
                f"jira-project-catalog\0{authorization.cloud_id}\0"
                f"{len(discovery.projects)}\0{completed_at.isoformat()}"
            ).encode()
        ).hexdigest()
        self.state_store.add_source_evidence(
            SourceEvidence(
                id=f"{run_id}:catalog",
                connector_run_id=run_id,
                source="jira_project_discovery",
                source_record_id="project-catalog",
                display_url=f"{authorization.site_url.rstrip('/')}/jira/projects",
                excerpt=None,
                evidence_fingerprint=fingerprint,
                retrieved_at=completed_at,
                freshness_at=completed_at,
                connector_instance_id=JIRA_PRIMARY_INSTANCE,
            )
        )
        output_path = self._write_private_report(
            run_id=run_id,
            generated_at=completed_at,
            authorization=authorization,
            discovery=discovery,
            application_name=client.oauth_project_id,
            application_owner=client.application_owner or "TBD",
        )
        self.state_store.mark_connector_authorization_used(
            JIRA_CONNECTOR,
            used_at=completed_at,
        )
        return JiraProjectDiscoveryReport(
            application_name=client.oauth_project_id,
            application_owner=client.application_owner or "TBD",
            account_identity=authorization.account_identity,
            account_identity_source=self.account_identity_source,
            granted_scope=authorization.granted_scope,
            grant_type=authorization.grant_type,
            site_url=authorization.site_url,
            cloud_id=authorization.cloud_id,
            accessible_site_count=self.accessible_site_count,
            project_count=len(discovery.projects),
            project_page_count=discovery.page_count,
            duplicate_project_count=discovery.duplicate_project_count,
            output_path=output_path,
            credential_health=CredentialHealth.HEALTHY.value,
            connector_run_id=run_id,
        )

    def _write_private_report(
        self,
        *,
        run_id: str,
        generated_at: datetime,
        authorization: JiraDiscoveryAuthorization,
        discovery: JiraProjectDiscovery,
        application_name: str,
        application_owner: str,
    ) -> Path:
        self.output_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.output_directory.chmod(0o700)
        output_path = self.output_directory / f"{run_id}.md"
        content = _render_private_report(
            generated_at=generated_at,
            authorization=authorization,
            discovery=discovery,
            application_name=application_name,
            application_owner=application_owner,
        )
        descriptor = os.open(
            output_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        return output_path


def _project_page_from_payload(
    payload: dict[object, object],
    *,
    expected_start: int,
) -> JiraProjectPage:
    raw_projects = payload.get("values")
    start_at = payload.get("startAt")
    max_results = payload.get("maxResults")
    is_last = payload.get("isLast")
    total = payload.get("total")
    if (
        not isinstance(raw_projects, list)
        or isinstance(start_at, bool)
        or not isinstance(start_at, int)
        or start_at != expected_start
        or isinstance(max_results, bool)
        or not isinstance(max_results, int)
        or max_results <= 0
        or not isinstance(is_last, bool)
        or not (
            total is None
            or (isinstance(total, int) and not isinstance(total, bool) and total >= 0)
        )
    ):
        raise JiraProjectRetrievalError("project page omitted pagination fields")
    try:
        projects = tuple(_project_from_payload(item) for item in raw_projects)
    finally:
        raw_projects.clear()
    return JiraProjectPage(
        projects=projects,
        start_at=start_at,
        max_results=max_results,
        is_last=is_last,
        total=total,
    )


def _project_from_payload(payload: object) -> JiraProject:
    if not isinstance(payload, dict):
        raise JiraProjectRetrievalError("project page contained an invalid record")
    project_id = payload.get("id")
    key = payload.get("key")
    name = payload.get("name")
    project_type = payload.get("projectTypeKey")
    archived = payload.get("archived")
    if (
        isinstance(project_id, bool)
        or not isinstance(project_id, (int, str))
        or not str(project_id).strip()
        or not isinstance(key, str)
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key)
        or not isinstance(name, str)
        or not name.strip()
        or not (project_type is None or isinstance(project_type, str))
        or not (archived is None or isinstance(archived, bool))
    ):
        raise JiraProjectRetrievalError("project record omitted approved fields")
    return JiraProject(
        id=str(project_id).strip(),
        key=key.strip(),
        name=" ".join(name.split()),
        project_type=(
            "unknown"
            if project_type is None or not project_type.strip()
            else project_type.strip()
        ),
        archived=archived,
    )


def _render_private_report(
    *,
    generated_at: datetime,
    authorization: JiraDiscoveryAuthorization,
    discovery: JiraProjectDiscovery,
    application_name: str,
    application_owner: str,
) -> str:
    lines = [
        "# Jira Project Discovery",
        "",
        "- **Private local report:** Do not commit or share.",
        f"- **Generated:** {generated_at.isoformat()}",
        f"- **Application:** {_markdown_text(application_name)}",
        f"- **Ownership:** {_markdown_text(application_owner)}",
        (
            "- **Authorized account:** "
            f"{_markdown_text(authorization.account_identity)} (user-confirmed)"
        ),
        f"- **Granted scope:** `{authorization.granted_scope}`",
        f"- **Grant type:** `{authorization.grant_type}`",
        f"- **Selected site:** {_markdown_text(authorization.site_url)}",
        f"- **Selected cloudId:** `{_markdown_text(authorization.cloud_id)}`",
        f"- **Project pages:** {discovery.page_count}",
        f"- **Projects available to browse:** {len(discovery.projects)}",
        "",
        "## Project boundary selection",
        "",
        "Check only the projects that Brad explicitly approves for the later "
        "issue trial. Project names alone are not approval.",
        "",
    ]
    if discovery.projects:
        for project in discovery.projects:
            archived = (
                "unknown"
                if project.archived is None
                else ("yes" if project.archived else "no")
            )
            lines.append(
                f"- [ ] `{_markdown_text(project.key)}` — "
                f"{_markdown_text(project.name)} "
                f"(ID `{_markdown_text(project.id)}`; "
                f"type `{_markdown_text(project.project_type)}`; "
                f"archived {archived}; browse yes)"
            )
    else:
        lines.append("- No accessible projects were returned.")
    lines.extend(
        [
            "",
            "## Issue-trial choices",
            "",
            "- [ ] Search every project checked above.",
            "- [ ] Allow explicitly linked issue keys outside the selected projects.",
            "- Approved project keys: `<APPROVED_PROJECT_KEYS>`",
            "- Approved explicit issue keys, if any: `<EXPLICITLY_LINKED_ISSUE_KEYS>`",
            "",
            "## Proposed JQL — not executed",
            "",
            "```text",
            "project in (<APPROVED_PROJECT_KEYS>)",
            "AND statusCategory != Done",
            "AND (",
            "  assignee = currentUser()",
            "  OR key in (<EXPLICITLY_LINKED_ISSUE_KEYS>)",
            ")",
            "ORDER BY updated DESC, key ASC",
            "```",
            "",
            "If no explicit issue keys are approved, use:",
            "",
            "```text",
            "project in (<APPROVED_PROJECT_KEYS>)",
            "AND statusCategory != Done",
            "AND assignee = currentUser()",
            "ORDER BY updated DESC, key ASC",
            "```",
            "",
            "## Proposed issue fields — not retrieved",
            "",
            "Included: "
            + ", ".join(f"`{field}`" for field in JIRA_PROPOSED_ISSUE_FIELDS)
            + ".",
            "",
            "Excluded: "
            + ", ".join(f"`{field}`" for field in JIRA_EXCLUDED_ISSUE_FIELDS)
            + "; unrestricted search; and all mutations.",
            "",
            "No JQL or issue endpoint was executed during this discovery.",
            "",
        ]
    )
    return "\n".join(lines)


def _markdown_text(value: str) -> str:
    return (
        " ".join(value.split())
        .replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("|", "\\|")
    )
