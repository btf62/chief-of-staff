"""Security, OAuth, transport, lifecycle, and report tests for Jira discovery."""

from __future__ import annotations

import json
import stat
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path

import pytest

from chief_of_staff.auth.jira_oauth import (
    JIRA_CONNECTOR,
    JIRA_GRANT_TYPE,
    JIRA_OAUTH_AUDIENCE,
    JIRA_PROPOSED_READ_SCOPE,
    JIRA_REDIRECT_URI,
    JiraAccessibleResource,
    JiraAccountConfirmationError,
    JiraAmbiguousSiteError,
    JiraAuthorizationResult,
    JiraInstalledAppOAuth,
    JiraNoAccessibleSiteError,
    JiraOAuthClientRegistrar,
    JiraOAuthStateMismatch,
    JiraOAuthTokenResponse,
)
from chief_of_staff.auth.keychain import (
    KeychainSecretReference,
    MacOSKeychain,
    SecurityCommandResult,
)
from chief_of_staff.connectors.jira_discovery import (
    JIRA_PROJECT_PAGE_SIZE,
    JIRA_PROJECT_SEARCH_OPERATION,
    JiraDiscoveryAuthenticationError,
    JiraDiscoveryAuthorization,
    JiraPartialPaginationError,
    JiraProject,
    JiraProjectDiscoveryHttpTransport,
    JiraProjectDiscoveryService,
    JiraProjectDiscoveryTrialRunner,
    JiraProjectPageRequest,
    JiraProjectPermissionError,
    JiraProjectRateLimitError,
    JiraProjectRetrievalError,
    JiraSiteBoundaryError,
    StoredJiraDiscoveryAuthorizationProvider,
)
from chief_of_staff.jira_live_cli import _read_interactive_client_credentials
from chief_of_staff.persistence import Database, StateStore

NOW = datetime(2026, 7, 27, 14, 0, tzinfo=UTC)
CLIENT_ID = "synthetic-atlassian-client"
CLIENT_SECRET = "synthetic-atlassian-client-secret"
ACCESS_TOKEN = "synthetic-atlassian-access-token"
ACCOUNT_IDENTITY = "selected@example.invalid"
ACCOUNT_REFERENCE = "primary-user"
CLOUD_ID = "11111111-2222-3333-4444-555555555555"
SITE_URL = "https://selected-site.atlassian.net"


@dataclass(slots=True)
class _FakeSecurityRunner:
    items: dict[tuple[str, str], str] = field(default_factory=dict)
    calls: list[tuple[tuple[str, ...], str | None]] = field(default_factory=list)

    def __call__(
        self,
        arguments: tuple[str, ...],
        *,
        input_text: str | None,
        capture_output: bool,
    ) -> SecurityCommandResult:
        del capture_output
        self.calls.append((arguments, input_text))
        account = arguments[arguments.index("-a") + 1]
        service = arguments[arguments.index("-s") + 1]
        key = (service, account)
        if arguments[0] == "add-generic-password":
            assert input_text is not None
            self.items[key] = input_text.rstrip("\n")
            return SecurityCommandResult(returncode=0)
        if arguments[0] == "find-generic-password":
            if key not in self.items:
                return SecurityCommandResult(returncode=44)
            return SecurityCommandResult(
                returncode=0,
                stdout=f"{self.items[key]}\n" if "-w" in arguments else "",
            )
        if arguments[0] == "delete-generic-password":
            existed = self.items.pop(key, None) is not None
            return SecurityCommandResult(returncode=0 if existed else 44)
        raise AssertionError("unexpected Keychain operation")


def _keychain() -> tuple[MacOSKeychain, _FakeSecurityRunner]:
    runner = _FakeSecurityRunner()
    return MacOSKeychain(command_runner=runner), runner


@dataclass(slots=True)
class _FakeTokenClient:
    response: JiraOAuthTokenResponse = field(
        default_factory=lambda: JiraOAuthTokenResponse(
            access_token=ACCESS_TOKEN,
            granted_scope=JIRA_PROPOSED_READ_SCOPE,
            expires_in_seconds=3600,
        )
    )
    exchange_called: bool = False

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
    ) -> JiraOAuthTokenResponse:
        assert client_id == CLIENT_ID
        assert client_secret == CLIENT_SECRET
        assert code == "synthetic-code"
        assert redirect_uri == JIRA_REDIRECT_URI
        self.exchange_called = True
        return self.response


@dataclass(frozen=True, slots=True)
class _FakeResourceClient:
    resources: tuple[JiraAccessibleResource, ...] = (
        JiraAccessibleResource(
            cloud_id=CLOUD_ID,
            url=SITE_URL,
            scopes=frozenset({JIRA_PROPOSED_READ_SCOPE}),
        ),
    )

    def get_accessible_resources(
        self,
        *,
        access_token: str,
    ) -> tuple[JiraAccessibleResource, ...]:
        assert access_token == ACCESS_TOKEN
        return self.resources


@dataclass(slots=True)
class _CallbackBrowser:
    mismatched_state: bool = False
    authorization_url: str | None = None
    callback_thread: threading.Thread | None = None

    def __call__(self, authorization_url: str) -> None:
        self.authorization_url = authorization_url
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(authorization_url).query)
        state = "wrong-state" if self.mismatched_state else query["state"][0]
        callback_url = f"{query['redirect_uri'][0]}?" + urllib.parse.urlencode(
            {"code": "synthetic-code", "state": state}
        )

        def send_callback() -> None:
            try:
                with urllib.request.urlopen(  # noqa: S310 - loopback test
                    callback_url,
                    timeout=5,
                ) as response:
                    response.read()
            except urllib.error.HTTPError:
                pass

        self.callback_thread = threading.Thread(target=send_callback)
        self.callback_thread.start()


def _register_client(store: StateStore, keychain: MacOSKeychain) -> None:
    JiraOAuthClientRegistrar(
        keychain=keychain,
        state_store=store,
        clock=lambda: NOW,
    ).register(
        application_name="Chief of Staff (Local) — Jira",
        application_owner="Northridge",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )


def test_interactive_client_registration_hides_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    def read_client_id(prompt: str) -> str:
        prompts.append(prompt)
        return f"  {CLIENT_ID}  "

    def read_client_secret(prompt: str) -> str:
        prompts.append(prompt)
        return CLIENT_SECRET

    monkeypatch.setattr("builtins.input", read_client_id)
    monkeypatch.setattr(
        "chief_of_staff.jira_live_cli.getpass.getpass",
        read_client_secret,
    )

    assert _read_interactive_client_credentials() == (CLIENT_ID, CLIENT_SECRET)
    assert prompts == [
        "Jira client ID: ",
        "Jira client secret (stored only in macOS Keychain): ",
    ]


def _authorize(
    store: StateStore,
    keychain: MacOSKeychain,
    *,
    resource_client: _FakeResourceClient | None = None,
    browser: _CallbackBrowser | None = None,
    account_confirmed: bool = True,
) -> JiraAuthorizationResult:
    selected_browser = browser or _CallbackBrowser()
    result = JiraInstalledAppOAuth(
        keychain=keychain,
        state_store=store,
        token_client=_FakeTokenClient(),
        resource_client=resource_client or _FakeResourceClient(),
        clock=lambda: NOW,
        browser_opener=selected_browser,
        account_confirmer=lambda expected: (
            expected == ACCOUNT_IDENTITY and account_confirmed
        ),
    ).authorize_interactively(
        account_reference=ACCOUNT_REFERENCE,
        expected_account_identity=ACCOUNT_IDENTITY,
        timeout_seconds=5,
    )
    assert selected_browser.callback_thread is not None
    selected_browser.callback_thread.join(timeout=5)
    return result


def test_jira_oauth_exact_scope_state_account_site_and_keychain(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    keychain, runner = _keychain()
    browser = _CallbackBrowser()
    with Database.open(database_path) as database:
        store = StateStore(database)
        _register_client(store, keychain)
        result = _authorize(store, keychain, browser=browser)

        authorization = store.get_connector_authorization(JIRA_CONNECTOR)
        resource = store.get_connector_resource(JIRA_CONNECTOR)
        client = store.get_oauth_client(JIRA_CONNECTOR)
        assert authorization == result.metadata
        assert resource == result.resource
        assert authorization is not None
        assert resource is not None
        assert client is not None
        assert client.oauth_grant_type == JIRA_GRANT_TYPE
        assert authorization.granted_scope == JIRA_PROPOSED_READ_SCOPE
        assert authorization.account_identity == ACCOUNT_IDENTITY
        assert authorization.refresh_token_account is None
        assert resource.resource_id == CLOUD_ID
        assert resource.resource_url == SITE_URL
        assert resource.grant_type == JIRA_GRANT_TYPE
        assert result.accessible_site_count == 1
        assert result.account_identity_source == "user-confirmed"
        assert result.access_token_issued
        assert not result.refresh_token_issued

    assert browser.authorization_url is not None
    query = urllib.parse.parse_qs(
        urllib.parse.urlsplit(browser.authorization_url).query
    )
    assert query == {
        "audience": [JIRA_OAUTH_AUDIENCE],
        "client_id": [CLIENT_ID],
        "scope": [JIRA_PROPOSED_READ_SCOPE],
        "redirect_uri": [JIRA_REDIRECT_URI],
        "state": [query["state"][0]],
        "response_type": ["code"],
        "prompt": ["consent"],
    }
    assert query["state"][0]
    forbidden_scopes = (
        "read:jira-user",
        "read:me",
        "offline_access",
        "write:jira-work",
        "manage:jira",
        "servicedesk",
        "confluence",
    )
    assert all(scope not in browser.authorization_url for scope in forbidden_scopes)
    assert CLIENT_SECRET in runner.items.values()
    assert ACCESS_TOKEN in runner.items.values()
    database_bytes = database_path.read_bytes()
    assert CLIENT_SECRET.encode() not in database_bytes
    assert ACCESS_TOKEN.encode() not in database_bytes
    assert stat.S_IMODE(database_path.stat().st_mode) == 0o600
    assert ACCESS_TOKEN not in repr(result)


def test_jira_oauth_rejects_state_and_account_before_exchange(
    tmp_path: Path,
) -> None:
    keychain, _runner = _keychain()
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        _register_client(store, keychain)
        mismatched_browser = _CallbackBrowser(mismatched_state=True)
        token_client = _FakeTokenClient()
        with pytest.raises(JiraOAuthStateMismatch):
            JiraInstalledAppOAuth(
                keychain=keychain,
                state_store=store,
                token_client=token_client,
                resource_client=_FakeResourceClient(),
                clock=lambda: NOW,
                browser_opener=mismatched_browser,
                account_confirmer=lambda _expected: True,
            ).authorize_interactively(
                account_reference=ACCOUNT_REFERENCE,
                expected_account_identity=ACCOUNT_IDENTITY,
                timeout_seconds=5,
            )
        assert mismatched_browser.callback_thread is not None
        mismatched_browser.callback_thread.join(timeout=5)
        assert not token_client.exchange_called

        account_browser = _CallbackBrowser()
        token_client = _FakeTokenClient()
        with pytest.raises(JiraAccountConfirmationError):
            JiraInstalledAppOAuth(
                keychain=keychain,
                state_store=store,
                token_client=token_client,
                resource_client=_FakeResourceClient(),
                clock=lambda: NOW,
                browser_opener=account_browser,
                account_confirmer=lambda _expected: False,
            ).authorize_interactively(
                account_reference=ACCOUNT_REFERENCE,
                expected_account_identity=ACCOUNT_IDENTITY,
                timeout_seconds=5,
            )
        assert account_browser.callback_thread is not None
        account_browser.callback_thread.join(timeout=5)
        assert not token_client.exchange_called


@pytest.mark.parametrize(
    ("resources", "expected_error"),
    [
        ((), JiraNoAccessibleSiteError),
        (
            (
                JiraAccessibleResource(
                    cloud_id=CLOUD_ID,
                    url=SITE_URL,
                    scopes=frozenset({JIRA_PROPOSED_READ_SCOPE}),
                ),
                JiraAccessibleResource(
                    cloud_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    url="https://other-site.atlassian.net",
                    scopes=frozenset({JIRA_PROPOSED_READ_SCOPE}),
                ),
            ),
            JiraAmbiguousSiteError,
        ),
    ],
)
def test_jira_oauth_distinguishes_missing_and_ambiguous_sites(
    tmp_path: Path,
    resources: tuple[JiraAccessibleResource, ...],
    expected_error: type[Exception],
) -> None:
    keychain, runner = _keychain()
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        _register_client(store, keychain)
        browser = _CallbackBrowser()
        with pytest.raises(expected_error):
            _authorize(
                store,
                keychain,
                resource_client=_FakeResourceClient(resources=resources),
                browser=browser,
            )
        assert store.get_connector_authorization(JIRA_CONNECTOR) is None
        assert store.get_connector_resource(JIRA_CONNECTOR) is None
    assert ACCESS_TOKEN not in runner.items.values()


@dataclass(slots=True)
class _Response:
    payload: object

    def read(self, amount: int = -1) -> bytes:
        return json.dumps(self.payload).encode()[:amount]

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return


@dataclass(slots=True)
class _ProjectOpener:
    payloads: list[object]
    failure_on_call: int | None = None
    failure_code: int | None = None
    requests: list[urllib.request.Request] = field(default_factory=list)

    def __call__(
        self,
        request: urllib.request.Request,
        *,
        timeout: int,
    ) -> _Response:
        assert timeout == 30
        self.requests.append(request)
        if self.failure_on_call == len(self.requests):
            if self.failure_code is None:
                raise urllib.error.URLError("synthetic")
            raise urllib.error.HTTPError(
                request.full_url,
                self.failure_code,
                "synthetic",
                Message(),
                None,
            )
        return _Response(self.payloads[len(self.requests) - 1])


def _project_payload(
    *,
    start_at: int,
    is_last: bool,
    projects: list[dict[str, object]],
    total: int = 2,
) -> dict[str, object]:
    return {
        "isLast": is_last,
        "maxResults": JIRA_PROJECT_PAGE_SIZE,
        "startAt": start_at,
        "total": total,
        "values": projects,
    }


def _raw_project(
    project_id: str,
    key: str,
    name: str,
    *,
    archived: bool | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": project_id,
        "key": key,
        "name": name,
        "projectTypeKey": "software",
        "description": "must be discarded",
        "lead": {"displayName": "must be discarded"},
        "insight": {"totalIssueCount": 999},
        "roles": {"Administrators": "must be discarded"},
    }
    if archived is not None:
        payload["archived"] = archived
    return payload


def _live_service(
    store: StateStore,
    keychain: MacOSKeychain,
    opener: _ProjectOpener,
    result: JiraAuthorizationResult,
) -> JiraProjectDiscoveryService:
    reference = KeychainSecretReference(
        service=result.metadata.credential_service,
        account=result.metadata.access_token_account,
    )
    return JiraProjectDiscoveryService(
        authorization_provider=StoredJiraDiscoveryAuthorizationProvider(
            state_store=store,
            keychain=keychain,
            clock=lambda: NOW + timedelta(minutes=1),
        ),
        transport=JiraProjectDiscoveryHttpTransport(
            keychain=keychain,
            access_token_reference=reference,
            approved_cloud_id=CLOUD_ID,
            url_opener=opener,
        ),
    )


def test_project_discovery_uses_only_browse_search_and_handles_pagination(
    tmp_path: Path,
) -> None:
    keychain, _runner = _keychain()
    opener = _ProjectOpener(
        payloads=[
            _project_payload(
                start_at=0,
                is_last=False,
                projects=[_raw_project("1", "AAA", "Alpha")],
            ),
            _project_payload(
                start_at=50,
                is_last=True,
                projects=[_raw_project("2", "BBB", "Beta", archived=False)],
            ),
        ]
    )
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        _register_client(store, keychain)
        result = _authorize(store, keychain)
        authorization, discovery = _live_service(
            store,
            keychain,
            opener,
            result,
        ).discover()

    assert authorization.cloud_id == CLOUD_ID
    assert discovery.page_count == 2
    assert discovery.pagination_occurred
    assert [project.key for project in discovery.projects] == ["AAA", "BBB"]
    assert fields(JiraProject) == (
        fields(JiraProject)[0],
        fields(JiraProject)[1],
        fields(JiraProject)[2],
        fields(JiraProject)[3],
        fields(JiraProject)[4],
        fields(JiraProject)[5],
    )
    assert [field.name for field in fields(JiraProject)] == [
        "id",
        "key",
        "name",
        "project_type",
        "archived",
        "browse_available",
    ]
    assert all(request.method == "GET" for request in opener.requests)
    assert len(opener.requests) == 2
    for index, request in enumerate(opener.requests):
        parsed = urllib.parse.urlsplit(request.full_url)
        assert parsed.path == (f"/ex/jira/{CLOUD_ID}/rest/api/3/project/search")
        query = urllib.parse.parse_qs(parsed.query)
        assert query == {
            "action": ["browse"],
            "maxResults": [str(JIRA_PROJECT_PAGE_SIZE)],
            "orderBy": ["key"],
            "startAt": [str(index * JIRA_PROJECT_PAGE_SIZE)],
        }
        assert "/issue" not in request.full_url
        assert "/search/jql" not in request.full_url
    assert JIRA_PROJECT_SEARCH_OPERATION == "GET /rest/api/3/project/search"


def test_unselected_site_is_rejected_before_network_access() -> None:
    keychain, _runner = _keychain()
    reference = KeychainSecretReference("test.service", "jira-access")
    keychain.store(reference, ACCESS_TOKEN)
    opener = _ProjectOpener(payloads=[])
    transport = JiraProjectDiscoveryHttpTransport(
        keychain=keychain,
        access_token_reference=reference,
        approved_cloud_id=CLOUD_ID,
        url_opener=opener,
    )
    with pytest.raises(JiraSiteBoundaryError):
        transport.list_projects(
            JiraDiscoveryAuthorization(
                account_reference=ACCOUNT_REFERENCE,
                account_identity=ACCOUNT_IDENTITY,
                cloud_id="unselected-cloud-id",
                site_url="https://other-site.atlassian.net",
                granted_scope=JIRA_PROPOSED_READ_SCOPE,
                grant_type=JIRA_GRANT_TYPE,
                credential_reference=reference.identifier,
            ),
            JiraProjectPageRequest(),
        )
    assert opener.requests == []


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, JiraDiscoveryAuthenticationError),
        (403, JiraProjectPermissionError),
        (429, JiraProjectRateLimitError),
        (500, JiraProjectRetrievalError),
    ],
)
def test_project_failure_categories_are_distinct(
    tmp_path: Path,
    status_code: int,
    expected_error: type[Exception],
) -> None:
    keychain, _runner = _keychain()
    opener = _ProjectOpener(
        payloads=[],
        failure_on_call=1,
        failure_code=status_code,
    )
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        _register_client(store, keychain)
        result = _authorize(store, keychain)
        with pytest.raises(expected_error):
            _live_service(store, keychain, opener, result).discover()


def test_empty_projects_and_partial_pagination_are_distinct(
    tmp_path: Path,
) -> None:
    keychain, _runner = _keychain()
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        _register_client(store, keychain)
        result = _authorize(store, keychain)
        _authorization, empty = _live_service(
            store,
            keychain,
            _ProjectOpener(
                payloads=[
                    _project_payload(
                        start_at=0,
                        is_last=True,
                        projects=[],
                        total=0,
                    )
                ]
            ),
            result,
        ).discover()
        assert empty.projects == ()
        assert empty.page_count == 1

        opener = _ProjectOpener(
            payloads=[
                _project_payload(
                    start_at=0,
                    is_last=False,
                    projects=[_raw_project("1", "AAA", "Alpha")],
                )
            ],
            failure_on_call=2,
            failure_code=429,
        )
        with pytest.raises(JiraPartialPaginationError) as captured:
            _live_service(store, keychain, opener, result).discover()
        assert captured.value.page_count == 1
        assert captured.value.cause_category == "JiraProjectRateLimitError"
        assert len(captured.value.completed_projects) == 1


def test_private_report_and_sqlite_contain_only_approved_persistence(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    output_directory = tmp_path / ".local" / "jira"
    keychain, _runner = _keychain()
    opener = _ProjectOpener(
        payloads=[
            _project_payload(
                start_at=0,
                is_last=True,
                projects=[
                    _raw_project(
                        "987654",
                        "PRIVATEKEY",
                        "Private Synthetic Project",
                    )
                ],
                total=1,
            )
        ]
    )
    with Database.open(database_path) as database:
        store = StateStore(database)
        _register_client(store, keychain)
        result = _authorize(store, keychain)
        report = JiraProjectDiscoveryTrialRunner(
            state_store=store,
            discovery_service=_live_service(store, keychain, opener, result),
            output_directory=output_directory,
            clock=lambda: NOW + timedelta(minutes=2),
        ).run()
        inspection = store.inspect_state()
        assert inspection.connector_runs == 1
        assert inspection.source_evidence == 1
        assert inspection.connector_resources == 1
        assert inspection.normalized_source_tasks == 0

    assert report.project_count == 1
    assert not report.project_catalog_persisted
    assert not report.raw_payload_persisted
    assert not report.issue_endpoint_called
    assert not report.refresh_token_requested
    assert stat.S_IMODE(report.output_path.stat().st_mode) == 0o600
    private_report = report.output_path.read_text(encoding="utf-8")
    assert "PRIVATEKEY" in private_report
    assert "Private Synthetic Project" in private_report
    assert "project in (<APPROVED_PROJECT_KEYS>)" in private_report
    assert "key in (<EXPLICITLY_LINKED_ISSUE_KEYS>)" in private_report
    assert "description" in private_report
    assert "No JQL or issue endpoint was executed" in private_report
    assert ACCESS_TOKEN not in private_report
    assert CLIENT_SECRET not in private_report

    database_bytes = database_path.read_bytes()
    assert b"PRIVATEKEY" not in database_bytes
    assert b"Private Synthetic Project" not in database_bytes
    assert ACCESS_TOKEN.encode() not in database_bytes
    assert CLIENT_SECRET.encode() not in database_bytes


def test_discovery_exposes_no_mutation_or_issue_operation() -> None:
    public_transport_methods = {
        name
        for name, value in vars(JiraProjectDiscoveryHttpTransport).items()
        if not name.startswith("_") and callable(value)
    }
    assert public_transport_methods == {"list_projects"}
    for operation in (
        "search_issues",
        "get_issue",
        "create_issue",
        "edit_issue",
        "delete_issue",
        "add_comment",
        "transition_issue",
        "create_project",
        "archive_project",
    ):
        assert not hasattr(JiraProjectDiscoveryHttpTransport, operation)
        assert not hasattr(JiraProjectDiscoveryService, operation)
