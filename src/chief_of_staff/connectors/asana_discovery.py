"""Bounded Asana workspace and active-project discovery without task access."""

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
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Protocol, cast

from chief_of_staff.auth.asana_oauth import (
    ASANA_CONNECTOR,
    ASANA_DISCOVERY_SCOPE_STRING,
    ASANA_DISCOVERY_SCOPES,
)
from chief_of_staff.auth.keychain import (
    KeychainSecretNotFound,
    KeychainSecretReference,
    MacOSKeychain,
)
from chief_of_staff.connectors.instances import ASANA_PRIMARY_INSTANCE
from chief_of_staff.domain import (
    AuthorizationStatus,
    ConnectorResourceMetadata,
    ConnectorRun,
    ConnectorStatus,
    CoverageStatus,
    CredentialHealth,
    SourceEvidence,
)
from chief_of_staff.persistence import StateStore

ASANA_API_ROOT: Final = "https://app.asana.com/api/1.0"
ASANA_WORKSPACE_OPERATION: Final = "GET /api/1.0/workspaces"
ASANA_PROJECT_OPERATION: Final = "GET /api/1.0/workspaces/{workspace_gid}/projects"
ASANA_APPROVED_WORKSPACE_ALIAS: Final = "northridgerochester.com"
ASANA_PAGE_SIZE: Final = 100
ASANA_MAX_PAGES: Final = 20
ASANA_WORKSPACE_FIELDS: Final = ("gid", "name", "is_organization")
ASANA_PROJECT_FIELDS: Final = (
    "gid",
    "name",
    "archived",
    "public",
    "permalink_url",
)
MAX_ASANA_RESPONSE_BYTES: Final = 4 * 1024 * 1024


class AsanaDiscoveryError(RuntimeError):
    """Base error for the bounded Asana discovery gate."""


class AsanaDiscoveryAuthorizationUnavailable(AsanaDiscoveryError):
    """Raised when no healthy exact-scope grant is present."""


class AsanaDiscoveryAuthenticationError(AsanaDiscoveryError):
    """Raised when Asana rejects the current credential."""


class AsanaDiscoveryPermissionError(AsanaDiscoveryError):
    """Raised when the exact discovery scope cannot access the endpoint."""


class AsanaDiscoveryRateLimitError(AsanaDiscoveryError):
    """Raised when the provider rate-limits bounded discovery."""


class AsanaDiscoveryRetrievalError(AsanaDiscoveryError):
    """Raised when one provider page is unavailable or invalid."""


class AsanaDiscoveryTimeoutError(AsanaDiscoveryRetrievalError):
    """Raised when Asana does not complete the approved endpoint in time."""


class AsanaDiscoveryPaginationError(AsanaDiscoveryError):
    """Raised for repeated, empty, conflicting, or excessive offsets."""


@dataclass(frozen=True, slots=True)
class AsanaDiscoveryAuthorization:
    """Exact-scope authorization with its secret hidden from representation."""

    account_reference: str
    account_identity: str
    granted_scopes: frozenset[str]
    credential_reference: str
    access_token: str = field(repr=False)
    connector_instance_id: str = ASANA_PRIMARY_INSTANCE


class AsanaDiscoveryAuthorizationProvider(Protocol):
    """Return one stored discovery authorization."""

    def get_authorization(self) -> AsanaDiscoveryAuthorization:
        """Return the exact approved instance without exposing it in output."""


@dataclass(frozen=True, slots=True)
class AsanaWorkspace:
    """Minimal workspace identity permitted in memory and private report."""

    gid: str
    name: str
    is_organization: bool

    def __post_init__(self) -> None:
        if not self.gid.strip() or not self.name.strip():
            raise ValueError("Asana workspace identity must not be empty")


@dataclass(frozen=True, slots=True)
class AsanaProject:
    """Minimal active-project facts permitted in memory and private report."""

    gid: str
    name: str
    archived: bool
    public: bool
    permalink_url: str

    def __post_init__(self) -> None:
        if not self.gid.strip() or not self.name.strip():
            raise ValueError("Asana project identity must not be empty")
        if not self.permalink_url.startswith("https://"):
            raise ValueError("Asana project permalink must use HTTPS")


@dataclass(frozen=True, slots=True)
class AsanaWorkspaceRequest:
    """Stable workspace pagination request."""

    limit: int
    fields: tuple[str, ...]
    offset: str | None = None


@dataclass(frozen=True, slots=True)
class AsanaProjectRequest:
    """Stable active-project pagination request for one workspace."""

    workspace_gid: str
    archived: bool
    limit: int
    fields: tuple[str, ...]
    offset: str | None = None


@dataclass(frozen=True, slots=True)
class AsanaWorkspacePage:
    """One provider page with an opaque transient continuation offset."""

    workspaces: tuple[AsanaWorkspace, ...]
    next_offset: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class AsanaProjectPage:
    """One provider page with an opaque transient continuation offset."""

    projects: tuple[AsanaProject, ...]
    next_offset: str | None = field(default=None, repr=False)


class AsanaDiscoveryTransport(Protocol):
    """The complete live API surface for the approved discovery."""

    def list_workspaces(
        self,
        authorization: AsanaDiscoveryAuthorization,
        request: AsanaWorkspaceRequest,
    ) -> AsanaWorkspacePage:
        """Retrieve one minimal workspace page."""

    def list_projects(
        self,
        authorization: AsanaDiscoveryAuthorization,
        request: AsanaProjectRequest,
    ) -> AsanaProjectPage:
        """Retrieve one minimal active-project page."""


class AsanaProjectDiscoveryTransport(Protocol):
    """The complete API surface for approved-workspace project discovery."""

    def list_projects(
        self,
        authorization: AsanaDiscoveryAuthorization,
        request: AsanaProjectRequest,
    ) -> AsanaProjectPage:
        """Retrieve one minimal active-project page."""


@dataclass(frozen=True, slots=True)
class AsanaDiscovery:
    """In-memory discovery result; private names are excluded from repr."""

    workspaces: tuple[AsanaWorkspace, ...] = field(repr=False)
    projects: tuple[AsanaProject, ...] = field(repr=False)
    workspace_page_count: int
    project_page_count: int
    project_discovery_performed: bool
    duplicate_workspace_count: int = 0
    duplicate_project_count: int = 0


@dataclass(frozen=True, slots=True)
class AsanaDiscoveryReport:
    """Privacy-safe live outcome suitable for a chat stop report."""

    application_name: str
    application_owner: str
    account_identity_source: str
    granted_scope: str
    credential_health: str
    refresh_health: str
    workspace_count: int
    workspace_page_count: int
    project_discovery_performed: bool
    project_count: int
    project_page_count: int
    private_report_path: Path
    connector_run_id: str
    access_token_issued: bool = True
    refresh_token_issued: bool = True
    task_endpoint_called: bool = False
    raw_payload_persisted: bool = False
    offset_persisted: bool = False
    complete_project_catalog_persisted: bool = False
    duplicate_project_count: int = 0
    discovery_complete: bool = True
    concurrent_change_could_affect_completeness: bool = True
    timeout_or_permission_issue: bool = False

    @property
    def workspace_pagination_occurred(self) -> bool:
        return self.workspace_page_count > 1

    @property
    def project_pagination_occurred(self) -> bool:
        return self.project_page_count > 1


@dataclass(frozen=True, slots=True)
class StoredAsanaDiscoveryAuthorizationProvider:
    """Resolve exact-scope token material from one Keychain item."""

    state_store: StateStore
    keychain: MacOSKeychain

    def get_authorization(self) -> AsanaDiscoveryAuthorization:
        metadata = self.state_store.get_connector_authorization(ASANA_PRIMARY_INSTANCE)
        if (
            metadata is None
            or metadata.authorization_status is not AuthorizationStatus.AUTHORIZED
            or metadata.credential_health is not CredentialHealth.HEALTHY
            or frozenset(metadata.granted_scope.split()) != ASANA_DISCOVERY_SCOPES
            or metadata.connector_instance_id != ASANA_PRIMARY_INSTANCE
        ):
            raise AsanaDiscoveryAuthorizationUnavailable(
                "Asana discovery authorization is unavailable"
            )
        reference = KeychainSecretReference(
            service=metadata.credential_service,
            account=metadata.access_token_account,
        )
        try:
            token = self.keychain.read(reference)
        except KeychainSecretNotFound:
            raise AsanaDiscoveryAuthorizationUnavailable(
                "Asana discovery credential is missing"
            ) from None
        return AsanaDiscoveryAuthorization(
            account_reference=metadata.account_reference,
            account_identity=metadata.account_identity,
            granted_scopes=frozenset(metadata.granted_scope.split()),
            credential_reference=reference.identifier,
            access_token=token,
        )


@dataclass(frozen=True, slots=True)
class AsanaDiscoveryHttpTransport:
    """Fixed-host GET transport for workspace and active-project discovery."""

    timeout_seconds: int = 30

    def list_workspaces(
        self,
        authorization: AsanaDiscoveryAuthorization,
        request: AsanaWorkspaceRequest,
    ) -> AsanaWorkspacePage:
        if (
            authorization.granted_scopes != ASANA_DISCOVERY_SCOPES
            or request.limit != ASANA_PAGE_SIZE
            or request.fields != ASANA_WORKSPACE_FIELDS
        ):
            raise AsanaDiscoveryRetrievalError(
                "Asana workspace request exceeded its boundary"
            )
        query: dict[str, str] = {
            "limit": str(request.limit),
            "opt_fields": ",".join(request.fields),
        }
        if request.offset is not None:
            query["offset"] = request.offset
        payload = self._get(
            authorization=authorization,
            path="/workspaces",
            query=query,
        )
        return AsanaWorkspacePage(
            workspaces=tuple(
                _parse_workspace(item) for item in _response_data(payload)
            ),
            next_offset=_next_offset(payload),
        )

    def list_projects(
        self,
        authorization: AsanaDiscoveryAuthorization,
        request: AsanaProjectRequest,
    ) -> AsanaProjectPage:
        if (
            authorization.granted_scopes != ASANA_DISCOVERY_SCOPES
            or not request.workspace_gid.strip()
            or request.archived
            or request.limit != ASANA_PAGE_SIZE
            or request.fields != ASANA_PROJECT_FIELDS
        ):
            raise AsanaDiscoveryRetrievalError(
                "Asana project request exceeded its boundary"
            )
        query = {
            "archived": "false",
            "limit": str(request.limit),
            "opt_fields": ",".join(request.fields),
        }
        if request.offset is not None:
            query["offset"] = request.offset
        encoded_gid = urllib.parse.quote(request.workspace_gid, safe="")
        payload = self._get(
            authorization=authorization,
            path=f"/workspaces/{encoded_gid}/projects",
            query=query,
        )
        return AsanaProjectPage(
            projects=tuple(_parse_project(item) for item in _response_data(payload)),
            next_offset=_next_offset(payload),
        )

    def _get(
        self,
        *,
        authorization: AsanaDiscoveryAuthorization,
        path: str,
        query: dict[str, str],
    ) -> dict[str, object]:
        url = f"{ASANA_API_ROOT}{path}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(  # noqa: S310 - fixed Asana host/path
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {authorization.access_token}",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - fixed Asana host/path
                request,
                timeout=self.timeout_seconds,
            ) as response:
                raw = response.read(MAX_ASANA_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            if error.code == 401:
                raise AsanaDiscoveryAuthenticationError(
                    "Asana rejected the discovery credential"
                ) from None
            if error.code == 403:
                raise AsanaDiscoveryPermissionError(
                    "Asana denied the discovery operation"
                ) from None
            if error.code == 429:
                raise AsanaDiscoveryRateLimitError(
                    "Asana rate-limited discovery"
                ) from None
            raise AsanaDiscoveryRetrievalError(
                "Asana discovery request failed"
            ) from None
        except TimeoutError:
            raise AsanaDiscoveryTimeoutError(
                "Asana discovery request timed out"
            ) from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise AsanaDiscoveryTimeoutError(
                    "Asana discovery request timed out"
                ) from None
            raise AsanaDiscoveryRetrievalError(
                "Asana discovery request was unavailable"
            ) from None
        if len(raw) > MAX_ASANA_RESPONSE_BYTES:
            raise AsanaDiscoveryRetrievalError(
                "Asana discovery response exceeded its limit"
            )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError, UnicodeDecodeError:
            raise AsanaDiscoveryRetrievalError(
                "Asana discovery response was invalid"
            ) from None
        if not isinstance(payload, dict):
            raise AsanaDiscoveryRetrievalError("Asana discovery response was invalid")
        return cast(dict[str, object], payload)


@dataclass(frozen=True, slots=True)
class AsanaDiscoveryService:
    """Follow only provider offsets and stop before ambiguous expansion."""

    authorization_provider: AsanaDiscoveryAuthorizationProvider
    transport: AsanaDiscoveryTransport

    def discover(self) -> tuple[AsanaDiscoveryAuthorization, AsanaDiscovery]:
        """Discover workspaces and projects only when one workspace is visible."""

        authorization = self.authorization_provider.get_authorization()
        if authorization.granted_scopes != ASANA_DISCOVERY_SCOPES:
            raise AsanaDiscoveryAuthorizationUnavailable(
                "Asana discovery scope does not match the approved boundary"
            )
        workspaces, workspace_pages, duplicate_workspaces = self._retrieve_workspaces(
            authorization
        )
        if len(workspaces) != 1:
            return authorization, AsanaDiscovery(
                workspaces=workspaces,
                projects=(),
                workspace_page_count=workspace_pages,
                project_page_count=0,
                project_discovery_performed=False,
                duplicate_workspace_count=duplicate_workspaces,
            )
        projects, project_pages, duplicate_projects = self._retrieve_projects(
            authorization,
            workspace_gid=workspaces[0].gid,
        )
        return authorization, AsanaDiscovery(
            workspaces=workspaces,
            projects=projects,
            workspace_page_count=workspace_pages,
            project_page_count=project_pages,
            project_discovery_performed=True,
            duplicate_workspace_count=duplicate_workspaces,
            duplicate_project_count=duplicate_projects,
        )

    def _retrieve_workspaces(
        self,
        authorization: AsanaDiscoveryAuthorization,
    ) -> tuple[tuple[AsanaWorkspace, ...], int, int]:
        values: dict[str, AsanaWorkspace] = {}
        duplicates = 0
        offset: str | None = None
        seen_offsets: set[str] = set()
        for page_count in range(1, ASANA_MAX_PAGES + 1):
            page = self.transport.list_workspaces(
                authorization,
                AsanaWorkspaceRequest(
                    limit=ASANA_PAGE_SIZE,
                    fields=ASANA_WORKSPACE_FIELDS,
                    offset=offset,
                ),
            )
            duplicates += _merge_unique(
                values,
                page.workspaces,
                kind="workspace",
            )
            if page.next_offset is None:
                return (
                    tuple(values[key] for key in sorted(values)),
                    page_count,
                    duplicates,
                )
            offset = _validated_next_offset(page.next_offset, seen_offsets)
        raise AsanaDiscoveryPaginationError(
            "Asana workspace discovery reached its page limit"
        )

    def _retrieve_projects(
        self,
        authorization: AsanaDiscoveryAuthorization,
        *,
        workspace_gid: str,
    ) -> tuple[tuple[AsanaProject, ...], int, int]:
        values: dict[str, AsanaProject] = {}
        duplicates = 0
        offset: str | None = None
        seen_offsets: set[str] = set()
        for page_count in range(1, ASANA_MAX_PAGES + 1):
            page = self.transport.list_projects(
                authorization,
                AsanaProjectRequest(
                    workspace_gid=workspace_gid,
                    archived=False,
                    limit=ASANA_PAGE_SIZE,
                    fields=ASANA_PROJECT_FIELDS,
                    offset=offset,
                ),
            )
            duplicates += _merge_unique(values, page.projects, kind="project")
            if page.next_offset is None:
                return (
                    tuple(values[key] for key in sorted(values)),
                    page_count,
                    duplicates,
                )
            offset = _validated_next_offset(page.next_offset, seen_offsets)
        raise AsanaDiscoveryPaginationError(
            "Asana project discovery reached its page limit"
        )


@dataclass(frozen=True, slots=True)
class AsanaApprovedWorkspaceProjectDiscoveryService:
    """Discover projects only inside one explicitly approved workspace."""

    authorization_provider: AsanaDiscoveryAuthorizationProvider
    transport: AsanaProjectDiscoveryTransport
    approved_workspace: AsanaWorkspace = field(repr=False)

    def discover(self) -> tuple[AsanaDiscoveryAuthorization, AsanaDiscovery]:
        """Retrieve active projects without listing or inspecting workspaces."""

        authorization = self.authorization_provider.get_authorization()
        if authorization.granted_scopes != ASANA_DISCOVERY_SCOPES:
            raise AsanaDiscoveryAuthorizationUnavailable(
                "Asana discovery scope does not match the approved boundary"
            )
        if self.approved_workspace.name != ASANA_APPROVED_WORKSPACE_ALIAS:
            raise AsanaDiscoveryPermissionError(
                "The Asana workspace is outside the explicit approval boundary"
            )
        if not self.approved_workspace.is_organization:
            raise AsanaDiscoveryPermissionError(
                "The approved Asana resource is not an organization workspace"
            )
        projects, project_pages, duplicate_projects = _retrieve_projects(
            transport=self.transport,
            authorization=authorization,
            workspace_gid=self.approved_workspace.gid,
        )
        return authorization, AsanaDiscovery(
            workspaces=(self.approved_workspace,),
            projects=projects,
            workspace_page_count=0,
            project_page_count=project_pages,
            project_discovery_performed=True,
            duplicate_project_count=duplicate_projects,
        )


@dataclass(frozen=True, slots=True)
class AsanaDiscoveryTrialRunner:
    """Persist only discovery metadata and write one private selection report."""

    state_store: StateStore
    discovery_service: AsanaDiscoveryService
    output_directory: Path
    application_name: str
    application_owner: str
    account_identity_source: str
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def run(self) -> AsanaDiscoveryReport:
        """Complete one discovery and stop before every task operation."""

        started_at = self.clock()
        _authorization, discovery = self.discovery_service.discover()
        completed_at = self.clock()
        run_id = f"asana-discovery-{uuid.uuid4().hex}"
        approved_scope = (
            f"{ASANA_DISCOVERY_SCOPE_STRING}; "
            f"operations={ASANA_WORKSPACE_OPERATION}, {ASANA_PROJECT_OPERATION}; "
            "archived=false; no tasks"
        )
        self.state_store.add_connector_run(
            ConnectorRun(
                id=run_id,
                source="asana_discovery",
                approved_scope=approved_scope,
                started_at=started_at,
                completed_at=completed_at,
                status=ConnectorStatus.SUCCEEDED,
                coverage_status=CoverageStatus.COMPLETE,
                freshness_at=completed_at,
                page_count=(
                    discovery.workspace_page_count + discovery.project_page_count
                ),
                connector_instance_id=ASANA_PRIMARY_INSTANCE,
            )
        )
        fingerprint = hashlib.sha256(
            (
                f"asana-discovery\0{len(discovery.workspaces)}\0"
                f"{len(discovery.projects)}\0{completed_at.isoformat()}"
            ).encode()
        ).hexdigest()
        self.state_store.add_source_evidence(
            SourceEvidence(
                id=f"{run_id}:catalog-reference",
                connector_run_id=run_id,
                connector_instance_id=ASANA_PRIMARY_INSTANCE,
                source="asana_discovery",
                source_record_id="workspace-project-discovery",
                evidence_fingerprint=fingerprint,
                retrieved_at=completed_at,
                freshness_at=completed_at,
            )
        )
        if len(discovery.workspaces) == 1:
            workspace = discovery.workspaces[0]
            self.state_store.save_connector_resource(
                ConnectorResourceMetadata(
                    connector=ASANA_CONNECTOR,
                    connector_instance_id=ASANA_PRIMARY_INSTANCE,
                    resource_reference="discovered-workspace",
                    resource_id=workspace.gid,
                    resource_url=(f"https://app.asana.com/0/{workspace.gid}/list"),
                    resource_type="workspace",
                    grant_type="discovered-not-approved",
                    selected_at=completed_at,
                )
            )
        self.state_store.update_connector_instance_coverage(
            ASANA_PRIMARY_INSTANCE,
            coverage_status=CoverageStatus.COMPLETE,
            freshness_at=completed_at,
            updated_at=completed_at,
        )
        self.state_store.mark_connector_authorization_used(
            ASANA_PRIMARY_INSTANCE,
            used_at=completed_at,
        )
        output_path = self._write_private_report(
            generated_at=completed_at,
            discovery=discovery,
        )
        metadata = self.state_store.get_connector_authorization(ASANA_PRIMARY_INSTANCE)
        if metadata is None:
            raise AsanaDiscoveryError(
                "Asana authorization metadata disappeared during discovery"
            )
        return AsanaDiscoveryReport(
            application_name=self.application_name,
            application_owner=self.application_owner,
            account_identity_source=self.account_identity_source,
            granted_scope=metadata.granted_scope,
            credential_health=metadata.credential_health.value,
            refresh_health=(
                "unavailable"
                if metadata.refresh_health is None
                else metadata.refresh_health.value
            ),
            workspace_count=len(discovery.workspaces),
            workspace_page_count=discovery.workspace_page_count,
            project_discovery_performed=discovery.project_discovery_performed,
            project_count=len(discovery.projects),
            project_page_count=discovery.project_page_count,
            private_report_path=output_path,
            connector_run_id=run_id,
        )

    def _write_private_report(
        self,
        *,
        generated_at: datetime,
        discovery: AsanaDiscovery,
    ) -> Path:
        self.output_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.output_directory.chmod(0o700)
        output_path = (
            self.output_directory / f"asana-discovery-{generated_at:%Y%m%dT%H%M%SZ}.md"
        )
        descriptor = os.open(
            output_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(
                _private_report_text(
                    generated_at=generated_at,
                    discovery=discovery,
                )
            )
        return output_path


@dataclass(frozen=True, slots=True)
class AsanaApprovedWorkspaceProjectTrialRunner:
    """Bind one approved workspace and run project-only discovery once."""

    state_store: StateStore
    discovery_service: AsanaApprovedWorkspaceProjectDiscoveryService
    output_directory: Path
    application_name: str
    application_owner: str
    account_identity_source: str
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def run(self) -> AsanaDiscoveryReport:
        """Persist only approved-workspace and project-run metadata."""

        started_at = self.clock()
        self._bind_approved_workspace(selected_at=started_at)
        _authorization, discovery = self.discovery_service.discover()
        completed_at = self.clock()
        run_id = f"asana-project-discovery-{uuid.uuid4().hex}"
        self.state_store.add_connector_run(
            ConnectorRun(
                id=run_id,
                source="asana_project_discovery",
                approved_scope=(
                    f"{ASANA_DISCOVERY_SCOPE_STRING}; "
                    f"operation={ASANA_PROJECT_OPERATION}; archived=false; "
                    "approved workspace only; no workspace listing; no tasks"
                ),
                started_at=started_at,
                completed_at=completed_at,
                status=ConnectorStatus.SUCCEEDED,
                coverage_status=CoverageStatus.COMPLETE,
                freshness_at=completed_at,
                page_count=discovery.project_page_count,
                connector_instance_id=ASANA_PRIMARY_INSTANCE,
            )
        )
        fingerprint = hashlib.sha256(
            (
                f"asana-project-discovery\0{len(discovery.projects)}\0"
                f"{completed_at.isoformat()}"
            ).encode()
        ).hexdigest()
        self.state_store.add_source_evidence(
            SourceEvidence(
                id=f"{run_id}:catalog-reference",
                connector_run_id=run_id,
                connector_instance_id=ASANA_PRIMARY_INSTANCE,
                source="asana_project_discovery",
                source_record_id="approved-workspace-project-discovery",
                evidence_fingerprint=fingerprint,
                retrieved_at=completed_at,
                freshness_at=completed_at,
            )
        )
        self.state_store.update_connector_instance_coverage(
            ASANA_PRIMARY_INSTANCE,
            coverage_status=CoverageStatus.COMPLETE,
            freshness_at=completed_at,
            updated_at=completed_at,
        )
        self.state_store.mark_connector_authorization_used(
            ASANA_PRIMARY_INSTANCE,
            used_at=completed_at,
        )
        output_path = self._write_private_report(
            generated_at=completed_at,
            discovery=discovery,
        )
        metadata = self.state_store.get_connector_authorization(ASANA_PRIMARY_INSTANCE)
        if metadata is None:
            raise AsanaDiscoveryError(
                "Asana authorization metadata disappeared during discovery"
            )
        return AsanaDiscoveryReport(
            application_name=self.application_name,
            application_owner=self.application_owner,
            account_identity_source=self.account_identity_source,
            granted_scope=metadata.granted_scope,
            credential_health=metadata.credential_health.value,
            refresh_health=(
                "unavailable"
                if metadata.refresh_health is None
                else metadata.refresh_health.value
            ),
            workspace_count=1,
            workspace_page_count=0,
            project_discovery_performed=True,
            project_count=len(discovery.projects),
            project_page_count=discovery.project_page_count,
            private_report_path=output_path,
            connector_run_id=run_id,
            duplicate_project_count=discovery.duplicate_project_count,
        )

    def _bind_approved_workspace(self, *, selected_at: datetime) -> None:
        workspace = self.discovery_service.approved_workspace
        instance = self.state_store.get_connector_instance(ASANA_PRIMARY_INSTANCE)
        if instance is None:
            raise AsanaDiscoveryAuthorizationUnavailable(
                "Asana connector instance metadata is unavailable"
            )
        self.state_store.save_connector_instance(
            replace(
                instance,
                approved_resource_boundary=(
                    "one explicitly approved organization workspace"
                ),
                approved_scopes=ASANA_DISCOVERY_SCOPE_STRING,
                retrieval_configuration="approved-workspace-active-project-discovery",
                enabled=True,
                updated_at=selected_at,
            )
        )
        self.state_store.save_connector_resource(
            ConnectorResourceMetadata(
                connector=ASANA_CONNECTOR,
                connector_instance_id=ASANA_PRIMARY_INSTANCE,
                resource_reference="approved-organization-workspace",
                resource_id=workspace.gid,
                resource_url=f"https://app.asana.com/0/{workspace.gid}/list",
                resource_type="workspace",
                grant_type="explicit-user-approval",
                selected_at=selected_at,
            )
        )

    def _write_private_report(
        self,
        *,
        generated_at: datetime,
        discovery: AsanaDiscovery,
    ) -> Path:
        self.output_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.output_directory.chmod(0o700)
        output_path = self.output_directory / (
            f"asana-project-discovery-{generated_at:%Y%m%dT%H%M%SZ}.md"
        )
        descriptor = os.open(
            output_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(
                _private_project_selection_report_text(
                    generated_at=generated_at,
                    discovery=discovery,
                )
            )
        return output_path


def approved_workspace_from_private_report(
    *,
    report_path: Path,
    approved_alias: str,
) -> AsanaWorkspace:
    """Resolve one explicit organization selection from the private report."""

    if not approved_alias.strip():
        raise ValueError("approved Asana workspace alias must not be empty")
    report = report_path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^- {re.escape(approved_alias)} "
        r"\(`(?P<gid>[0-9]+)`\); organization=(?P<organization>true|false)$",
        flags=re.MULTILINE,
    )
    matches = {
        (match.group("gid"), match.group("organization") == "true")
        for match in pattern.finditer(report)
    }
    report = ""
    if len(matches) != 1:
        raise AsanaDiscoveryPermissionError(
            "The private discovery report did not contain one exact approved workspace"
        )
    gid, is_organization = matches.pop()
    if not is_organization:
        raise AsanaDiscoveryPermissionError(
            "The approved Asana workspace is not an organization"
        )
    return AsanaWorkspace(
        gid=gid,
        name=approved_alias.strip(),
        is_organization=True,
    )


def _retrieve_projects(
    *,
    transport: AsanaProjectDiscoveryTransport,
    authorization: AsanaDiscoveryAuthorization,
    workspace_gid: str,
) -> tuple[tuple[AsanaProject, ...], int, int]:
    values: dict[str, AsanaProject] = {}
    duplicates = 0
    offset: str | None = None
    seen_offsets: set[str] = set()
    for page_count in range(1, ASANA_MAX_PAGES + 1):
        page = transport.list_projects(
            authorization,
            AsanaProjectRequest(
                workspace_gid=workspace_gid,
                archived=False,
                limit=ASANA_PAGE_SIZE,
                fields=ASANA_PROJECT_FIELDS,
                offset=offset,
            ),
        )
        duplicates += _merge_unique(values, page.projects, kind="project")
        if page.next_offset is None:
            return (
                tuple(values[key] for key in sorted(values)),
                page_count,
                duplicates,
            )
        offset = _validated_next_offset(page.next_offset, seen_offsets)
    raise AsanaDiscoveryPaginationError(
        "Asana project discovery reached its page limit"
    )


def _merge_unique(
    values: dict[str, AsanaWorkspace] | dict[str, AsanaProject],
    new_values: tuple[AsanaWorkspace, ...] | tuple[AsanaProject, ...],
    *,
    kind: str,
) -> int:
    duplicate_count = 0
    for value in new_values:
        existing = values.get(value.gid)
        if existing is None:
            values[value.gid] = value  # type: ignore[assignment]
        elif existing == value:
            duplicate_count += 1
        else:
            raise AsanaDiscoveryPaginationError(
                f"conflicting duplicate Asana {kind} GID"
            )
    return duplicate_count


def _validated_next_offset(value: str, seen_offsets: set[str]) -> str:
    if not value or value in seen_offsets:
        raise AsanaDiscoveryPaginationError(
            "Asana returned an invalid or repeated pagination offset"
        )
    seen_offsets.add(value)
    return value


def _response_data(payload: dict[str, object]) -> tuple[dict[str, object], ...]:
    data = payload.get("data")
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise AsanaDiscoveryRetrievalError(
            "Asana discovery response omitted its data collection"
        )
    return tuple(cast(dict[str, object], item) for item in data)


def _next_offset(payload: dict[str, object]) -> str | None:
    next_page = payload.get("next_page")
    if next_page is None:
        return None
    if not isinstance(next_page, dict):
        raise AsanaDiscoveryRetrievalError(
            "Asana discovery response contained invalid pagination"
        )
    offset = next_page.get("offset")
    if not isinstance(offset, str) or not offset:
        raise AsanaDiscoveryRetrievalError(
            "Asana discovery response omitted its provider offset"
        )
    return offset


def _parse_workspace(payload: dict[str, object]) -> AsanaWorkspace:
    gid = payload.get("gid")
    name = payload.get("name")
    is_organization = payload.get("is_organization")
    if (
        not isinstance(gid, str)
        or not isinstance(name, str)
        or not isinstance(is_organization, bool)
    ):
        raise AsanaDiscoveryRetrievalError(
            "Asana workspace response omitted an approved field"
        )
    return AsanaWorkspace(gid=gid, name=name, is_organization=is_organization)


def _parse_project(payload: dict[str, object]) -> AsanaProject:
    gid = payload.get("gid")
    name = payload.get("name")
    archived = payload.get("archived")
    public = payload.get("public")
    permalink_url = payload.get("permalink_url")
    if (
        not isinstance(gid, str)
        or not isinstance(name, str)
        or not isinstance(archived, bool)
        or not isinstance(public, bool)
        or not isinstance(permalink_url, str)
    ):
        raise AsanaDiscoveryRetrievalError(
            "Asana project response omitted an approved field"
        )
    if archived:
        raise AsanaDiscoveryRetrievalError(
            "Asana returned an archived project outside the request"
        )
    return AsanaProject(
        gid=gid,
        name=name,
        archived=archived,
        public=public,
        permalink_url=permalink_url,
    )


def _private_report_text(
    *,
    generated_at: datetime,
    discovery: AsanaDiscovery,
) -> str:
    lines = [
        "# Private Asana Discovery",
        "",
        f"- Generated: {generated_at.isoformat()}",
        f"- Accessible workspaces: {len(discovery.workspaces)}",
        f"- Workspace pages: {discovery.workspace_page_count}",
        (
            "- Project discovery performed: "
            f"{str(discovery.project_discovery_performed).lower()}"
        ),
        f"- Active projects: {len(discovery.projects)}",
        f"- Project pages: {discovery.project_page_count}",
        "- Task endpoint called: false",
        "",
        "## Workspaces",
        "",
    ]
    lines.extend(
        f"- {workspace.name} (`{workspace.gid}`); "
        f"organization={str(workspace.is_organization).lower()}"
        for workspace in discovery.workspaces
    )
    if not discovery.workspaces:
        lines.append("- None returned.")
    lines.extend(("", "## Active projects", ""))
    if discovery.project_discovery_performed:
        lines.extend(
            f"- {project.name} (`{project.gid}`); "
            f"public={str(project.public).lower()}; "
            f"[open]({project.permalink_url})"
            for project in discovery.projects
        )
        if not discovery.projects:
            lines.append("- None returned.")
    else:
        lines.append(
            "- Not retrieved because discovery did not return exactly one workspace."
        )
    lines.extend(
        (
            "",
            "## Explicit approval choices for the later task gate",
            "",
            "- [ ] Approve exactly one workspace.",
            "- [ ] Approve one or more projects, if project restriction is desired.",
            "- [ ] Allow or exclude assigned tasks outside approved projects.",
            "- [ ] Include or exclude My Tasks.",
            "- [ ] Allow or exclude explicit task GIDs linked by another approved source.",
            "",
            "## Prepared task-retrieval proposal — not executed",
            "",
            "- Prefer `GET /api/1.0/tasks` with `assignee=me`, the explicitly "
            "approved workspace, provider incomplete-task semantics through "
            "`completed_since`, and stable provider-offset pagination.",
            "- Proposed later scopes: `tasks:read`, `workspaces:read`, and "
            "`projects:read`; add `project_sections:read` only if approved "
            "section membership is required.",
            "- Do not use workspace task search as the normal path: it is "
            "premium-only, eventually consistent, and lacks normal stable "
            "pagination.",
            "- Exclude notes, stories, attachments, followers, likes, custom "
            "fields, time tracking, portfolios, goals, users, tags, and all "
            "mutation operations unless separately justified and approved.",
            "",
        )
    )
    return "\n".join(lines)


def _private_project_selection_report_text(
    *,
    generated_at: datetime,
    discovery: AsanaDiscovery,
) -> str:
    if len(discovery.workspaces) != 1 or not discovery.project_discovery_performed:
        raise ValueError("project-selection report requires one approved workspace")
    workspace = discovery.workspaces[0]
    lines = [
        "# Private Asana Project Selection",
        "",
        f"- Generated: {generated_at.isoformat()}",
        f"- Approved workspace: {workspace.name} (`{workspace.gid}`)",
        f"- Organization: {str(workspace.is_organization).lower()}",
        f"- Project pages: {discovery.project_page_count}",
        f"- Active projects: {len(discovery.projects)}",
        f"- Duplicate project GIDs: {discovery.duplicate_project_count}",
        "- Project discovery complete: true",
        (
            "- Completeness caveat: provider-offset pagination completed, but "
            "concurrent project changes may have affected the catalog."
        ),
        "- Workspace-list endpoint called: false",
        "- Task endpoint called: false",
        "",
        "## Active projects",
        "",
    ]
    lines.extend(
        f"- {project.name} (`{project.gid}`); "
        f"archived={str(project.archived).lower()}; "
        f"public={str(project.public).lower()}; "
        f"[open]({project.permalink_url})"
        for project in discovery.projects
    )
    if not discovery.projects:
        lines.append("- None returned.")
    lines.extend(
        (
            "",
            "## Explicit approval choices for the later task gate",
            "",
            "- [ ] Approve one or more projects.",
            (
                "- [ ] Allow all assigned incomplete tasks in the approved "
                "workspace regardless of project membership."
            ),
            "- [ ] Include tasks with no project.",
            "- [ ] Include My Tasks.",
            (
                "- [ ] Include explicit task GIDs linked from another "
                "separately approved source."
            ),
            ("- [ ] Require approved project membership in briefing context."),
            (
                "- [ ] Require section membership in briefing context; this "
                "requires a separate scope decision."
            ),
            (
                "- [ ] Mark any selected project as more important than "
                "another, with an explicit reason."
            ),
            "",
            (
                "Project names, visibility, and discovery order do not imply "
                "approval or priority."
            ),
            "",
            "## Later task-retrieval options — not executed",
            "",
            ("### Option A — Assigned tasks across the approved workspace"),
            "",
            (
                "Use `GET /api/1.0/tasks` with `assignee=me`, the approved "
                "workspace, provider-supported incomplete-task semantics, and "
                "stable offset pagination. This can include tasks outside "
                "selected projects and tasks with no project."
            ),
            "",
            "### Option B — Tasks from explicitly approved projects",
            "",
            (
                "Call the project-task endpoint separately for each approved "
                "project. Deduplicate by stable task GID while preserving every "
                "approved project membership because one task may belong to "
                "multiple projects."
            ),
            "",
            "### Option C — Hybrid boundary",
            "",
            (
                "Retrieve assigned incomplete tasks across the approved "
                "workspace plus unassigned-to-Brad tasks from explicitly "
                "approved projects only when both categories are separately "
                "approved."
            ),
            "",
            (
                "Do not use workspace task search as the normal proposal "
                "unless standard endpoints cannot satisfy the approved "
                "boundary."
            ),
            "",
            "## Proposed later scopes — not requested",
            "",
            "- `tasks:read`",
            "- retain `workspaces:read`",
            "- retain `projects:read`",
            (
                "- add `project_sections:read` only if section context is "
                "approved and required"
            ),
            "",
            (
                "Do not add user, tag, story, attachment, OpenID Connect, "
                "write, delete, full-permission, or administrative scopes "
                "without a separate demonstrated requirement."
            ),
            "",
            "## Proposed later task fields — not retrieved",
            "",
            "- `gid`",
            "- `name`",
            "- `completed`",
            "- `assignee.gid`",
            "- `due_on`",
            "- `due_at`",
            "- `start_on`",
            "- `start_at`",
            "- `created_at`",
            "- `modified_at`",
            "- `resource_subtype`",
            "- `parent.gid`",
            "- approved project memberships",
            "- approved section memberships only if later authorized",
            "- dependency and dependent references",
            "- `permalink_url`",
            "",
            "Task notes and descriptions remain excluded by default.",
            "",
        )
    )
    return "\n".join(lines)
