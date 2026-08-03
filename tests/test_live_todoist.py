"""Security, OAuth, transport, lifecycle, and briefing tests for Todoist."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path

import pytest

from chief_of_staff.auth.keychain import (
    KeychainSecretReference,
    MacOSKeychain,
    SecurityCommandResult,
)
from chief_of_staff.auth.todoist_oauth import (
    KEYCHAIN_SERVICE,
    TODOIST_CONNECTOR,
    TODOIST_REDIRECT_URI,
    TodoistIdentity,
    TodoistInstalledAppOAuth,
    TodoistOAuthClientRegistrar,
    TodoistOAuthError,
    TodoistOAuthTokenResponse,
)
from chief_of_staff.connectors import (
    TODOIST_DATA_READ_SCOPE,
    StoredTodoistAuthorizationProvider,
    TodoistAuthorization,
    TodoistHttpTransport,
    TodoistPageRequest,
    TodoistPrioritySemanticConflict,
    TodoistRateLimitError,
    verify_todoist_priority_semantics,
)
from chief_of_staff.persistence import Database, StateStore

NOW = datetime(2026, 7, 26, 14, 0, tzinfo=UTC)
ACCOUNT_IDENTITY = "selected@example.invalid"
ACCOUNT_REFERENCE = "primary-user"
CLIENT_ID = "synthetic-todoist-client"


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
    exchange_response: TodoistOAuthTokenResponse
    refresh_response: TodoistOAuthTokenResponse
    exchanged_code: str | None = None
    exchanged_redirect: str | None = None
    refresh_called: bool = False
    revoked: bool = False

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
    ) -> TodoistOAuthTokenResponse:
        assert client_id == CLIENT_ID
        assert client_secret == "synthetic-client-secret"
        self.exchanged_code = code
        self.exchanged_redirect = redirect_uri
        return self.exchange_response

    def refresh(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> TodoistOAuthTokenResponse:
        assert client_id == CLIENT_ID
        assert client_secret == "synthetic-client-secret"
        assert refresh_token in {
            "synthetic-initial-refresh",
            "synthetic-rotated-refresh",
        }
        self.refresh_called = True
        return self.refresh_response

    def revoke(
        self,
        *,
        client_id: str,
        client_secret: str,
        access_token: str,
    ) -> None:
        assert client_id == CLIENT_ID
        assert client_secret == "synthetic-client-secret"
        assert access_token == "synthetic-rotated-access"
        self.revoked = True


@dataclass(frozen=True, slots=True)
class _FakeIdentityClient:
    def get_identity(self, *, access_token: str) -> TodoistIdentity:
        assert access_token == "synthetic-initial-access"
        return TodoistIdentity(
            id="synthetic-user",
            email=ACCOUNT_IDENTITY,
            timezone="America/New_York",
        )


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


def _register_client(
    store: StateStore,
    keychain: MacOSKeychain,
) -> None:
    TodoistOAuthClientRegistrar(
        keychain=keychain,
        state_store=store,
        clock=lambda: NOW,
    ).register(
        application_name="Chief of Staff (Local)",
        application_owner="Brad",
        client_id=CLIENT_ID,
        client_secret="synthetic-client-secret",
    )


def _token_client() -> _FakeTokenClient:
    return _FakeTokenClient(
        exchange_response=TodoistOAuthTokenResponse(
            access_token="synthetic-initial-access",
            refresh_token="synthetic-initial-refresh",
            granted_scope=TODOIST_DATA_READ_SCOPE,
            expires_in_seconds=3600,
        ),
        refresh_response=TodoistOAuthTokenResponse(
            access_token="synthetic-rotated-access",
            refresh_token="synthetic-rotated-refresh",
            granted_scope=TODOIST_DATA_READ_SCOPE,
            expires_in_seconds=3600,
        ),
    )


def test_todoist_oauth_uses_exact_scope_state_refresh_and_keychain(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    keychain, runner = _keychain()
    token_client = _token_client()
    browser = _CallbackBrowser()
    with Database.open(database_path) as database:
        store = StateStore(database)
        _register_client(store, keychain)
        result = TodoistInstalledAppOAuth(
            keychain=keychain,
            state_store=store,
            token_client=token_client,
            identity_client=_FakeIdentityClient(),
            clock=lambda: NOW,
            browser_opener=browser,
        ).authorize_interactively(
            account_reference=ACCOUNT_REFERENCE,
            timeout_seconds=5,
            test_refresh=True,
        )
        stored = store.get_connector_authorization(TODOIST_CONNECTOR)
        assert stored == result.metadata
        assert stored is not None
        assert stored.granted_scope == TODOIST_DATA_READ_SCOPE
        assert stored.account_identity == ACCOUNT_IDENTITY
        assert stored.refresh_token_account is not None
        assert result.access_token_issued
        assert result.refresh_token_issued
        assert result.refresh_tested

        access_reference = KeychainSecretReference(
            stored.credential_service,
            stored.access_token_account,
        )
        keychain.delete(access_reference)
        authorization = StoredTodoistAuthorizationProvider(
            state_store=store,
            keychain=keychain,
            refresher=TodoistInstalledAppOAuth(
                keychain=keychain,
                state_store=store,
                token_client=token_client,
                identity_client=_FakeIdentityClient(),
                clock=lambda: NOW,
            ),
            clock=lambda: NOW,
        ).get_todoist_authorization(ACCOUNT_REFERENCE)
        assert authorization.granted_scopes == frozenset({TODOIST_DATA_READ_SCOPE})
        assert keychain.exists(access_reference)

    assert browser.callback_thread is not None
    browser.callback_thread.join(timeout=5)
    assert browser.authorization_url is not None
    query = urllib.parse.parse_qs(
        urllib.parse.urlsplit(browser.authorization_url).query
    )
    assert query["scope"] == [TODOIST_DATA_READ_SCOPE]
    assert query["redirect_uri"] == [TODOIST_REDIRECT_URI]
    assert query["response_type"] == ["code"]
    assert query["state"][0]
    assert all(
        scope not in browser.authorization_url
        for scope in (
            "task:add",
            "data:read_write",
            "data:delete",
            "project:delete",
            "backups:read",
        )
    )
    assert token_client.exchanged_code == "synthetic-code"
    assert token_client.exchanged_redirect == TODOIST_REDIRECT_URI
    assert token_client.refresh_called
    assert "synthetic-rotated-access" in runner.items.values()
    assert "synthetic-rotated-refresh" in runner.items.values()
    database_bytes = database_path.read_bytes()
    for secret in (
        "synthetic-client-secret",
        "synthetic-initial-access",
        "synthetic-initial-refresh",
        "synthetic-rotated-access",
        "synthetic-rotated-refresh",
    ):
        assert secret.encode() not in database_bytes


def test_todoist_oauth_rejects_state_mismatch(tmp_path: Path) -> None:
    keychain, _runner = _keychain()
    browser = _CallbackBrowser(mismatched_state=True)
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        _register_client(store, keychain)
        oauth = TodoistInstalledAppOAuth(
            keychain=keychain,
            state_store=store,
            token_client=_token_client(),
            identity_client=_FakeIdentityClient(),
            clock=lambda: NOW,
            browser_opener=browser,
        )
        with pytest.raises(TodoistOAuthError, match="denied"):
            oauth.authorize_interactively(
                account_reference=ACCOUNT_REFERENCE,
                timeout_seconds=5,
            )
        assert store.get_connector_authorization(TODOIST_CONNECTOR) is None
    assert browser.callback_thread is not None
    browser.callback_thread.join(timeout=5)


def test_todoist_disconnect_revokes_and_deletes_only_token_grant(
    tmp_path: Path,
) -> None:
    keychain, runner = _keychain()
    token_client = _token_client()
    browser = _CallbackBrowser()
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        _register_client(store, keychain)
        oauth = TodoistInstalledAppOAuth(
            keychain=keychain,
            state_store=store,
            token_client=token_client,
            identity_client=_FakeIdentityClient(),
            clock=lambda: NOW,
            browser_opener=browser,
        )
        oauth.authorize_interactively(
            account_reference=ACCOUNT_REFERENCE,
            timeout_seconds=5,
        )
        oauth.disconnect(revoke=True)

        assert token_client.revoked
        assert store.get_connector_authorization(TODOIST_CONNECTOR) is None
        assert store.get_oauth_client(TODOIST_CONNECTOR) is not None
        assert (
            KEYCHAIN_SERVICE,
            f"{TODOIST_CONNECTOR}:access-token:{ACCOUNT_REFERENCE}",
        ) not in runner.items
        assert (
            KEYCHAIN_SERVICE,
            f"{TODOIST_CONNECTOR}:refresh-token:{ACCOUNT_REFERENCE}",
        ) not in runner.items
    assert browser.callback_thread is not None
    browser.callback_thread.join(timeout=5)


@dataclass(slots=True)
class _FakeHttpResponse:
    body: bytes

    def read(self, amount: int = -1) -> bytes:
        return self.body[:amount]

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        del args


@dataclass(slots=True)
class _RecordingOpener:
    bodies: list[bytes]
    requests: list[urllib.request.Request] = field(default_factory=list)

    def __call__(
        self,
        request: urllib.request.Request,
        *,
        timeout: int,
    ) -> _FakeHttpResponse:
        assert timeout == 30
        self.requests.append(request)
        return _FakeHttpResponse(self.bodies.pop(0))


def _authorization(reference: KeychainSecretReference) -> TodoistAuthorization:
    return TodoistAuthorization(
        account_reference=ACCOUNT_REFERENCE,
        account_identity=ACCOUNT_IDENTITY,
        granted_scopes=frozenset({TODOIST_DATA_READ_SCOPE}),
        credential_reference=reference.identifier,
    )


def test_todoist_http_transport_reaches_only_approved_get_resources() -> None:
    keychain, _runner = _keychain()
    reference = KeychainSecretReference(
        KEYCHAIN_SERVICE,
        f"{TODOIST_CONNECTOR}:access-token:{ACCOUNT_REFERENCE}",
    )
    keychain.store(reference, "synthetic-access-token")
    opener = _RecordingOpener(
        [
            json.dumps(
                {
                    "id": "user-1",
                    "email": ACCOUNT_IDENTITY,
                    "token": "provider-personal-token-must-be-ignored",
                    "tz_info": {"timezone": "America/New_York"},
                }
            ).encode(),
            json.dumps(
                {
                    "results": [
                        {
                            "id": "task-1",
                            "content": "Synthetic task",
                            "priority": 1,
                            "project_id": "project-1",
                            "section_id": "section-1",
                            "labels": ["Selected"],
                            "responsible_uid": "user-1",
                            "added_at": "2026-07-20T12:00:00Z",
                            "updated_at": "2026-07-25T12:00:00Z",
                            "due": {
                                "date": "2026-07-27",
                                "is_recurring": False,
                            },
                        }
                    ],
                    "next_cursor": None,
                }
            ).encode(),
            json.dumps(
                {
                    "id": "project-1",
                    "name": "Synthetic project",
                    "is_shared": True,
                    "can_assign_tasks": True,
                }
            ).encode(),
            json.dumps(
                {
                    "id": "section-1",
                    "project_id": "project-1",
                    "name": "Synthetic section",
                }
            ).encode(),
            json.dumps(
                {
                    "results": [{"id": "label-1", "name": "Selected"}],
                    "next_cursor": None,
                }
            ).encode(),
        ]
    )
    transport = TodoistHttpTransport(
        keychain=keychain,
        access_token_reference=reference,
        url_opener=opener,
    )
    authorization = _authorization(reference)

    user = transport.get_authenticated_user(authorization)
    task_page = transport.list_tasks(
        authorization,
        TodoistPageRequest(cursor=None),
    )
    project = transport.get_project(authorization, "project-1")
    section = transport.get_section(authorization, "section-1")
    label_page = transport.list_labels(
        authorization,
        TodoistPageRequest(cursor=None),
    )

    assert user.email == ACCOUNT_IDENTITY
    assert task_page.tasks[0].priority == 1
    assert project.id == "project-1"
    assert project.is_shared
    assert project.can_assign_tasks
    assert section.id == "section-1"
    assert label_page.labels[0].id == "label-1"
    assert all(request.get_method() == "GET" for request in opener.requests)
    paths = [
        urllib.parse.urlsplit(request.full_url).path for request in opener.requests
    ]
    assert paths == [
        "/api/v1/user",
        "/api/v1/tasks",
        "/api/v1/projects/project-1",
        "/api/v1/sections/section-1",
        "/api/v1/labels",
    ]
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
        assert not hasattr(transport, operation)


def test_priority_probe_verifies_endpoint_mapping_and_stable_pagination() -> None:
    keychain, _runner = _keychain()
    reference = KeychainSecretReference(
        KEYCHAIN_SERVICE,
        f"{TODOIST_CONNECTOR}:access-token:{ACCOUNT_REFERENCE}",
    )
    keychain.store(reference, "synthetic-access-token")
    opener = _RecordingOpener(
        [
            _task_page_bytes("p1-a", priority=4, next_cursor="opaque-next"),
            _task_page_bytes("p1-b", priority=4),
            _task_page_bytes("p2-a", priority=3),
        ]
    )
    result = verify_todoist_priority_semantics(
        TodoistHttpTransport(
            keychain=keychain,
            access_token_reference=reference,
            url_opener=opener,
        ),
        _authorization(reference),
    )

    assert result.mapping == (("P1", 4), ("P2", 3), ("P3", 2), ("P4", 1))
    assert result.p1_task_count == 2
    assert result.p2_task_count == 1
    assert result.page_count == 3
    queries = [
        urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        for request in opener.requests
    ]
    assert queries == [
        {"limit": ["200"], "query": ["p1"]},
        {"cursor": ["opaque-next"], "limit": ["200"], "query": ["p1"]},
        {"limit": ["200"], "query": ["p2"]},
    ]


def test_priority_probe_stops_on_semantic_conflict() -> None:
    keychain, _runner = _keychain()
    reference = KeychainSecretReference(
        KEYCHAIN_SERVICE,
        f"{TODOIST_CONNECTOR}:access-token:{ACCOUNT_REFERENCE}",
    )
    keychain.store(reference, "synthetic-access-token")
    opener = _RecordingOpener(
        [
            _task_page_bytes("p1-wrong", priority=1),
            _task_page_bytes("p2-wrong", priority=2),
        ]
    )

    with pytest.raises(TodoistPrioritySemanticConflict):
        verify_todoist_priority_semantics(
            TodoistHttpTransport(
                keychain=keychain,
                access_token_reference=reference,
                url_opener=opener,
            ),
            _authorization(reference),
        )


def _task_page_bytes(
    task_id: str,
    *,
    priority: int,
    next_cursor: str | None = None,
) -> bytes:
    return json.dumps(
        {
            "results": [
                {
                    "id": task_id,
                    "content": "Synthetic task",
                    "priority": priority,
                    "labels": [],
                }
            ],
            "next_cursor": next_cursor,
        }
    ).encode()


@dataclass(slots=True)
class _RateLimitedOpener:
    def __call__(
        self,
        request: urllib.request.Request,
        *,
        timeout: int,
    ) -> _FakeHttpResponse:
        del request, timeout
        raise urllib.error.HTTPError(
            url="https://api.todoist.com/api/v1/user",
            code=429,
            msg="rate limited",
            hdrs=Message(),
            fp=None,
        )


def test_todoist_http_transport_discloses_rate_limit_without_payload() -> None:
    keychain, _runner = _keychain()
    reference = KeychainSecretReference(
        KEYCHAIN_SERVICE,
        f"{TODOIST_CONNECTOR}:access-token:{ACCOUNT_REFERENCE}",
    )
    keychain.store(reference, "synthetic-access-token")
    transport = TodoistHttpTransport(
        keychain=keychain,
        access_token_reference=reference,
        url_opener=_RateLimitedOpener(),
    )

    with pytest.raises(TodoistRateLimitError):
        transport.get_authenticated_user(_authorization(reference))
