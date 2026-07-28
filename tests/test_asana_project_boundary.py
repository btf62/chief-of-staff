"""Exact-project Asana boundary and persistence tests."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path

import pytest

from chief_of_staff.asana_live_cli import main as asana_live_main
from chief_of_staff.auth.asana_oauth import (
    ASANA_APPLICATION_NAME,
    ASANA_CONNECTOR,
    ASANA_DISCOVERY_SCOPE_STRING,
    ASANA_DISCOVERY_SCOPES,
)
from chief_of_staff.connectors.asana_discovery import (
    AsanaDiscoveryAuthorization,
    AsanaDiscoveryPermissionError,
)
from chief_of_staff.connectors.asana_project_boundary import (
    ASANA_EXACT_PROJECT_BOUNDARY,
    ASANA_EXACT_PROJECT_FIELDS,
    ASANA_EXACT_PROJECT_RESOURCE_REFERENCE,
    AsanaExactProjectHttpTransport,
    AsanaExactProjectReference,
    AsanaExactProjectRequest,
    AsanaExactProjectTrialRunner,
    AsanaExactProjectVerificationService,
    AsanaVerifiedProject,
    parse_approved_asana_project_url,
)
from chief_of_staff.connectors.instances import ASANA_PRIMARY_INSTANCE
from chief_of_staff.domain import (
    AuthorizationStatus,
    ConnectorAuthorizationMetadata,
    ConnectorDomain,
    ConnectorInstanceMetadata,
    ConnectorResourceMetadata,
    CredentialHealth,
    OAuthClientMetadata,
)
from chief_of_staff.persistence import Database, StateStore

NOW = datetime(2026, 7, 28, 18, 0, tzinfo=UTC)
WORKSPACE_GID = "1111111111111111"
PROJECT_GID = "2222222222222222"
VIEW_GID = "3333333333333333"
PROJECT_NAME = "Synthetic Approved Project"
APPROVED_URL = (
    f"https://app.asana.com/1/{WORKSPACE_GID}/project/{PROJECT_GID}/board/{VIEW_GID}"
)
PERMALINK = f"https://app.asana.com/0/{PROJECT_GID}/list"


@dataclass(slots=True)
class _AuthorizationProvider:
    def get_authorization(self) -> AsanaDiscoveryAuthorization:
        return AsanaDiscoveryAuthorization(
            account_reference="primary-user",
            account_identity="synthetic@example.invalid",
            granted_scopes=ASANA_DISCOVERY_SCOPES,
            credential_reference="synthetic-keychain-reference",
            access_token="synthetic-access-token",
        )


@dataclass(slots=True)
class _ExactProjectTransport:
    project: AsanaVerifiedProject
    calls: list[AsanaExactProjectRequest] = field(default_factory=list)

    def get_project(
        self,
        authorization: AsanaDiscoveryAuthorization,
        request: AsanaExactProjectRequest,
    ) -> AsanaVerifiedProject:
        assert authorization.granted_scopes == ASANA_DISCOVERY_SCOPES
        self.calls.append(request)
        return self.project


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = json.dumps(payload).encode()

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self.payload


def _project(
    *,
    gid: str = PROJECT_GID,
    workspace_gid: str = WORKSPACE_GID,
    archived: bool = False,
) -> AsanaVerifiedProject:
    return AsanaVerifiedProject(
        gid=gid,
        workspace_gid=workspace_gid,
        name=PROJECT_NAME,
        archived=archived,
        public=False,
        permalink_url=PERMALINK,
    )


def _reference() -> AsanaExactProjectReference:
    return parse_approved_asana_project_url(APPROVED_URL)


def _prepare_store(store: StateStore) -> None:
    store.save_connector_instance(
        ConnectorInstanceMetadata(
            id=ASANA_PRIMARY_INSTANCE,
            provider=ASANA_CONNECTOR,
            alias="Asana",
            domain_classification=ConnectorDomain.WORK,
            approved_resource_boundary="superseded workspace boundary",
            approved_scopes=ASANA_DISCOVERY_SCOPE_STRING,
            retrieval_configuration="approved-workspace-active-project-discovery",
            enabled=True,
            retention_policy_reference="adr-0004-discovery-only",
            created_at=NOW - timedelta(hours=1),
            updated_at=NOW - timedelta(hours=1),
        )
    )
    store.save_oauth_client(
        OAuthClientMetadata(
            connector=ASANA_CONNECTOR,
            connector_instance_id=ASANA_PRIMARY_INSTANCE,
            oauth_project_id=ASANA_APPLICATION_NAME,
            oauth_client_id="synthetic-client-id",
            credential_service="synthetic-keychain",
            client_secret_account="asana:client-secret",
            configured_at=NOW - timedelta(hours=1),
            application_owner="Synthetic sole owner",
            oauth_grant_type="authorization_code",
        )
    )
    store.save_connector_authorization(
        ConnectorAuthorizationMetadata(
            connector=ASANA_CONNECTOR,
            connector_instance_id=ASANA_PRIMARY_INSTANCE,
            account_reference="primary-user",
            account_identity="synthetic@example.invalid",
            granted_scope=ASANA_DISCOVERY_SCOPE_STRING,
            credential_service="synthetic-keychain",
            access_token_account="asana:access",
            refresh_token_account="asana:refresh",
            authorization_status=AuthorizationStatus.AUTHORIZED,
            credential_health=CredentialHealth.HEALTHY,
            refresh_health=CredentialHealth.HEALTHY,
            token_expires_at=NOW + timedelta(hours=1),
            authorized_at=NOW - timedelta(hours=1),
            updated_at=NOW - timedelta(hours=1),
        )
    )
    store.save_connector_resource(
        ConnectorResourceMetadata(
            connector=ASANA_CONNECTOR,
            connector_instance_id=ASANA_PRIMARY_INSTANCE,
            resource_reference="approved-organization-workspace",
            resource_id="9999999999999999",
            resource_url="https://app.asana.com/0/9999999999999999/list",
            resource_type="workspace",
            grant_type="explicit-user-approval",
            selected_at=NOW - timedelta(hours=1),
        )
    )


def test_approved_url_parses_exact_project_and_ignores_view_as_authority() -> None:
    reference = parse_approved_asana_project_url(APPROVED_URL)

    assert reference.workspace_gid == WORKSPACE_GID
    assert reference.project_gid == PROJECT_GID
    assert VIEW_GID not in repr(reference)


@pytest.mark.parametrize(
    "url",
    (
        "http://app.asana.com/1/1/project/2/board/3",
        "https://evil.example/1/1/project/2/board/3",
        "https://app.asana.com/0/2/list",
        "https://app.asana.com/1/1/project/2/board/3?extra=true",
        "https://app.asana.com/1/1/project/2/board/3#private",
    ),
)
def test_approved_url_rejects_ambiguous_or_broader_forms(url: str) -> None:
    with pytest.raises(ValueError):
        parse_approved_asana_project_url(url)


@pytest.mark.parametrize(
    "retired_command",
    (
        "authorize-and-discover",
        "approve-workspace-and-discover-projects",
    ),
)
def test_workspace_wide_discovery_commands_are_no_longer_reachable(
    retired_command: str,
) -> None:
    with pytest.raises(SystemExit):
        asana_live_main([retired_command])


def test_verification_uses_one_exact_request_and_has_no_list_or_task_surface() -> None:
    transport = _ExactProjectTransport(project=_project())
    service = AsanaExactProjectVerificationService(
        authorization_provider=_AuthorizationProvider(),
        transport=transport,
        approved_reference=_reference(),
    )

    _authorization, project = service.verify()

    assert project.gid == PROJECT_GID
    assert len(transport.calls) == 1
    assert transport.calls[0].project_gid == PROJECT_GID
    assert transport.calls[0].expected_workspace_gid == WORKSPACE_GID
    for operation in (
        "list_workspaces",
        "list_projects",
        "list_tasks",
        "search_tasks",
        "create",
        "update",
        "delete",
        "write",
    ):
        assert not hasattr(transport, operation)
        assert not hasattr(service, operation)


@pytest.mark.parametrize(
    "project",
    (
        _project(gid="4444444444444444"),
        _project(workspace_gid="5555555555555555"),
        _project(archived=True),
    ),
)
def test_verification_rejects_mismatched_or_archived_project(
    project: AsanaVerifiedProject,
) -> None:
    with pytest.raises(AsanaDiscoveryPermissionError):
        AsanaExactProjectVerificationService(
            authorization_provider=_AuthorizationProvider(),
            transport=_ExactProjectTransport(project=project),
            approved_reference=_reference(),
        ).verify()


def test_http_transport_calls_only_exact_project_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[urllib.request.Request] = []

    def urlopen(
        request: urllib.request.Request,
        *,
        timeout: int,
    ) -> _Response:
        assert timeout == 30
        captured.append(request)
        return _Response(
            {
                "data": {
                    "gid": PROJECT_GID,
                    "workspace": {"gid": WORKSPACE_GID},
                    "name": PROJECT_NAME,
                    "archived": False,
                    "public": False,
                    "permalink_url": PERMALINK,
                }
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    project = AsanaExactProjectHttpTransport().get_project(
        _AuthorizationProvider().get_authorization(),
        AsanaExactProjectRequest(
            project_gid=PROJECT_GID,
            expected_workspace_gid=WORKSPACE_GID,
        ),
    )

    assert project.gid == PROJECT_GID
    assert len(captured) == 1
    request = captured[0]
    assert request.method == "GET"
    parsed = urllib.parse.urlsplit(request.full_url)
    assert parsed.path == f"/api/1.0/projects/{PROJECT_GID}"
    query = urllib.parse.parse_qs(parsed.query)
    assert query == {"opt_fields": [",".join(ASANA_EXACT_PROJECT_FIELDS)]}
    assert "/tasks" not in request.full_url
    assert "/workspaces" not in request.full_url


def test_http_transport_distinguishes_permission_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(
        request: urllib.request.Request,
        *,
        timeout: int,
    ) -> _Response:
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "Forbidden",
            hdrs=Message(),
            fp=None,
        )

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    with pytest.raises(AsanaDiscoveryPermissionError):
        AsanaExactProjectHttpTransport().get_project(
            _AuthorizationProvider().get_authorization(),
            AsanaExactProjectRequest(
                project_gid=PROJECT_GID,
                expected_workspace_gid=WORKSPACE_GID,
            ),
        )


def test_trial_replaces_workspace_binding_with_exact_project(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    transport = _ExactProjectTransport(project=_project())
    with Database.open(database_path) as database:
        store = StateStore(database)
        _prepare_store(store)

        report = AsanaExactProjectTrialRunner(
            state_store=store,
            verification_service=AsanaExactProjectVerificationService(
                authorization_provider=_AuthorizationProvider(),
                transport=transport,
                approved_reference=_reference(),
            ),
            output_directory=tmp_path / ".local/asana",
            application_name=ASANA_APPLICATION_NAME,
            application_owner="Synthetic sole owner",
            clock=lambda: NOW,
        ).run()

        resource = store.get_connector_resource(ASANA_PRIMARY_INSTANCE)
        assert resource is not None
        assert resource.resource_type == "project"
        assert resource.resource_id == PROJECT_GID
        assert resource.resource_reference == ASANA_EXACT_PROJECT_RESOURCE_REFERENCE
        assert resource.grant_type == "explicit-user-approval"
        instance = store.get_connector_instance(ASANA_PRIMARY_INSTANCE)
        assert instance is not None
        assert instance.approved_resource_boundary == ASANA_EXACT_PROJECT_BOUNDARY
        assert instance.retrieval_configuration == "exact-project-only"
        assert instance.approved_scopes == ASANA_DISCOVERY_SCOPE_STRING

        private_report = report.private_report_path.read_text(encoding="utf-8")
        assert PROJECT_NAME in private_report
        assert WORKSPACE_GID in private_report
        assert PROJECT_GID in private_report
        assert "prior workspace-wide active boundary is superseded" in private_report
        assert "obsolete Northridge boards have no active authority" in private_report
        assert "collaboration with 9 Embers on Rock RMS development" in private_report
        assert "Task endpoint called: false" in private_report
        assert report.private_report_path.stat().st_mode & 0o777 == 0o600

        database_bytes = database_path.read_bytes()
        assert PROJECT_NAME.encode() not in database_bytes
        assert b"synthetic-access-token" not in database_bytes
        assert (
            database.connection.execute(
                """
                SELECT count(*) FROM connector_runs
                WHERE source = 'asana_project_boundary_verification'
                """
            ).fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute(
                """
                SELECT count(*) FROM source_evidence
                WHERE source = 'asana_project_boundary_verification'
                """
            ).fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute(
                "SELECT count(*) FROM connector_resources WHERE provider = 'asana'"
            ).fetchone()[0]
            == 1
        )
        assert not report.task_endpoint_called
        assert not report.workspace_list_endpoint_called
        assert not report.project_list_endpoint_called
        assert not report.raw_payload_persisted
