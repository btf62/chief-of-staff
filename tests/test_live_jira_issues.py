"""Live Jira enhanced-search transport contract tests without network access."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import Message

import pytest

from chief_of_staff.auth import JIRA_PROPOSED_READ_SCOPE
from chief_of_staff.auth.keychain import KeychainSecretReference
from chief_of_staff.connectors import (
    JIRA_APPROVED_JQL,
    JIRA_INITIAL_FIELDS,
    ConnectorRequest,
    JiraAuthenticationError,
    JiraAuthorization,
    JiraConnector,
    JiraEnhancedSearchHttpTransport,
    JiraInvalidJqlError,
    JiraPermissionError,
    JiraQueryBoundary,
    JiraRateLimitError,
    JiraRetrievalError,
    JiraSearchRequest,
)
from chief_of_staff.domain import CoverageStatus
from chief_of_staff.pipeline import resolve_context

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
CLOUD_ID = "approved-cloud-id"
TOKEN_REFERENCE = KeychainSecretReference(
    service="test-jira",
    account="access-token",
)


@dataclass(slots=True)
class _Keychain:
    value: str = field(default="secret-access-token", repr=False)

    def read(self, reference: KeychainSecretReference) -> str:
        assert reference == TOKEN_REFERENCE
        return self.value


@dataclass(slots=True)
class _Response:
    payload: bytes

    def read(self, amount: int = -1) -> bytes:
        return self.payload[:amount]

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None


@dataclass(slots=True)
class _Opener:
    payloads: list[dict[str, object]]
    requests: list[urllib.request.Request] = field(default_factory=list)

    def __call__(
        self,
        request: urllib.request.Request,
        *,
        timeout: int,
    ) -> _Response:
        assert timeout == 30
        self.requests.append(request)
        payload = self.payloads.pop(0)
        return _Response(json.dumps(payload).encode())


@dataclass(frozen=True, slots=True)
class _Provider:
    authorization: JiraAuthorization

    def get_jira_authorization(
        self,
        account_reference: str,
        site_reference: str,
    ) -> JiraAuthorization:
        assert account_reference == "primary-user"
        assert site_reference == "approved-site"
        return self.authorization


def _authorization() -> JiraAuthorization:
    return JiraAuthorization(
        account_reference="primary-user",
        account_identity="user-confirmed@example.invalid",
        site_reference="approved-site",
        cloud_resource_reference=CLOUD_ID,
        granted_scopes=frozenset({JIRA_PROPOSED_READ_SCOPE}),
        credential_reference=TOKEN_REFERENCE.identifier,
        current_user_assignment_prevalidated=True,
    )


def _issue(
    issue_id: str,
    *,
    key: str,
    summary: str,
    updated: str,
) -> dict[str, object]:
    return {
        "id": issue_id,
        "key": key,
        "fields": {
            "summary": summary,
            "project": {"key": "NRC", "name": "discard this project name"},
            "issuetype": {"name": "Task", "description": "discard"},
            "status": {
                "name": "In Progress",
                "statusCategory": {"name": "In Progress", "key": "indeterminate"},
            },
            "assignee": {
                "accountId": "approved-account-id",
                "displayName": "discard this display name",
            },
            "priority": {"name": "High", "id": "discard"},
            "duedate": "2026-07-28",
            "created": "2026-07-01T10:00:00.000+0000",
            "updated": updated,
            "parent": None,
            "labels": ["approved-label"],
            "issuelinks": [
                {
                    "type": {
                        "inward": "is blocked by",
                        "outward": "blocks",
                        "name": "discard",
                    },
                    "inwardIssue": {
                        "id": "900000099",
                        "key": "NRC-900000099",
                        "fields": {},
                    },
                }
            ],
            "description": "must remain transient",
            "reporter": {"accountId": "must-not-normalize"},
            "comment": {"comments": ["must-not-normalize"]},
        },
        "renderedFields": {"description": "must-not-normalize"},
        "names": {"summary": "must-not-normalize"},
        "schema": {"summary": "must-not-normalize"},
    }


def _request(next_page_token: str | None = None) -> JiraSearchRequest:
    return JiraSearchRequest(
        boundary=JiraQueryBoundary(
            approved_project_keys=("NRC",),
            assigned_to_current_user=True,
            unresolved_only=True,
            explicitly_linked_issue_keys=(),
        ),
        fields=JIRA_INITIAL_FIELDS,
        next_page_token=next_page_token,
    )


def test_live_transport_uses_exact_cloud_query_fields_and_cursor_contract() -> None:
    opener = _Opener(
        payloads=[
            {
                "issues": [
                    _issue(
                        "1",
                        key="NRC-900000001",
                        summary="Approved first issue",
                        updated="2026-07-27T10:00:00.000+0000",
                    )
                ],
                "isLast": False,
                "nextPageToken": "opaque-next-page",
            },
            {
                "issues": [
                    _issue(
                        "2",
                        key="NRC-900000002",
                        summary="Approved second issue",
                        updated="2026-07-26T10:00:00.000+0000",
                    )
                ],
                "isLast": True,
            },
        ]
    )
    transport = JiraEnhancedSearchHttpTransport(
        keychain=_Keychain(),  # type: ignore[arg-type]
        access_token_reference=TOKEN_REFERENCE,
        approved_cloud_id=CLOUD_ID,
        approved_site_url="https://example.atlassian.net",
        url_opener=opener,
    )
    connector = JiraConnector(
        account_reference="primary-user",
        site_reference="approved-site",
        approved_project_keys=("NRC",),
        authorization_provider=_Provider(_authorization()),
        transport=transport,
        clock=lambda: NOW,
    )
    context = resolve_context(
        run_id="live-jira-contract",
        briefing_date=NOW.date(),
        timezone="America/New_York",
    )

    result = connector.retrieve(
        ConnectorRequest(
            run_id=context.run_id,
            briefing_date=context.briefing_date,
            timezone=context.timezone,
            approved_scope=connector.approved_scope,
            window=context.retrieval_window,
        )
    )

    assert result.coverage.status is CoverageStatus.COMPLETE
    assert result.coverage.page_count == 2
    assert [item.source_record_id for item in result.items] == [
        "NRC-900000001",
        "NRC-900000002",
    ]
    assert len(opener.requests) == 2
    raw_bodies = [request.data for request in opener.requests]
    assert all(isinstance(body, bytes | bytearray) for body in raw_bodies)
    bodies = [
        json.loads(body) for body in raw_bodies if isinstance(body, bytes | bytearray)
    ]
    assert bodies[0] == {
        "jql": JIRA_APPROVED_JQL,
        "fields": list(JIRA_INITIAL_FIELDS),
        "maxResults": 50,
    }
    assert bodies[1] == bodies[0] | {"nextPageToken": "opaque-next-page"}
    assert all(
        request.full_url
        == f"https://api.atlassian.com/ex/jira/{CLOUD_ID}/rest/api/3/search/jql"
        for request in opener.requests
    )
    assert all(request.method == "POST" for request in opener.requests)
    assert connector.last_audit is not None
    first = connector.last_audit.selected_issues[0]
    assert first.project_key == "NRC"
    assert first.assignee_account_id == "approved-account-id"
    assert not hasattr(first, "description")
    assert not hasattr(first, "reporter_account_id")
    assert not hasattr(first, "comments")
    assert first.links[0].relationship == "is blocked by"


def test_duplicate_ids_keep_the_newest_representation_in_deterministic_order() -> None:
    opener = _Opener(
        payloads=[
            {
                "issues": [
                    _issue(
                        "1",
                        key="NRC-900000001",
                        summary="Newer representation",
                        updated="2026-07-27T10:00:00.000+0000",
                    )
                ],
                "isLast": False,
                "nextPageToken": "next",
            },
            {
                "issues": [
                    _issue(
                        "1",
                        key="NRC-900000001",
                        summary="Older representation",
                        updated="2026-07-26T10:00:00.000+0000",
                    )
                ],
                "isLast": True,
            },
        ]
    )
    connector = JiraConnector(
        account_reference="primary-user",
        site_reference="approved-site",
        approved_project_keys=("NRC",),
        authorization_provider=_Provider(_authorization()),
        transport=JiraEnhancedSearchHttpTransport(
            keychain=_Keychain(),  # type: ignore[arg-type]
            access_token_reference=TOKEN_REFERENCE,
            approved_cloud_id=CLOUD_ID,
            approved_site_url="https://example.atlassian.net",
            url_opener=opener,
        ),
        clock=lambda: NOW,
    )
    context = resolve_context(
        run_id="duplicate-live-jira",
        briefing_date=NOW.date(),
        timezone="America/New_York",
    )

    result = connector.retrieve(
        ConnectorRequest(
            run_id=context.run_id,
            briefing_date=context.briefing_date,
            timezone=context.timezone,
            approved_scope=connector.approved_scope,
            window=context.retrieval_window,
        )
    )

    assert connector.last_audit is not None
    assert connector.last_audit.duplicate_issue_count == 1
    assert len(result.items) == 1
    assert result.items[0].facts["title"] == "Newer representation"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, JiraInvalidJqlError),
        (401, JiraAuthenticationError),
        (403, JiraPermissionError),
        (429, JiraRateLimitError),
        (500, JiraRetrievalError),
    ],
)
def test_http_failures_remain_distinct(
    status: int,
    expected: type[Exception],
) -> None:
    def fail(
        request: urllib.request.Request,
        *,
        timeout: int,
    ) -> _Response:
        del timeout
        raise urllib.error.HTTPError(
            request.full_url,
            status,
            "synthetic",
            Message(),
            None,
        )

    transport = JiraEnhancedSearchHttpTransport(
        keychain=_Keychain(),  # type: ignore[arg-type]
        access_token_reference=TOKEN_REFERENCE,
        approved_cloud_id=CLOUD_ID,
        approved_site_url="https://example.atlassian.net",
        url_opener=fail,
    )

    with pytest.raises(expected):
        transport.search_issues(_authorization(), _request())


def test_empty_results_are_complete_and_distinct_from_invalid_pagination() -> None:
    empty = JiraEnhancedSearchHttpTransport(
        keychain=_Keychain(),  # type: ignore[arg-type]
        access_token_reference=TOKEN_REFERENCE,
        approved_cloud_id=CLOUD_ID,
        approved_site_url="https://example.atlassian.net",
        url_opener=_Opener(payloads=[{"issues": [], "isLast": True}]),
    )
    invalid = JiraEnhancedSearchHttpTransport(
        keychain=_Keychain(),  # type: ignore[arg-type]
        access_token_reference=TOKEN_REFERENCE,
        approved_cloud_id=CLOUD_ID,
        approved_site_url="https://example.atlassian.net",
        url_opener=_Opener(payloads=[{"issues": [], "isLast": False}]),
    )

    assert empty.search_issues(_authorization(), _request()).issues == ()
    with pytest.raises(JiraRetrievalError, match="continuation"):
        invalid.search_issues(_authorization(), _request())


def test_live_transport_rejects_any_boundary_broadening_and_has_no_mutations() -> None:
    transport = JiraEnhancedSearchHttpTransport(
        keychain=_Keychain(),  # type: ignore[arg-type]
        access_token_reference=TOKEN_REFERENCE,
        approved_cloud_id=CLOUD_ID,
        approved_site_url="https://example.atlassian.net",
        url_opener=_Opener(payloads=[]),
    )
    broadened = JiraSearchRequest(
        boundary=JiraQueryBoundary(
            approved_project_keys=("NRC", "OTHER"),
            explicitly_linked_issue_keys=("OTHER-1",),
        ),
        fields=JIRA_INITIAL_FIELDS,
        next_page_token=None,
    )

    with pytest.raises(JiraRetrievalError, match="boundary"):
        transport.search_issues(_authorization(), broadened)
    for mutation in (
        "create_issue",
        "edit_issue",
        "transition_issue",
        "add_comment",
        "delete_issue",
    ):
        assert not hasattr(transport, mutation)
