"""Exact-boundary live Jira enhanced-search transport."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
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
from chief_of_staff.connectors.jira import (
    JIRA_APPROVED_JQL,
    JIRA_APPROVED_PROJECT_KEY,
    JIRA_INITIAL_FIELDS,
    JIRA_PAGE_LIMIT,
    JiraAuthenticationError,
    JiraAuthorization,
    JiraAuthorizationUnavailable,
    JiraInvalidJqlError,
    JiraIssue,
    JiraIssueLink,
    JiraIssuePage,
    JiraPermissionError,
    JiraRateLimitError,
    JiraRetrievalError,
    JiraSearchRequest,
)
from chief_of_staff.connectors.jira_discovery import JIRA_API_ROOT
from chief_of_staff.domain import AuthorizationStatus, CredentialHealth
from chief_of_staff.persistence import StateStore

MAX_JIRA_ISSUE_RESPONSE_BYTES: Final = 8 * 1024 * 1024
_ISSUE_KEY = re.compile(r"[A-Z][A-Z0-9_]*-[1-9][0-9]*")


class JiraIssueHttpResponse(Protocol):
    """Minimal response surface for injectable contract tests."""

    def read(self, amount: int = -1) -> bytes:
        """Read a bounded response body."""

    def __enter__(self) -> JiraIssueHttpResponse:
        """Enter the response context."""

    def __exit__(self, *args: object) -> None:
        """Close the response context."""


class JiraIssueUrlOpener(Protocol):
    """Injectable HTTPS opener for the sole enhanced-search operation."""

    def __call__(
        self,
        request: urllib.request.Request,
        *,
        timeout: int,
    ) -> JiraIssueHttpResponse:
        """Open one fixed POST request."""


def _open_url(
    request: urllib.request.Request,
    *,
    timeout: int,
) -> JiraIssueHttpResponse:
    return cast(
        JiraIssueHttpResponse,
        urllib.request.urlopen(  # noqa: S310 - fixed HTTPS API root
            request,
            timeout=timeout,
        ),
    )


@dataclass(frozen=True, slots=True)
class StoredJiraAuthorizationProvider:
    """Resolve the one exact-scope, exact-site short-lived Jira grant."""

    state_store: StateStore
    keychain: MacOSKeychain
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def get_jira_authorization(
        self,
        account_reference: str,
        site_reference: str,
    ) -> JiraAuthorization:
        """Return non-secret metadata after validating the stored boundary."""

        metadata = self.state_store.get_connector_authorization(JIRA_CONNECTOR)
        resource = self.state_store.get_connector_resource(JIRA_CONNECTOR)
        if (
            metadata is None
            or resource is None
            or metadata.account_reference != account_reference
            or resource.resource_reference != site_reference
            or metadata.granted_scope != JIRA_PROPOSED_READ_SCOPE
            or resource.grant_type != JIRA_GRANT_TYPE
            or resource.resource_type != "jira_cloud_site"
            or metadata.authorization_status is not AuthorizationStatus.AUTHORIZED
            or metadata.credential_health is not CredentialHealth.HEALTHY
            or metadata.token_expires_at <= self.clock()
            or metadata.refresh_token_account is not None
        ):
            raise JiraAuthorizationUnavailable
        reference = KeychainSecretReference(
            service=metadata.credential_service,
            account=metadata.access_token_account,
        )
        if not self.keychain.exists(reference):
            raise JiraAuthorizationUnavailable
        return JiraAuthorization(
            account_reference=metadata.account_reference,
            account_identity=metadata.account_identity,
            site_reference=resource.resource_reference,
            cloud_resource_reference=resource.resource_id,
            granted_scopes=frozenset({metadata.granted_scope}),
            credential_reference=reference.identifier,
            current_user_assignment_prevalidated=True,
        )


@dataclass(frozen=True, slots=True)
class JiraEnhancedSearchHttpTransport:
    """POST only the exact NRC query to Jira's enhanced JQL endpoint."""

    keychain: MacOSKeychain
    access_token_reference: KeychainSecretReference
    approved_cloud_id: str
    approved_site_url: str
    url_opener: JiraIssueUrlOpener = field(
        default=_open_url,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.approved_cloud_id.strip():
            raise ValueError("approved Jira cloudId must not be empty")
        parsed = urllib.parse.urlsplit(self.approved_site_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or not parsed.hostname.endswith(".atlassian.net")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("approved Jira site URL is invalid")

    def search_issues(
        self,
        authorization: JiraAuthorization,
        request: JiraSearchRequest,
    ) -> JiraIssuePage:
        """Return one minimized enhanced-search page."""

        self._validate_boundary(authorization, request)
        try:
            access_token = self.keychain.read(self.access_token_reference)
        except KeychainSecretNotFound:
            raise JiraAuthenticationError from None
        request_payload: dict[str, object] = {
            "jql": JIRA_APPROVED_JQL,
            "fields": list(JIRA_INITIAL_FIELDS),
            "maxResults": JIRA_PAGE_LIMIT,
        }
        if request.next_page_token is not None:
            request_payload["nextPageToken"] = request.next_page_token
        request_body = json.dumps(
            request_payload,
            separators=(",", ":"),
        ).encode()
        request_payload.clear()
        request_url = (
            f"{JIRA_API_ROOT}/"
            f"{urllib.parse.quote(self.approved_cloud_id, safe='')}"
            "/rest/api/3/search/jql"
        )
        http_request = urllib.request.Request(  # noqa: S310 - fixed API root
            request_url,
            data=request_body,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        request_body = b""
        raw_response = bytearray()
        try:
            with self.url_opener(http_request, timeout=30) as response:
                raw_response = bytearray(
                    response.read(MAX_JIRA_ISSUE_RESPONSE_BYTES + 1)
                )
        except urllib.error.HTTPError as error:
            if error.code == 400:
                raise JiraInvalidJqlError from None
            if error.code == 401:
                raise JiraAuthenticationError from None
            if error.code == 403:
                raise JiraPermissionError from None
            if error.code == 429:
                raise JiraRateLimitError from None
            raise JiraRetrievalError from None
        except urllib.error.URLError, TimeoutError:
            raise JiraRetrievalError from None
        finally:
            access_token = ""
        try:
            if len(raw_response) > MAX_JIRA_ISSUE_RESPONSE_BYTES:
                raise JiraRetrievalError("Jira issue response exceeded its limit")
            payload = json.loads(raw_response)
        except json.JSONDecodeError, UnicodeDecodeError:
            raise JiraRetrievalError("Jira issue response was invalid") from None
        finally:
            raw_response[:] = b"\x00" * len(raw_response)
        if not isinstance(payload, dict):
            raise JiraRetrievalError("Jira issue response was invalid")
        try:
            return _issue_page_from_payload(
                payload,
                site_url=self.approved_site_url,
            )
        finally:
            payload.clear()

    def _validate_boundary(
        self,
        authorization: JiraAuthorization,
        request: JiraSearchRequest,
    ) -> None:
        if (
            authorization.cloud_resource_reference != self.approved_cloud_id
            or authorization.credential_reference
            != self.access_token_reference.identifier
            or authorization.granted_scopes != frozenset({JIRA_PROPOSED_READ_SCOPE})
            or not authorization.current_user_assignment_prevalidated
        ):
            raise JiraAuthenticationError
        if (
            request.boundary.approved_project_keys != (JIRA_APPROVED_PROJECT_KEY,)
            or not request.boundary.assigned_to_current_user
            or not request.boundary.unresolved_only
            or request.boundary.explicitly_linked_issue_keys
            or request.fields != JIRA_INITIAL_FIELDS
            or request.max_results != JIRA_PAGE_LIMIT
            or (
                request.next_page_token is not None
                and not request.next_page_token.strip()
            )
        ):
            raise JiraRetrievalError("Jira enhanced-search boundary mismatch")


def _issue_page_from_payload(
    payload: dict[object, object],
    *,
    site_url: str,
) -> JiraIssuePage:
    raw_issues = payload.get("issues")
    is_last = payload.get("isLast")
    next_page_token = payload.get("nextPageToken")
    if (
        not isinstance(raw_issues, list)
        or not isinstance(is_last, bool)
        or not (
            next_page_token is None
            or (isinstance(next_page_token, str) and bool(next_page_token.strip()))
        )
        or (not is_last and next_page_token is None)
        or (is_last and next_page_token is not None)
    ):
        raise JiraRetrievalError("Jira issue page omitted continuation metadata")
    try:
        issues = tuple(
            _issue_from_payload(item, site_url=site_url) for item in raw_issues
        )
    finally:
        raw_issues.clear()
    return JiraIssuePage(
        issues=issues,
        next_page_token=next_page_token,
    )


def _issue_from_payload(payload: object, *, site_url: str) -> JiraIssue:
    if not isinstance(payload, dict):
        raise JiraRetrievalError("Jira issue page contained an invalid record")
    issue_id = _required_identifier(payload.get("id"))
    key = _required_issue_key(payload.get("key"))
    raw_fields = payload.get("fields")
    if not isinstance(raw_fields, dict):
        raise JiraRetrievalError("Jira issue omitted its approved fields")
    try:
        project = _required_mapping(raw_fields.get("project"), "project")
        issue_type = _required_mapping(raw_fields.get("issuetype"), "issuetype")
        status = _required_mapping(raw_fields.get("status"), "status")
        status_category = _required_mapping(
            status.get("statusCategory"),
            "status category",
        )
        assignee = _required_mapping(raw_fields.get("assignee"), "assignee")
        priority = raw_fields.get("priority")
        parent = raw_fields.get("parent")
        raw_labels = raw_fields.get("labels")
        raw_links = raw_fields.get("issuelinks")
        if not isinstance(raw_labels, list) or not isinstance(raw_links, list):
            raise JiraRetrievalError("Jira issue omitted labels or links")
        labels = tuple(_clean_text(label) for label in raw_labels)
        links = tuple(_link_from_payload(link, site_url=site_url) for link in raw_links)
        priority_name = (
            None
            if priority is None
            else _required_string(
                _required_mapping(priority, "priority").get("name"),
                "priority name",
            )
        )
        parent_key = (
            None
            if parent is None
            else _required_issue_key(_required_mapping(parent, "parent").get("key"))
        )
        return JiraIssue(
            id=issue_id,
            key=key,
            summary=_required_string(raw_fields.get("summary"), "summary"),
            project_key=_required_project_key(project.get("key")),
            issue_type=_required_string(issue_type.get("name"), "issue type"),
            status=_required_string(status.get("name"), "status"),
            status_category=_required_string(
                status_category.get("name"),
                "status category",
            ),
            display_url=f"{site_url.rstrip('/')}/browse/{key}",
            assignee_account_id=_required_identifier(assignee.get("accountId")),
            priority_name=priority_name,
            due_date=_optional_date(raw_fields.get("duedate")),
            created_at=_required_datetime(raw_fields.get("created"), "created"),
            updated_at=_required_datetime(raw_fields.get("updated"), "updated"),
            parent_key=parent_key,
            labels=labels,
            links=links,
        )
    finally:
        raw_fields.clear()


def _link_from_payload(payload: object, *, site_url: str) -> JiraIssueLink:
    if not isinstance(payload, dict):
        raise JiraRetrievalError("Jira issue link was invalid")
    link_type = _required_mapping(payload.get("type"), "issue link type")
    inward = payload.get("inwardIssue")
    outward = payload.get("outwardIssue")
    if (inward is None) == (outward is None):
        raise JiraRetrievalError("Jira issue link omitted its direction")
    if inward is not None:
        related = _required_mapping(inward, "inward issue")
        relationship = _required_string(link_type.get("inward"), "inward relation")
    else:
        related = _required_mapping(outward, "outward issue")
        relationship = _required_string(link_type.get("outward"), "outward relation")
    issue_id = _required_identifier(related.get("id"))
    issue_key = _required_issue_key(related.get("key"))
    return JiraIssueLink(
        relationship=relationship,
        issue_id=issue_id,
        issue_key=issue_key,
        display_url=f"{site_url.rstrip('/')}/browse/{issue_key}",
    )


def _required_mapping(value: object, name: str) -> dict[object, object]:
    if not isinstance(value, dict):
        raise JiraRetrievalError(f"Jira {name} was invalid")
    return value


def _required_identifier(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise JiraRetrievalError("Jira identifier was invalid")
    cleaned = str(value).strip()
    if not cleaned:
        raise JiraRetrievalError("Jira identifier was invalid")
    return cleaned


def _required_issue_key(value: object) -> str:
    cleaned = _required_string(value, "issue key")
    if _ISSUE_KEY.fullmatch(cleaned) is None:
        raise JiraRetrievalError("Jira issue key was invalid")
    return cleaned


def _required_project_key(value: object) -> str:
    key = _required_issue_key(f"{_required_string(value, 'project key')}-1")
    return key.rsplit("-", 1)[0]


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JiraRetrievalError(f"Jira {name} was invalid")
    return _clean_text(value)


def _clean_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JiraRetrievalError("Jira text value was invalid")
    return " ".join(value.split())


def _optional_date(value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise JiraRetrievalError("Jira due date was invalid")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise JiraRetrievalError("Jira due date was invalid") from None


def _required_datetime(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise JiraRetrievalError(f"Jira {name} timestamp was invalid")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise JiraRetrievalError(f"Jira {name} timestamp was invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise JiraRetrievalError(f"Jira {name} timestamp was not timezone-aware")
    return parsed
