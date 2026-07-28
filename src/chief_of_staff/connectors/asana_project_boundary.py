"""Verify and bind one exact Asana project without task access."""

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
from chief_of_staff.connectors.asana_discovery import (
    ASANA_API_ROOT,
    MAX_ASANA_RESPONSE_BYTES,
    AsanaDiscoveryAuthenticationError,
    AsanaDiscoveryAuthorization,
    AsanaDiscoveryAuthorizationProvider,
    AsanaDiscoveryAuthorizationUnavailable,
    AsanaDiscoveryError,
    AsanaDiscoveryPermissionError,
    AsanaDiscoveryRateLimitError,
    AsanaDiscoveryRetrievalError,
    AsanaDiscoveryTimeoutError,
)
from chief_of_staff.connectors.instances import ASANA_PRIMARY_INSTANCE
from chief_of_staff.domain import (
    ConnectorResourceMetadata,
    ConnectorRun,
    ConnectorStatus,
    CoverageStatus,
    SourceEvidence,
)
from chief_of_staff.persistence import StateStore

ASANA_EXACT_PROJECT_OPERATION: Final = "GET /api/1.0/projects/{project_gid}"
ASANA_EXACT_PROJECT_BOUNDARY: Final = (
    "one explicitly approved 9 Embers Rock RMS development project"
)
ASANA_EXACT_PROJECT_RESOURCE_REFERENCE: Final = "approved-9-embers-rock-rms-project"
ASANA_EXACT_PROJECT_FIELDS: Final = (
    "gid",
    "name",
    "archived",
    "public",
    "permalink_url",
    "workspace.gid",
)
_APPROVED_PROJECT_PATH = re.compile(
    r"^/1/(?P<workspace_gid>[0-9]+)/project/"
    r"(?P<project_gid>[0-9]+)/(?:board|list)/(?P<view_gid>[0-9]+)/?$"
)


@dataclass(frozen=True, slots=True)
class AsanaExactProjectReference:
    """Exact project identity parsed from one user-approved Asana URL."""

    workspace_gid: str = field(repr=False)
    project_gid: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AsanaExactProjectRequest:
    """The only request shape permitted by the exact-project transport."""

    project_gid: str = field(repr=False)
    expected_workspace_gid: str = field(repr=False)
    fields: tuple[str, ...] = ASANA_EXACT_PROJECT_FIELDS


@dataclass(frozen=True, slots=True)
class AsanaVerifiedProject:
    """Minimal verified project facts retained only in memory and private audit."""

    gid: str = field(repr=False)
    workspace_gid: str = field(repr=False)
    name: str = field(repr=False)
    archived: bool
    public: bool
    permalink_url: str = field(repr=False)


class AsanaExactProjectTransport(Protocol):
    """The complete live API surface for exact-project verification."""

    def get_project(
        self,
        authorization: AsanaDiscoveryAuthorization,
        request: AsanaExactProjectRequest,
    ) -> AsanaVerifiedProject:
        """Retrieve one exact project by GID."""


@dataclass(frozen=True, slots=True)
class AsanaExactProjectHttpTransport:
    """Fixed-host transport exposing one read-only exact-project GET."""

    timeout_seconds: int = 30

    def get_project(
        self,
        authorization: AsanaDiscoveryAuthorization,
        request: AsanaExactProjectRequest,
    ) -> AsanaVerifiedProject:
        """Retrieve one exact project with no collection or task endpoint."""

        if (
            authorization.granted_scopes != ASANA_DISCOVERY_SCOPES
            or not request.project_gid.isdigit()
            or not request.expected_workspace_gid.isdigit()
            or request.fields != ASANA_EXACT_PROJECT_FIELDS
        ):
            raise AsanaDiscoveryRetrievalError(
                "Asana exact-project request exceeded its boundary"
            )
        encoded_gid = urllib.parse.quote(request.project_gid, safe="")
        query = urllib.parse.urlencode({"opt_fields": ",".join(request.fields)})
        url = f"{ASANA_API_ROOT}/projects/{encoded_gid}?{query}"
        http_request = urllib.request.Request(  # noqa: S310 - fixed Asana host
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {authorization.access_token}",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - fixed Asana host
                http_request,
                timeout=self.timeout_seconds,
            ) as response:
                raw = response.read(MAX_ASANA_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            if error.code == 401:
                raise AsanaDiscoveryAuthenticationError(
                    "Asana rejected the exact-project credential"
                ) from None
            if error.code in {403, 404}:
                raise AsanaDiscoveryPermissionError(
                    "Asana denied or could not find the approved exact project"
                ) from None
            if error.code == 429:
                raise AsanaDiscoveryRateLimitError(
                    "Asana rate-limited exact-project verification"
                ) from None
            raise AsanaDiscoveryRetrievalError(
                "Asana exact-project verification failed"
            ) from None
        except TimeoutError:
            raise AsanaDiscoveryTimeoutError(
                "Asana exact-project verification timed out"
            ) from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise AsanaDiscoveryTimeoutError(
                    "Asana exact-project verification timed out"
                ) from None
            raise AsanaDiscoveryRetrievalError(
                "Asana exact-project verification was unavailable"
            ) from None
        if len(raw) > MAX_ASANA_RESPONSE_BYTES:
            raise AsanaDiscoveryRetrievalError(
                "Asana exact-project response exceeded its limit"
            )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError, UnicodeDecodeError:
            raise AsanaDiscoveryRetrievalError(
                "Asana exact-project response was invalid"
            ) from None
        if not isinstance(payload, dict):
            raise AsanaDiscoveryRetrievalError(
                "Asana exact-project response was invalid"
            )
        return _parse_exact_project(cast(dict[str, object], payload))


@dataclass(frozen=True, slots=True)
class AsanaExactProjectVerificationService:
    """Verify one approved project and its workspace without discovery."""

    authorization_provider: AsanaDiscoveryAuthorizationProvider
    transport: AsanaExactProjectTransport
    approved_reference: AsanaExactProjectReference = field(repr=False)

    def verify(
        self,
    ) -> tuple[AsanaDiscoveryAuthorization, AsanaVerifiedProject]:
        """Return only when provider identity exactly matches the approval."""

        authorization = self.authorization_provider.get_authorization()
        if authorization.granted_scopes != ASANA_DISCOVERY_SCOPES:
            raise AsanaDiscoveryAuthorizationUnavailable(
                "Asana scope does not match the approved verification boundary"
            )
        project = self.transport.get_project(
            authorization,
            AsanaExactProjectRequest(
                project_gid=self.approved_reference.project_gid,
                expected_workspace_gid=self.approved_reference.workspace_gid,
            ),
        )
        if (
            project.gid != self.approved_reference.project_gid
            or project.workspace_gid != self.approved_reference.workspace_gid
        ):
            raise AsanaDiscoveryPermissionError(
                "Asana returned a project outside the exact approval boundary"
            )
        if project.archived:
            raise AsanaDiscoveryPermissionError(
                "The approved exact Asana project is archived"
            )
        return authorization, project


@dataclass(frozen=True, slots=True)
class AsanaExactProjectReport:
    """Privacy-safe outcome for the exact-project boundary correction."""

    application_name: str
    application_owner: str
    granted_scope: str
    credential_health: str
    refresh_health: str
    private_report_path: Path
    connector_run_id: str
    project_verified: bool = True
    active_resource_type: str = "project"
    project_endpoint_calls: int = 1
    workspace_list_endpoint_called: bool = False
    project_list_endpoint_called: bool = False
    task_endpoint_called: bool = False
    raw_payload_persisted: bool = False


@dataclass(frozen=True, slots=True)
class AsanaExactProjectTrialRunner:
    """Verify then replace the active connector binding with one exact project."""

    state_store: StateStore
    verification_service: AsanaExactProjectVerificationService
    output_directory: Path
    application_name: str
    application_owner: str
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def run(self) -> AsanaExactProjectReport:
        """Verify one project, persist its reference, and stop before tasks."""

        started_at = self.clock()
        _authorization, project = self.verification_service.verify()
        completed_at = self.clock()
        run_id = f"asana-exact-project-{uuid.uuid4().hex}"
        instance = self.state_store.get_connector_instance(ASANA_PRIMARY_INSTANCE)
        if instance is None:
            raise AsanaDiscoveryAuthorizationUnavailable(
                "Asana connector instance metadata is unavailable"
            )
        self.state_store.save_connector_instance(
            replace(
                instance,
                approved_resource_boundary=ASANA_EXACT_PROJECT_BOUNDARY,
                approved_scopes=ASANA_DISCOVERY_SCOPE_STRING,
                retrieval_configuration="exact-project-only",
                enabled=True,
                updated_at=completed_at,
            )
        )
        self.state_store.save_connector_resource(
            ConnectorResourceMetadata(
                connector=ASANA_CONNECTOR,
                connector_instance_id=ASANA_PRIMARY_INSTANCE,
                resource_reference=ASANA_EXACT_PROJECT_RESOURCE_REFERENCE,
                resource_id=project.gid,
                resource_url=project.permalink_url,
                resource_type="project",
                grant_type="explicit-user-approval",
                selected_at=completed_at,
            )
        )
        self.state_store.add_connector_run(
            ConnectorRun(
                id=run_id,
                source="asana_project_boundary_verification",
                approved_scope=(
                    f"{ASANA_DISCOVERY_SCOPE_STRING}; "
                    f"operation={ASANA_EXACT_PROJECT_OPERATION}; "
                    "exact project only; no collection listing; no tasks"
                ),
                started_at=started_at,
                completed_at=completed_at,
                status=ConnectorStatus.SUCCEEDED,
                coverage_status=CoverageStatus.COMPLETE,
                freshness_at=completed_at,
                page_count=1,
                connector_instance_id=ASANA_PRIMARY_INSTANCE,
            )
        )
        fingerprint = hashlib.sha256(
            (
                f"asana-project-boundary\0{project.gid}\0"
                f"{project.workspace_gid}\0{completed_at.isoformat()}"
            ).encode()
        ).hexdigest()
        self.state_store.add_source_evidence(
            SourceEvidence(
                id=f"{run_id}:project-reference",
                connector_run_id=run_id,
                connector_instance_id=ASANA_PRIMARY_INSTANCE,
                source="asana_project_boundary_verification",
                source_record_id=project.gid,
                evidence_fingerprint=fingerprint,
                display_url=project.permalink_url,
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
            project=project,
        )
        metadata = self.state_store.get_connector_authorization(ASANA_PRIMARY_INSTANCE)
        if metadata is None:
            raise AsanaDiscoveryError(
                "Asana authorization metadata disappeared during verification"
            )
        return AsanaExactProjectReport(
            application_name=self.application_name,
            application_owner=self.application_owner,
            granted_scope=metadata.granted_scope,
            credential_health=metadata.credential_health.value,
            refresh_health=(
                "unavailable"
                if metadata.refresh_health is None
                else metadata.refresh_health.value
            ),
            private_report_path=output_path,
            connector_run_id=run_id,
        )

    def _write_private_report(
        self,
        *,
        generated_at: datetime,
        project: AsanaVerifiedProject,
    ) -> Path:
        self.output_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.output_directory.chmod(0o700)
        output_path = self.output_directory / (
            f"asana-exact-project-boundary-{generated_at:%Y%m%dT%H%M%SZ}.md"
        )
        descriptor = os.open(
            output_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(
                _private_exact_project_report_text(
                    generated_at=generated_at,
                    project=project,
                )
            )
        return output_path


def parse_approved_asana_project_url(url: str) -> AsanaExactProjectReference:
    """Parse one exact modern Asana project URL without broadening it."""

    parsed = urllib.parse.urlsplit(url.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname != "app.asana.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("approved Asana URL must be one exact app.asana.com project")
    match = _APPROVED_PROJECT_PATH.fullmatch(parsed.path)
    if match is None:
        raise ValueError("approved Asana URL has an unsupported project path")
    return AsanaExactProjectReference(
        workspace_gid=match.group("workspace_gid"),
        project_gid=match.group("project_gid"),
    )


def _parse_exact_project(payload: dict[str, object]) -> AsanaVerifiedProject:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise AsanaDiscoveryRetrievalError(
            "Asana exact-project response omitted its project"
        )
    workspace = data.get("workspace")
    if not isinstance(workspace, dict):
        raise AsanaDiscoveryRetrievalError(
            "Asana exact-project response omitted its workspace"
        )
    gid = data.get("gid")
    workspace_gid = workspace.get("gid")
    name = data.get("name")
    archived = data.get("archived")
    public = data.get("public")
    permalink_url = data.get("permalink_url")
    if (
        not isinstance(gid, str)
        or not isinstance(workspace_gid, str)
        or not isinstance(name, str)
        or not isinstance(archived, bool)
        or not isinstance(public, bool)
        or not isinstance(permalink_url, str)
    ):
        raise AsanaDiscoveryRetrievalError(
            "Asana exact-project response omitted an approved field"
        )
    parsed_url = urllib.parse.urlsplit(permalink_url)
    if parsed_url.scheme != "https" or parsed_url.hostname != "app.asana.com":
        raise AsanaDiscoveryRetrievalError(
            "Asana exact-project response contained an invalid permalink"
        )
    return AsanaVerifiedProject(
        gid=gid,
        workspace_gid=workspace_gid,
        name=name,
        archived=archived,
        public=public,
        permalink_url=permalink_url,
    )


def _private_exact_project_report_text(
    *,
    generated_at: datetime,
    project: AsanaVerifiedProject,
) -> str:
    return "\n".join(
        (
            "# Private Asana Exact-Project Boundary",
            "",
            f"- Generated: {generated_at.isoformat()}",
            f"- Verified project: {project.name} (`{project.gid}`)",
            f"- Verified workspace GID: `{project.workspace_gid}`",
            f"- Archived: {str(project.archived).lower()}",
            f"- Public: {str(project.public).lower()}",
            f"- Authoritative link: {project.permalink_url}",
            "- Project endpoint calls: 1",
            "- Workspace-list endpoint called: false",
            "- Project-list endpoint called: false",
            "- Task endpoint called: false",
            "- Raw payload persisted: false",
            "",
            "## Boundary",
            "",
            "- The prior workspace-wide active boundary is superseded.",
            "- The obsolete Northridge boards have no active authority.",
            ("- Current purpose: collaboration with 9 Embers on Rock RMS development."),
            "- The active connector boundary is this exact project only.",
            (
                "- The trailing board or list view identifier in the submitted "
                "URL is navigation context, not a separate authorization."
            ),
            "- No task retrieval is authorized or performed.",
            "",
        )
    )
