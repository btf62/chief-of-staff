"""OAuth and bounded Asana workspace/project discovery contract tests."""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chief_of_staff.asana_live_cli import (
    _read_client_credentials,
    _read_interactive_client_credentials,
)
from chief_of_staff.auth.asana_oauth import (
    ASANA_APPLICATION_NAME,
    ASANA_DISCOVERY_SCOPE_STRING,
    ASANA_DISCOVERY_SCOPES,
    ASANA_REDIRECT_URI,
    AsanaAccountConfirmationError,
    AsanaAuthorizationResult,
    AsanaInstalledAppOAuth,
    AsanaOAuthClientRegistrar,
    AsanaOAuthStateMismatch,
    AsanaOAuthTokenResponse,
    AsanaTokenInspection,
    _pkce_challenge,
)
from chief_of_staff.auth.keychain import (
    MacOSKeychain,
    SecurityCommandResult,
)
from chief_of_staff.connectors import (
    ASANA_PROJECT_FIELDS,
    ASANA_WORKSPACE_FIELDS,
    AsanaDiscovery,
    AsanaDiscoveryAuthorization,
    AsanaDiscoveryAuthorizationUnavailable,
    AsanaDiscoveryPaginationError,
    AsanaDiscoveryService,
    AsanaDiscoveryTrialRunner,
    AsanaProject,
    AsanaProjectPage,
    AsanaProjectRequest,
    AsanaWorkspace,
    AsanaWorkspacePage,
    AsanaWorkspaceRequest,
)
from chief_of_staff.connectors.instances import ASANA_PRIMARY_INSTANCE
from chief_of_staff.domain import AuthorizationStatus, CredentialHealth
from chief_of_staff.persistence import Database, StateStore

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
ACCOUNT_IDENTITY = "synthetic-asana@example.invalid"
WORKSPACE_GID = "9000000000000001"
WORKSPACE_NAME = "Synthetic Private Workspace"
PROJECT_GID = "8000000000000001"
PROJECT_NAME = "Synthetic Private Project"
ACCESS_TOKEN = "synthetic-asana-access-token"
REFRESH_TOKEN = "synthetic-asana-refresh-token"
CLIENT_SECRET = "synthetic-asana-client-secret"


@dataclass(slots=True)
class _MemorySecurityRunner:
    values: dict[tuple[str, str], str] = field(default_factory=dict)

    def __call__(
        self,
        arguments: tuple[str, ...],
        *,
        input_text: str | None,
        capture_output: bool,
    ) -> SecurityCommandResult:
        account = arguments[arguments.index("-a") + 1]
        service = arguments[arguments.index("-s") + 1]
        key = (service, account)
        command = arguments[0]
        if command == "add-generic-password":
            assert input_text is not None
            self.values[key] = input_text.rstrip("\n")
            return SecurityCommandResult(0)
        if command == "find-generic-password":
            if key not in self.values:
                return SecurityCommandResult(44)
            return SecurityCommandResult(
                0,
                self.values[key] + "\n" if capture_output else "",
            )
        if command == "delete-generic-password":
            return SecurityCommandResult(
                0 if self.values.pop(key, None) is not None else 44
            )
        raise AssertionError("unexpected Keychain command")


@dataclass(slots=True)
class _CallbackRunner:
    mismatch: bool = False
    authorization_url: str | None = None
    code_challenge: str | None = None

    def run(
        self,
        *,
        authorization_url: str,
        expected_state: str,
        timeout_seconds: int,
        browser_opener: object,
    ) -> dict[str, str]:
        del timeout_seconds, browser_opener
        self.authorization_url = authorization_url
        query = urllib.parse.parse_qs(urllib.parse.urlparse(authorization_url).query)
        assert query["scope"] == [ASANA_DISCOVERY_SCOPE_STRING]
        assert query["redirect_uri"] == [ASANA_REDIRECT_URI]
        assert query["response_type"] == ["code"]
        assert query["code_challenge_method"] == ["S256"]
        assert query["state"] == [expected_state]
        self.code_challenge = query["code_challenge"][0]
        return {
            "code": "synthetic-one-time-code",
            "state": "mismatched-state" if self.mismatch else expected_state,
        }


@dataclass(slots=True)
class _TokenClient:
    callback: _CallbackRunner
    exchanges: int = 0
    refreshes: int = 0
    revocations: int = 0

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> AsanaOAuthTokenResponse:
        assert client_id == "synthetic-client-id"
        assert client_secret == CLIENT_SECRET
        assert code == "synthetic-one-time-code"
        assert redirect_uri == ASANA_REDIRECT_URI
        assert self.callback.code_challenge == _pkce_challenge(code_verifier)
        self.exchanges += 1
        return AsanaOAuthTokenResponse(
            access_token=ACCESS_TOKEN,
            refresh_token=REFRESH_TOKEN,
            expires_in_seconds=3600,
            identity_gid="7000000000000001",
            identity_name="Synthetic User",
            identity_email=ACCOUNT_IDENTITY,
        )

    def inspect(self, *, token: str) -> AsanaTokenInspection:
        assert token == ACCESS_TOKEN
        return AsanaTokenInspection(
            active=True,
            token_type="bearer",
            scopes=ASANA_DISCOVERY_SCOPES,
            expires_in_seconds=3600,
        )

    def refresh(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> AsanaOAuthTokenResponse:
        assert client_id == "synthetic-client-id"
        assert client_secret == CLIENT_SECRET
        assert refresh_token == REFRESH_TOKEN
        self.refreshes += 1
        return AsanaOAuthTokenResponse(
            access_token=ACCESS_TOKEN,
            refresh_token=REFRESH_TOKEN,
            expires_in_seconds=3600,
            identity_gid="7000000000000001",
            identity_name="Synthetic User",
            identity_email=ACCOUNT_IDENTITY,
        )

    def revoke(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> None:
        assert client_id == "synthetic-client-id"
        assert client_secret == CLIENT_SECRET
        assert refresh_token == REFRESH_TOKEN
        self.revocations += 1


@dataclass(frozen=True, slots=True)
class _AuthorizationProvider:
    def get_authorization(self) -> AsanaDiscoveryAuthorization:
        return AsanaDiscoveryAuthorization(
            account_reference="primary-user",
            account_identity=ACCOUNT_IDENTITY,
            granted_scopes=ASANA_DISCOVERY_SCOPES,
            credential_reference="synthetic-reference",
            access_token=ACCESS_TOKEN,
        )


@dataclass(frozen=True, slots=True)
class _UnavailableAuthorizationProvider:
    def get_authorization(self) -> AsanaDiscoveryAuthorization:
        raise AsanaDiscoveryAuthorizationUnavailable


@dataclass(slots=True)
class _DiscoveryTransport:
    workspace_pages: tuple[AsanaWorkspacePage, ...]
    project_pages: tuple[AsanaProjectPage, ...] = ()
    workspace_calls: list[AsanaWorkspaceRequest] = field(default_factory=list)
    project_calls: list[AsanaProjectRequest] = field(default_factory=list)

    def list_workspaces(
        self,
        authorization: AsanaDiscoveryAuthorization,
        request: AsanaWorkspaceRequest,
    ) -> AsanaWorkspacePage:
        assert authorization.access_token == ACCESS_TOKEN
        self.workspace_calls.append(request)
        return self.workspace_pages[len(self.workspace_calls) - 1]

    def list_projects(
        self,
        authorization: AsanaDiscoveryAuthorization,
        request: AsanaProjectRequest,
    ) -> AsanaProjectPage:
        assert authorization.access_token == ACCESS_TOKEN
        self.project_calls.append(request)
        return self.project_pages[len(self.project_calls) - 1]


def _workspace(
    gid: str = WORKSPACE_GID,
    name: str = WORKSPACE_NAME,
) -> AsanaWorkspace:
    return AsanaWorkspace(gid=gid, name=name, is_organization=True)


def _project(
    gid: str = PROJECT_GID,
    name: str = PROJECT_NAME,
) -> AsanaProject:
    return AsanaProject(
        gid=gid,
        name=name,
        archived=False,
        public=False,
        permalink_url=f"https://app.asana.com/0/{gid}/list",
    )


def _keychain() -> tuple[MacOSKeychain, _MemorySecurityRunner]:
    runner = _MemorySecurityRunner()
    return MacOSKeychain(command_runner=runner), runner


def _register_and_authorize(
    store: StateStore,
    keychain: MacOSKeychain,
    callback: _CallbackRunner,
) -> tuple[AsanaAuthorizationResult, _TokenClient]:
    AsanaOAuthClientRegistrar(
        keychain=keychain,
        state_store=store,
        clock=lambda: NOW,
    ).register(
        application_name=ASANA_APPLICATION_NAME,
        application_owner="Northridge-approved synthetic owner",
        client_id="synthetic-client-id",
        client_secret=CLIENT_SECRET,
    )
    token_client = _TokenClient(callback)
    result = AsanaInstalledAppOAuth(
        keychain=keychain,
        state_store=store,
        token_client=token_client,
        callback_runner=callback,
        clock=lambda: NOW,
        browser_opener=lambda _url: None,
    ).authorize_interactively(
        account_reference="primary-user",
        confirmed_account_identity=ACCOUNT_IDENTITY,
    )
    return result, token_client


def test_discovery_scopes_are_exact_and_exclude_broader_access() -> None:
    assert {
        "workspaces:read",
        "projects:read",
    } == ASANA_DISCOVERY_SCOPES
    prohibited = {
        "tasks:read",
        "users:read",
        "openid",
        "email",
        "profile",
        "tasks:write",
        "tasks:delete",
        "default",
    }
    assert ASANA_DISCOVERY_SCOPES.isdisjoint(prohibited)


def test_interactive_client_registration_hides_both_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []
    values = iter((" synthetic-client-id ", CLIENT_SECRET))

    def read_hidden(prompt: str) -> str:
        prompts.append(prompt)
        return next(values)

    monkeypatch.setattr(
        "chief_of_staff.asana_live_cli.getpass.getpass",
        read_hidden,
    )

    assert _read_interactive_client_credentials() == (
        "synthetic-client-id",
        CLIENT_SECRET,
    )
    assert prompts == [
        "Asana client ID: ",
        "Asana client secret (stored only in macOS Keychain): ",
    ]


def test_controlled_stdin_client_registration_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.stdin",
        type("_Input", (), {"read": lambda _self, _size: ""})(),
    )
    with pytest.raises(ValueError):
        _read_client_credentials()


def test_oauth_validates_state_pkce_identity_and_keeps_tokens_in_keychain(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    keychain, keychain_runner = _keychain()
    callback = _CallbackRunner()
    with Database.open(database_path) as database:
        store = StateStore(database)
        result, token_client = _register_and_authorize(store, keychain, callback)
        stored = store.get_connector_authorization(ASANA_PRIMARY_INSTANCE)

        assert stored == result.metadata
        assert token_client.exchanges == 1
        assert result.account_identity_source == "user-confirmed-and-api-verified"
        assert stored is not None
        assert stored.authorization_status is AuthorizationStatus.AUTHORIZED
        assert stored.credential_health is CredentialHealth.HEALTHY
        assert stored.refresh_health is CredentialHealth.HEALTHY
        assert ACCESS_TOKEN in keychain_runner.values.values()
        assert REFRESH_TOKEN in keychain_runner.values.values()
        database_bytes = database_path.read_bytes()
        for secret in (ACCESS_TOKEN, REFRESH_TOKEN, CLIENT_SECRET):
            assert secret.encode() not in database_bytes


def test_oauth_rejects_state_and_wrong_account_before_persistence(
    tmp_path: Path,
) -> None:
    keychain, _runner = _keychain()
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        registrar = AsanaOAuthClientRegistrar(
            keychain=keychain,
            state_store=store,
            clock=lambda: NOW,
        )
        registrar.register(
            application_name=ASANA_APPLICATION_NAME,
            application_owner="synthetic owner",
            client_id="synthetic-client-id",
            client_secret=CLIENT_SECRET,
        )
        mismatched = _CallbackRunner(mismatch=True)
        with pytest.raises(AsanaOAuthStateMismatch):
            AsanaInstalledAppOAuth(
                keychain=keychain,
                state_store=store,
                token_client=_TokenClient(mismatched),
                callback_runner=mismatched,
                browser_opener=lambda _url: None,
            ).authorize_interactively(
                account_reference="primary-user",
                confirmed_account_identity=ACCOUNT_IDENTITY,
            )
        callback = _CallbackRunner()
        wrong_account_client = _TokenClient(callback)
        with pytest.raises(AsanaAccountConfirmationError):
            AsanaInstalledAppOAuth(
                keychain=keychain,
                state_store=store,
                token_client=wrong_account_client,
                callback_runner=callback,
                browser_opener=lambda _url: None,
            ).authorize_interactively(
                account_reference="primary-user",
                confirmed_account_identity="wrong@example.invalid",
            )
        assert wrong_account_client.revocations == 1
        assert store.get_connector_authorization(ASANA_PRIMARY_INSTANCE) is None


def test_refresh_disconnect_and_reauthorization_are_instance_scoped(
    tmp_path: Path,
) -> None:
    keychain, keychain_runner = _keychain()
    callback = _CallbackRunner()
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        _result, token_client = _register_and_authorize(store, keychain, callback)
        oauth = AsanaInstalledAppOAuth(
            keychain=keychain,
            state_store=store,
            token_client=token_client,
            callback_runner=callback,
            clock=lambda: NOW,
            browser_opener=lambda _url: None,
        )

        refreshed = oauth.refresh_authorization(account_reference="primary-user")
        assert refreshed.credential_health is CredentialHealth.HEALTHY
        assert token_client.refreshes == 1

        oauth.disconnect()
        assert token_client.revocations == 1
        assert store.get_connector_authorization(ASANA_PRIMARY_INSTANCE) is None
        assert store.get_oauth_client(ASANA_PRIMARY_INSTANCE) is not None
        assert ACCESS_TOKEN not in keychain_runner.values.values()
        assert REFRESH_TOKEN not in keychain_runner.values.values()

        reauthorized = oauth.authorize_interactively(
            account_reference="primary-user",
            confirmed_account_identity=ACCOUNT_IDENTITY,
        )
        assert reauthorized.metadata.authorization_status is (
            AuthorizationStatus.AUTHORIZED
        )


def test_workspace_pagination_and_multiple_workspace_stop_before_projects() -> None:
    transport = _DiscoveryTransport(
        workspace_pages=(
            AsanaWorkspacePage(
                workspaces=(_workspace(),),
                next_offset="provider-workspace-offset",
            ),
            AsanaWorkspacePage(
                workspaces=(
                    _workspace(
                        gid="9000000000000002",
                        name="Second Synthetic Workspace",
                    ),
                )
            ),
        ),
    )

    _authorization, discovery = AsanaDiscoveryService(
        authorization_provider=_AuthorizationProvider(),
        transport=transport,
    ).discover()

    assert len(discovery.workspaces) == 2
    assert discovery.workspace_page_count == 2
    assert not discovery.project_discovery_performed
    assert transport.project_calls == []
    assert [call.offset for call in transport.workspace_calls] == [
        None,
        "provider-workspace-offset",
    ]
    assert all(
        call.fields == ASANA_WORKSPACE_FIELDS for call in transport.workspace_calls
    )


def test_single_workspace_permits_minimal_paginated_project_discovery() -> None:
    transport = _DiscoveryTransport(
        workspace_pages=(AsanaWorkspacePage(workspaces=(_workspace(),)),),
        project_pages=(
            AsanaProjectPage(
                projects=(_project(),),
                next_offset="provider-project-offset",
            ),
            AsanaProjectPage(
                projects=(
                    _project(
                        gid="8000000000000002",
                        name="Second Synthetic Project",
                    ),
                )
            ),
        ),
    )

    _authorization, discovery = AsanaDiscoveryService(
        authorization_provider=_AuthorizationProvider(),
        transport=transport,
    ).discover()

    assert discovery.project_discovery_performed
    assert discovery.project_page_count == 2
    assert len(discovery.projects) == 2
    assert [call.offset for call in transport.project_calls] == [
        None,
        "provider-project-offset",
    ]
    assert all(not call.archived for call in transport.project_calls)
    assert all(call.fields == ASANA_PROJECT_FIELDS for call in transport.project_calls)


def test_duplicate_gids_are_deduplicated_only_when_identical() -> None:
    duplicate = _workspace()
    service = AsanaDiscoveryService(
        authorization_provider=_AuthorizationProvider(),
        transport=_DiscoveryTransport(
            workspace_pages=(
                AsanaWorkspacePage(
                    workspaces=(duplicate,),
                    next_offset="next",
                ),
                AsanaWorkspacePage(workspaces=(duplicate,)),
            ),
            project_pages=(AsanaProjectPage(projects=()),),
        ),
    )

    _authorization, discovery = service.discover()

    assert len(discovery.workspaces) == 1
    assert discovery.duplicate_workspace_count == 1

    conflicting = AsanaDiscoveryService(
        authorization_provider=_AuthorizationProvider(),
        transport=_DiscoveryTransport(
            workspace_pages=(
                AsanaWorkspacePage(
                    workspaces=(duplicate,),
                    next_offset="next",
                ),
                AsanaWorkspacePage(
                    workspaces=(_workspace(name="Conflicting Synthetic Workspace"),)
                ),
            )
        ),
    )
    with pytest.raises(AsanaDiscoveryPaginationError):
        conflicting.discover()


def test_authorization_failure_is_distinct_from_empty_workspace_discovery() -> None:
    with pytest.raises(AsanaDiscoveryAuthorizationUnavailable):
        AsanaDiscoveryService(
            authorization_provider=_UnavailableAuthorizationProvider(),
            transport=_DiscoveryTransport(workspace_pages=()),
        ).discover()
    _authorization, empty = AsanaDiscoveryService(
        authorization_provider=_AuthorizationProvider(),
        transport=_DiscoveryTransport(
            workspace_pages=(AsanaWorkspacePage(workspaces=()),)
        ),
    ).discover()
    assert empty.workspaces == ()
    assert empty.workspace_page_count == 1
    assert not empty.project_discovery_performed


def test_trial_persists_only_allowed_metadata_and_private_report(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    keychain, _keychain_runner = _keychain()
    callback = _CallbackRunner()
    transport = _DiscoveryTransport(
        workspace_pages=(AsanaWorkspacePage(workspaces=(_workspace(),)),),
        project_pages=(
            AsanaProjectPage(
                projects=(_project(),),
                next_offset="transient-project-offset",
            ),
            AsanaProjectPage(
                projects=(
                    _project(
                        gid="8000000000000002",
                        name="Second Synthetic Project",
                    ),
                )
            ),
        ),
    )
    with Database.open(database_path) as database:
        store = StateStore(database)
        authorization, _token_client = _register_and_authorize(
            store,
            keychain,
            callback,
        )
        report = AsanaDiscoveryTrialRunner(
            state_store=store,
            discovery_service=AsanaDiscoveryService(
                authorization_provider=_AuthorizationProvider(),
                transport=transport,
            ),
            output_directory=tmp_path / ".local/asana",
            application_name=ASANA_APPLICATION_NAME,
            application_owner="Northridge-approved synthetic owner",
            account_identity_source=authorization.account_identity_source,
            clock=lambda: NOW,
        ).run()

        private_report = report.private_report_path.read_text(encoding="utf-8")
        assert WORKSPACE_NAME in private_report
        assert WORKSPACE_GID in private_report
        assert PROJECT_NAME in private_report
        assert PROJECT_GID in private_report
        assert "Task endpoint called: false" in private_report
        assert report.private_report_path.stat().st_mode & 0o777 == 0o600
        assert not report.task_endpoint_called
        assert report.project_discovery_performed
        assert report.project_count == 2
        database_bytes = database_path.read_bytes()
        assert WORKSPACE_NAME.encode() not in database_bytes
        assert PROJECT_NAME.encode() not in database_bytes
        assert b"transient-project-offset" not in database_bytes
        assert ACCESS_TOKEN.encode() not in database_bytes
        assert REFRESH_TOKEN.encode() not in database_bytes
        assert (
            database.connection.execute(
                "SELECT count(*) FROM connector_runs WHERE source = 'asana_discovery'"
            ).fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute(
                "SELECT count(*) FROM source_evidence WHERE source = 'asana_discovery'"
            ).fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute(
                "SELECT count(*) FROM connector_resources WHERE provider = 'asana'"
            ).fetchone()[0]
            == 1
        )


def test_discovery_surface_has_no_task_or_mutation_operation() -> None:
    transport = _DiscoveryTransport(
        workspace_pages=(AsanaWorkspacePage(workspaces=()),)
    )
    service = AsanaDiscoveryService(
        authorization_provider=_AuthorizationProvider(),
        transport=transport,
    )
    for operation in (
        "list_tasks",
        "search_tasks",
        "get_users",
        "create",
        "update",
        "delete",
        "write",
    ):
        assert not hasattr(transport, operation)
        assert not hasattr(service, operation)


def test_private_names_do_not_leak_through_discovery_representation() -> None:
    discovery = AsanaDiscovery(
        workspaces=(_workspace(),),
        projects=(_project(),),
        workspace_page_count=1,
        project_page_count=1,
        project_discovery_performed=True,
    )
    assert WORKSPACE_NAME not in repr(discovery)
    assert PROJECT_NAME not in repr(discovery)


def test_sqlite_schema_contains_no_raw_payload_or_offset_columns(
    tmp_path: Path,
) -> None:
    with Database.open(tmp_path / "schema.sqlite3") as database:
        columns = {
            str(row["name"])
            for table in (
                "connector_runs",
                "source_evidence",
                "connector_resources",
            )
            for row in database.connection.execute(
                "SELECT name FROM pragma_table_info(?)",
                (table,),
            )
        }
    assert "raw_payload" not in columns
    assert "offset" not in columns
