"""Application-owned repositories for inspectable local state."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from chief_of_staff.domain.models import (
    AuthorizationStatus,
    BriefingArchivedFact,
    BriefingCoverage,
    BriefingPresentation,
    BriefingPresentationItem,
    BriefingPresentationSection,
    BriefingPresentationSource,
    BriefingPresentationState,
    BriefingRun,
    BriefingStatus,
    Classification,
    Conclusion,
    ConclusionKind,
    ConclusionProjection,
    ConclusionState,
    ConnectorAuthorizationMetadata,
    ConnectorDomain,
    ConnectorInstanceMetadata,
    ConnectorResourceMetadata,
    ConnectorRun,
    CoverageStatus,
    CredentialHealth,
    DispositionEvent,
    DispositionKind,
    DispositionResult,
    NormalizedGmailMessage,
    NormalizedJiraIssue,
    NormalizedSourceTask,
    OAuthClientMetadata,
    RecurrenceAction,
    RecurrenceDecision,
    ScheduledOccurrence,
    ScheduledOutcome,
    ScheduledTrial,
    SourceEvidence,
    StateInspection,
)
from chief_of_staff.inference.models import InferenceAuditRecord
from chief_of_staff.persistence.database import Database

_SUPPRESSING_DISPOSITIONS = frozenset(
    {
        DispositionKind.DISMISSED,
        DispositionKind.DELEGATED,
        DispositionKind.RESCHEDULED,
        DispositionKind.COMPLETED,
        DispositionKind.INTENTIONALLY_ABANDONED,
        DispositionKind.DELETED,
    }
)


class StaleConclusionVersionError(RuntimeError):
    """Raised when a correction form targets an outdated local projection."""


class InvalidDispositionError(ValueError):
    """Raised when disposition fields do not satisfy the action contract."""


@dataclass(frozen=True, slots=True)
class SourceTaskReconciliation:
    """Privacy-safe identity counts from replacing one source task snapshot."""

    previous_unique_count: int
    final_unique_count: int
    newly_selected_count: int
    retained_count: int
    removed_count: int
    superseded_snapshot_count: int
    dependency_preserved_count: int


class StateStore:
    """Transactional persistence for runs, evidence, and correction history."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save_connector_instance(self, metadata: ConnectorInstanceMetadata) -> None:
        """Persist one non-secret application-owned connector identity."""

        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT provider FROM connector_instances WHERE id = ?",
                (metadata.id,),
            ).fetchone()
            if existing is not None and str(existing["provider"]) != metadata.provider:
                raise ValueError(
                    "connector instance ID cannot be rebound to another provider"
                )
            connection.execute(
                """
                INSERT INTO connector_instances(
                    id,
                    provider,
                    alias,
                    domain_classification,
                    approved_resource_boundary,
                    approved_scopes,
                    retrieval_configuration,
                    last_coverage_status,
                    last_freshness_at,
                    enabled,
                    retention_policy_reference,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    alias = excluded.alias,
                    domain_classification = excluded.domain_classification,
                    approved_resource_boundary =
                        excluded.approved_resource_boundary,
                    approved_scopes = excluded.approved_scopes,
                    retrieval_configuration =
                        excluded.retrieval_configuration,
                    last_coverage_status = excluded.last_coverage_status,
                    last_freshness_at = excluded.last_freshness_at,
                    enabled = excluded.enabled,
                    retention_policy_reference =
                        excluded.retention_policy_reference,
                    updated_at = excluded.updated_at
                """,
                _connector_instance_values(metadata),
            )

    def get_connector_instance(
        self,
        connector_instance_id: str,
    ) -> ConnectorInstanceMetadata | None:
        """Return one instance without exposing its account identity or secrets."""

        row = self.database.connection.execute(
            "SELECT * FROM connector_instances WHERE id = ?",
            (connector_instance_id,),
        ).fetchone()
        return None if row is None else _connector_instance_from_row(row)

    def list_connector_instances(
        self,
        *,
        provider: str | None = None,
    ) -> tuple[ConnectorInstanceMetadata, ...]:
        """List configured instances, optionally restricted to one provider."""

        if provider is None:
            rows = self.database.connection.execute(
                "SELECT * FROM connector_instances ORDER BY provider, alias, id"
            ).fetchall()
        else:
            rows = self.database.connection.execute(
                """
                SELECT *
                FROM connector_instances
                WHERE provider = ?
                ORDER BY alias, id
                """,
                (provider,),
            ).fetchall()
        return tuple(_connector_instance_from_row(row) for row in rows)

    def update_connector_instance_coverage(
        self,
        connector_instance_id: str,
        *,
        coverage_status: CoverageStatus,
        freshness_at: datetime | None,
        updated_at: datetime,
    ) -> None:
        """Update coverage for exactly one independently configured account."""

        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE connector_instances
                SET last_coverage_status = ?,
                    last_freshness_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    coverage_status.value,
                    _serialize_optional_datetime(freshness_at),
                    _serialize_datetime(updated_at),
                    connector_instance_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("connector instance metadata is missing")

    def add_connector_run(self, run: ConnectorRun) -> None:
        """Persist connector metadata without a raw source payload."""

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO connector_runs(
                    id,
                    source,
                    approved_scope,
                    retrieval_window_start,
                    retrieval_window_end,
                    started_at,
                    completed_at,
                    status,
                    coverage_status,
                    freshness_at,
                    error_category,
                    page_count,
                    connector_instance_id,
                    record_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.source,
                    run.approved_scope,
                    _serialize_optional_datetime(run.retrieval_window_start),
                    _serialize_optional_datetime(run.retrieval_window_end),
                    _serialize_datetime(run.started_at),
                    _serialize_optional_datetime(run.completed_at),
                    run.status.value,
                    run.coverage_status.value,
                    _serialize_optional_datetime(run.freshness_at),
                    run.error_category,
                    run.page_count,
                    run.connector_instance_id,
                    run.record_count,
                ),
            )

    def save_oauth_client(self, metadata: OAuthClientMetadata) -> None:
        """Persist non-secret OAuth client metadata and Keychain references."""

        with self.database.transaction() as connection:
            connector_instance_id = self._ensure_connector_instance(
                connection,
                provider=metadata.connector,
                connector_instance_id=metadata.connector_instance_id,
                created_at=metadata.configured_at,
            )
            connection.execute(
                """
                INSERT INTO oauth_clients(
                    connector_instance_id,
                    provider,
                    oauth_project_id,
                    oauth_client_id,
                    credential_service,
                    client_secret_account,
                    configured_at,
                    application_owner,
                    oauth_grant_type
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connector_instance_id) DO UPDATE SET
                    provider = excluded.provider,
                    oauth_project_id = excluded.oauth_project_id,
                    oauth_client_id = excluded.oauth_client_id,
                    credential_service = excluded.credential_service,
                    client_secret_account = excluded.client_secret_account,
                    configured_at = excluded.configured_at,
                    application_owner = excluded.application_owner,
                    oauth_grant_type = excluded.oauth_grant_type
                """,
                (
                    connector_instance_id,
                    metadata.connector,
                    metadata.oauth_project_id,
                    metadata.oauth_client_id,
                    metadata.credential_service,
                    metadata.client_secret_account,
                    _serialize_datetime(metadata.configured_at),
                    metadata.application_owner,
                    metadata.oauth_grant_type,
                ),
            )

    def get_oauth_client(
        self,
        connector_or_instance_id: str,
    ) -> OAuthClientMetadata | None:
        """Return non-secret OAuth client metadata."""

        connector_instance_id = self._resolve_connector_instance_id(
            connector_or_instance_id
        )
        if connector_instance_id is None:
            return None
        row = self.database.connection.execute(
            "SELECT * FROM oauth_clients WHERE connector_instance_id = ?",
            (connector_instance_id,),
        ).fetchone()
        if row is None:
            return None
        return OAuthClientMetadata(
            connector=str(row["provider"]),
            oauth_project_id=str(row["oauth_project_id"]),
            oauth_client_id=str(row["oauth_client_id"]),
            credential_service=str(row["credential_service"]),
            client_secret_account=str(row["client_secret_account"]),
            configured_at=_parse_datetime(str(row["configured_at"])),
            application_owner=(
                None
                if row["application_owner"] is None
                else str(row["application_owner"])
            ),
            oauth_grant_type=(
                None
                if row["oauth_grant_type"] is None
                else str(row["oauth_grant_type"])
            ),
            connector_instance_id=str(row["connector_instance_id"]),
        )

    def save_connector_authorization(
        self,
        metadata: ConnectorAuthorizationMetadata,
    ) -> None:
        """Persist non-secret authorization health and Keychain references."""

        connector_instance_id = (
            metadata.connector_instance_id
            or self._resolve_connector_instance_id(metadata.connector)
        )
        if connector_instance_id is None:
            raise ValueError("connector instance metadata is missing")
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO connector_authorizations(
                    connector_instance_id,
                    provider,
                    account_reference,
                    account_identity,
                    granted_scope,
                    credential_service,
                    access_token_account,
                    refresh_token_account,
                    authorization_status,
                    credential_health,
                    refresh_health,
                    token_expires_at,
                    authorized_at,
                    last_used_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connector_instance_id) DO UPDATE SET
                    provider = excluded.provider,
                    account_reference = excluded.account_reference,
                    account_identity = excluded.account_identity,
                    granted_scope = excluded.granted_scope,
                    credential_service = excluded.credential_service,
                    access_token_account = excluded.access_token_account,
                    refresh_token_account = excluded.refresh_token_account,
                    authorization_status = excluded.authorization_status,
                    credential_health = excluded.credential_health,
                    refresh_health = excluded.refresh_health,
                    token_expires_at = excluded.token_expires_at,
                    authorized_at = excluded.authorized_at,
                    last_used_at = excluded.last_used_at,
                    updated_at = excluded.updated_at
                """,
                (
                    connector_instance_id,
                    metadata.connector,
                    metadata.account_reference,
                    metadata.account_identity,
                    metadata.granted_scope,
                    metadata.credential_service,
                    metadata.access_token_account,
                    metadata.refresh_token_account,
                    metadata.authorization_status.value,
                    metadata.credential_health.value,
                    (
                        None
                        if metadata.refresh_health is None
                        else metadata.refresh_health.value
                    ),
                    _serialize_datetime(metadata.token_expires_at),
                    _serialize_datetime(metadata.authorized_at),
                    _serialize_optional_datetime(metadata.last_used_at),
                    _serialize_datetime(metadata.updated_at),
                ),
            )
            connection.execute(
                """
                UPDATE connector_instances
                SET approved_scopes = ?,
                    enabled = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    metadata.granted_scope,
                    int(
                        metadata.authorization_status is AuthorizationStatus.AUTHORIZED
                    ),
                    _serialize_datetime(metadata.updated_at),
                    connector_instance_id,
                ),
            )

    def get_connector_authorization(
        self,
        connector_or_instance_id: str,
    ) -> ConnectorAuthorizationMetadata | None:
        """Return inspectable authorization metadata without secret values."""

        connector_instance_id = self._resolve_connector_instance_id(
            connector_or_instance_id
        )
        if connector_instance_id is None:
            return None
        row = self.database.connection.execute(
            """
            SELECT *
            FROM connector_authorizations
            WHERE connector_instance_id = ?
            """,
            (connector_instance_id,),
        ).fetchone()
        if row is None:
            return None
        return ConnectorAuthorizationMetadata(
            connector=str(row["provider"]),
            account_reference=str(row["account_reference"]),
            account_identity=str(row["account_identity"]),
            granted_scope=str(row["granted_scope"]),
            credential_service=str(row["credential_service"]),
            access_token_account=str(row["access_token_account"]),
            refresh_token_account=(
                None
                if row["refresh_token_account"] is None
                else str(row["refresh_token_account"])
            ),
            authorization_status=AuthorizationStatus(str(row["authorization_status"])),
            credential_health=CredentialHealth(str(row["credential_health"])),
            refresh_health=(
                None
                if row["refresh_health"] is None
                else CredentialHealth(str(row["refresh_health"]))
            ),
            token_expires_at=_parse_datetime(str(row["token_expires_at"])),
            authorized_at=_parse_datetime(str(row["authorized_at"])),
            last_used_at=_parse_optional_datetime(
                None if row["last_used_at"] is None else str(row["last_used_at"])
            ),
            updated_at=_parse_datetime(str(row["updated_at"])),
            connector_instance_id=str(row["connector_instance_id"]),
        )

    def save_connector_resource(self, metadata: ConnectorResourceMetadata) -> None:
        """Persist one non-secret resource-level connector boundary."""

        connector_instance_id = (
            metadata.connector_instance_id
            or self._resolve_connector_instance_id(metadata.connector)
        )
        if connector_instance_id is None:
            raise ValueError("connector instance metadata is missing")
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO connector_resources(
                    connector_instance_id,
                    provider,
                    resource_reference,
                    resource_id,
                    resource_url,
                    resource_type,
                    grant_type,
                    selected_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connector_instance_id) DO UPDATE SET
                    provider = excluded.provider,
                    resource_reference = excluded.resource_reference,
                    resource_id = excluded.resource_id,
                    resource_url = excluded.resource_url,
                    resource_type = excluded.resource_type,
                    grant_type = excluded.grant_type,
                    selected_at = excluded.selected_at
                """,
                (
                    connector_instance_id,
                    metadata.connector,
                    metadata.resource_reference,
                    metadata.resource_id,
                    metadata.resource_url,
                    metadata.resource_type,
                    metadata.grant_type,
                    _serialize_datetime(metadata.selected_at),
                ),
            )

    def get_connector_resource(
        self,
        connector_or_instance_id: str,
    ) -> ConnectorResourceMetadata | None:
        """Return the selected non-secret resource boundary."""

        connector_instance_id = self._resolve_connector_instance_id(
            connector_or_instance_id
        )
        if connector_instance_id is None:
            return None
        row = self.database.connection.execute(
            "SELECT * FROM connector_resources WHERE connector_instance_id = ?",
            (connector_instance_id,),
        ).fetchone()
        if row is None:
            return None
        return ConnectorResourceMetadata(
            connector=str(row["provider"]),
            resource_reference=str(row["resource_reference"]),
            resource_id=str(row["resource_id"]),
            resource_url=str(row["resource_url"]),
            resource_type=str(row["resource_type"]),
            grant_type=str(row["grant_type"]),
            selected_at=_parse_datetime(str(row["selected_at"])),
            connector_instance_id=str(row["connector_instance_id"]),
        )

    def mark_connector_authorization_used(
        self,
        connector_or_instance_id: str,
        *,
        used_at: datetime,
    ) -> None:
        """Record successful use without changing or reading a credential."""

        connector_instance_id = self._required_connector_instance_id(
            connector_or_instance_id
        )
        timestamp = _serialize_datetime(used_at)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE connector_authorizations
                SET last_used_at = ?, updated_at = ?
                WHERE connector_instance_id = ?
                """,
                (timestamp, timestamp, connector_instance_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("connector authorization metadata is missing")

    def set_connector_authorization_health(
        self,
        connector_or_instance_id: str,
        *,
        status: AuthorizationStatus,
        health: CredentialHealth,
        updated_at: datetime,
    ) -> None:
        """Update non-secret health after expiry or provider rejection."""

        connector_instance_id = self._required_connector_instance_id(
            connector_or_instance_id
        )
        timestamp = _serialize_datetime(updated_at)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE connector_authorizations
                SET authorization_status = ?,
                    credential_health = ?,
                    updated_at = ?
                WHERE connector_instance_id = ?
                """,
                (
                    status.value,
                    health.value,
                    timestamp,
                    connector_instance_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("connector authorization metadata is missing")

    def delete_connector_configuration(self, connector_or_instance_id: str) -> None:
        """Delete non-secret metadata after credentials are removed."""

        connector_instance_id = self._required_connector_instance_id(
            connector_or_instance_id
        )
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM oauth_clients WHERE connector_instance_id = ?",
                (connector_instance_id,),
            )

    def delete_connector_instance(self, connector_instance_id: str) -> bool:
        """Delete one exact retired instance after its secrets are removed."""

        if not connector_instance_id.strip():
            raise ValueError("connector instance ID must not be empty")
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM connector_instances WHERE id = ?",
                (connector_instance_id,),
            )
        return cursor.rowcount > 0

    def delete_connector_authorization(self, connector_or_instance_id: str) -> bool:
        """Delete only non-secret grant metadata after token cleanup."""

        connector_instance_id = self._required_connector_instance_id(
            connector_or_instance_id
        )
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                DELETE FROM connector_authorizations
                WHERE connector_instance_id = ?
                """,
                (connector_instance_id,),
            )
            if cursor.rowcount:
                connection.execute(
                    """
                    UPDATE connector_instances
                    SET enabled = 0,
                        updated_at = strftime(
                            '%Y-%m-%dT%H:%M:%f+00:00',
                            'now'
                        )
                    WHERE id = ?
                    """,
                    (connector_instance_id,),
                )
        return cursor.rowcount > 0

    def _resolve_connector_instance_id(
        self,
        connector_or_instance_id: str,
    ) -> str | None:
        if not connector_or_instance_id.strip():
            raise ValueError("connector identity must not be empty")
        exact = self.database.connection.execute(
            "SELECT id FROM connector_instances WHERE id = ?",
            (connector_or_instance_id,),
        ).fetchone()
        if exact is not None:
            return str(exact["id"])
        rows = self.database.connection.execute(
            "SELECT id FROM connector_instances WHERE provider = ? ORDER BY id",
            (connector_or_instance_id,),
        ).fetchall()
        if len(rows) > 1:
            raise ValueError(
                "provider has multiple connector instances; use an instance ID"
            )
        return None if not rows else str(rows[0]["id"])

    def _required_connector_instance_id(
        self,
        connector_or_instance_id: str,
    ) -> str:
        connector_instance_id = self._resolve_connector_instance_id(
            connector_or_instance_id
        )
        if connector_instance_id is None:
            raise ValueError("connector instance metadata is missing")
        return connector_instance_id

    def _ensure_connector_instance(
        self,
        connection: sqlite3.Connection,
        *,
        provider: str,
        connector_instance_id: str | None,
        created_at: datetime,
    ) -> str:
        if not provider.strip():
            raise ValueError("connector provider must not be empty")
        if connector_instance_id is None:
            rows = connection.execute(
                "SELECT id FROM connector_instances WHERE provider = ? ORDER BY id",
                (provider,),
            ).fetchall()
            if len(rows) > 1:
                raise ValueError(
                    "provider has multiple connector instances; use an instance ID"
                )
            if rows:
                return str(rows[0]["id"])
            connector_instance_id = f"{provider}:primary"
        elif not connector_instance_id.strip():
            raise ValueError("connector instance ID must not be empty")

        timestamp = _serialize_datetime(created_at)
        connection.execute(
            """
            INSERT INTO connector_instances(
                id,
                provider,
                alias,
                domain_classification,
                approved_resource_boundary,
                approved_scopes,
                retrieval_configuration,
                enabled,
                retention_policy_reference,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, 'unclassified', ?, 'not-authorized',
                    'provider-default', 0, 'adr-0004-default', ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                connector_instance_id,
                provider,
                provider.replace("_", " ").title(),
                provider,
                timestamp,
                timestamp,
            ),
        )
        row = connection.execute(
            "SELECT provider FROM connector_instances WHERE id = ?",
            (connector_instance_id,),
        ).fetchone()
        if row is None or str(row["provider"]) != provider:
            raise ValueError("connector instance provider does not match metadata")
        return connector_instance_id

    def _source_snapshot_instance(
        self,
        *,
        source: str,
        connector_instance_id: str | None,
        normalized_table: str,
    ) -> str | None:
        queries = {
            "normalized_source_tasks": """
                SELECT DISTINCT evidence.connector_instance_id
                FROM source_evidence AS evidence
                JOIN normalized_source_tasks AS normalized
                    ON normalized.evidence_id = evidence.id
                WHERE evidence.source = ?
            """,
            "normalized_jira_issues": """
                SELECT DISTINCT evidence.connector_instance_id
                FROM source_evidence AS evidence
                JOIN normalized_jira_issues AS normalized
                    ON normalized.evidence_id = evidence.id
                WHERE evidence.source = ?
            """,
        }
        query = queries.get(normalized_table)
        if query is None:
            raise ValueError("unsupported normalized source table")
        if connector_instance_id is not None:
            row = self.database.connection.execute(
                "SELECT provider FROM connector_instances WHERE id = ?",
                (connector_instance_id,),
            ).fetchone()
            if row is None or str(row["provider"]) != source:
                raise ValueError(
                    "connector instance does not match the source snapshot"
                )
            return connector_instance_id

        rows = self.database.connection.execute(
            query,
            (source,),
        ).fetchall()
        instance_values = {
            None
            if row["connector_instance_id"] is None
            else str(row["connector_instance_id"])
            for row in rows
        }
        if len(instance_values) > 1:
            raise ValueError(
                "source has multiple connector instances; use an instance ID"
            )
        if instance_values:
            return next(iter(instance_values))

        provider_rows = self.database.connection.execute(
            "SELECT id FROM connector_instances WHERE provider = ?",
            (source,),
        ).fetchall()
        if len(provider_rows) > 1:
            raise ValueError(
                "provider has multiple connector instances; use an instance ID"
            )
        return None if not provider_rows else str(provider_rows[0]["id"])

    def add_briefing_run(self, run: BriefingRun) -> None:
        """Persist one versioned briefing-run record."""

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO briefing_runs(
                    id,
                    briefing_date,
                    timezone,
                    invocation_mode,
                    started_at,
                    completed_at,
                    status,
                    generated_at,
                    as_of,
                    historical_mode,
                    originating_recorded_run_id,
                    processing_versions_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.briefing_date.isoformat(),
                    run.timezone,
                    run.invocation_mode,
                    _serialize_datetime(run.started_at),
                    _serialize_optional_datetime(run.completed_at),
                    run.status.value,
                    _serialize_optional_datetime(run.generated_at),
                    _serialize_optional_datetime(run.as_of),
                    run.historical_mode,
                    run.originating_recorded_run_id,
                    run.processing_versions_json,
                ),
            )

    def add_inference_audit(self, audit: InferenceAuditRecord) -> None:
        """Persist provider and validation metadata without inference content."""

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO inference_audits(
                    id,
                    briefing_run_id,
                    candidate_id_hash,
                    task_name,
                    task_version,
                    prompt_version,
                    schema_version,
                    policy_version,
                    model_configuration_version,
                    provider,
                    model_id,
                    sensitivity_tier,
                    status,
                    validation_status,
                    request_count,
                    latency_ms,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    estimated_cost_microusd,
                    error_category,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?)
                """,
                (
                    audit.id,
                    audit.briefing_run_id,
                    audit.candidate_id_hash,
                    audit.task_name,
                    audit.task_version,
                    audit.prompt_version,
                    audit.schema_version,
                    audit.policy_version,
                    audit.model_configuration_version,
                    audit.provider,
                    audit.model_id,
                    audit.sensitivity_tier.value,
                    audit.status.value,
                    (
                        None
                        if audit.validation_status is None
                        else audit.validation_status.value
                    ),
                    audit.request_count,
                    audit.latency_ms,
                    audit.input_tokens,
                    audit.output_tokens,
                    audit.total_tokens,
                    audit.estimated_cost_microusd,
                    audit.error_category,
                    _serialize_datetime(audit.created_at),
                ),
            )

    def link_connector_run(self, briefing_run_id: str, connector_run_id: str) -> None:
        """Associate source coverage with a briefing run."""

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO briefing_connector_runs(
                    briefing_run_id,
                    connector_run_id
                )
                VALUES (?, ?)
                """,
                (briefing_run_id, connector_run_id),
            )

    def add_source_evidence(self, evidence: SourceEvidence) -> None:
        """Persist only the minimal evidence required for provenance."""

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO source_evidence(
                    id,
                    connector_run_id,
                    connector_instance_id,
                    source,
                    source_record_id,
                    display_url,
                    excerpt,
                    evidence_fingerprint,
                    retrieved_at,
                    freshness_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.id,
                    evidence.connector_run_id,
                    evidence.connector_instance_id,
                    evidence.source,
                    evidence.source_record_id,
                    evidence.display_url,
                    evidence.excerpt,
                    evidence.evidence_fingerprint,
                    _serialize_datetime(evidence.retrieved_at),
                    _serialize_optional_datetime(evidence.freshness_at),
                ),
            )

    def update_source_evidence_excerpt(
        self,
        evidence_id: str,
        excerpt: str,
    ) -> None:
        """Attach one minimized local excerpt after transient source processing."""

        minimized = excerpt.strip()
        if not minimized or len(minimized) > 2000:
            raise ValueError("source evidence excerpt is invalid")
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE source_evidence SET excerpt = ? WHERE id = ?",
                (minimized, evidence_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("source evidence is missing")

    def add_normalized_source_task(self, task: NormalizedSourceTask) -> None:
        """Persist one selected task and only its minimal resolved context."""

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO normalized_source_tasks(
                    evidence_id,
                    title,
                    provider_priority,
                    recurring,
                    all_day,
                    due_at,
                    project_id,
                    project_name,
                    section_id,
                    section_name,
                    responsible_user_id,
                    parent_task_id,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.evidence_id,
                    task.title,
                    task.provider_priority,
                    int(task.recurring),
                    int(task.all_day),
                    _serialize_optional_datetime(task.due_at),
                    task.project_id,
                    task.project_name,
                    task.section_id,
                    task.section_name,
                    task.responsible_user_id,
                    task.parent_task_id,
                    _serialize_optional_datetime(task.created_at),
                    _serialize_optional_datetime(task.updated_at),
                ),
            )
            connection.executemany(
                """
                INSERT INTO normalized_source_task_labels(
                    evidence_id,
                    label_id,
                    label_name
                )
                VALUES (?, ?, ?)
                """,
                (
                    (task.evidence_id, label_id, label_name)
                    for label_id, label_name in task.labels
                ),
            )

    def add_normalized_jira_issue(self, issue: NormalizedJiraIssue) -> None:
        """Persist only the approved normalized Jira issue fields."""

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO normalized_jira_issues(
                    evidence_id,
                    issue_key,
                    summary,
                    project_key,
                    issue_type,
                    status,
                    status_category,
                    assignee_account_id,
                    priority_name,
                    due_date,
                    created_at,
                    updated_at,
                    parent_key
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    issue.evidence_id,
                    issue.issue_key,
                    issue.summary,
                    issue.project_key,
                    issue.issue_type,
                    issue.status,
                    issue.status_category,
                    issue.assignee_account_id,
                    issue.priority_name,
                    None if issue.due_date is None else issue.due_date.isoformat(),
                    _serialize_datetime(issue.created_at),
                    _serialize_datetime(issue.updated_at),
                    issue.parent_key,
                ),
            )
            connection.executemany(
                """
                INSERT INTO normalized_jira_issue_labels(evidence_id, label)
                VALUES (?, ?)
                """,
                ((issue.evidence_id, label) for label in issue.labels),
            )
            connection.executemany(
                """
                INSERT INTO normalized_jira_issue_links(
                    evidence_id,
                    relationship,
                    related_issue_id,
                    related_issue_key,
                    display_url
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (
                        issue.evidence_id,
                        link.relationship,
                        link.issue_id,
                        link.issue_key,
                        link.display_url,
                    )
                    for link in issue.links
                ),
            )

    def add_normalized_gmail_message(self, message: NormalizedGmailMessage) -> None:
        """Persist only minimized Work Gmail facts needed after retrieval."""

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO normalized_gmail_messages(
                    evidence_id,
                    thread_id,
                    direction,
                    occurred_at,
                    participant_references,
                    subject,
                    label_classification,
                    detection_type,
                    processing_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.evidence_id,
                    message.thread_id,
                    message.direction,
                    _serialize_datetime(message.occurred_at),
                    json.dumps(message.participant_references),
                    message.subject,
                    message.label_classification,
                    message.detection_type,
                    message.processing_version,
                ),
            )

    def prune_unselected_source_tasks(
        self,
        *,
        source: str,
        retained_source_record_ids: frozenset[str],
        connector_instance_id: str | None = None,
    ) -> int:
        """Delete stale selected-task snapshots unless correction state needs them."""

        if not source.strip():
            raise ValueError("source must not be empty")
        connector_instance_id = self._source_snapshot_instance(
            source=source,
            connector_instance_id=connector_instance_id,
            normalized_table="normalized_source_tasks",
        )
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT evidence.id, evidence.source_record_id
                FROM source_evidence AS evidence
                JOIN normalized_source_tasks AS task
                    ON task.evidence_id = evidence.id
                WHERE evidence.source = ?
                  AND (
                      (? IS NULL AND evidence.connector_instance_id IS NULL)
                      OR evidence.connector_instance_id = ?
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM conclusion_evidence AS link
                      WHERE link.evidence_id = evidence.id
                  )
                """,
                (source, connector_instance_id, connector_instance_id),
            ).fetchall()
            stale_evidence_ids = tuple(
                str(row["id"])
                for row in rows
                if str(row["source_record_id"]) not in retained_source_record_ids
            )
            connection.executemany(
                "DELETE FROM source_evidence WHERE id = ?",
                ((evidence_id,) for evidence_id in stale_evidence_ids),
            )
        return len(stale_evidence_ids)

    def reconcile_source_task_snapshot(
        self,
        *,
        source: str,
        current_evidence_ids: dict[str, str],
        connector_instance_id: str | None = None,
    ) -> SourceTaskReconciliation:
        """Replace source task snapshots while preserving conclusion evidence."""

        if not source.strip():
            raise ValueError("source must not be empty")
        if any(
            not key.strip() or not value.strip()
            for key, value in current_evidence_ids.items()
        ):
            raise ValueError("current evidence identifiers must not be empty")
        connector_instance_id = self._source_snapshot_instance(
            source=source,
            connector_instance_id=connector_instance_id,
            normalized_table="normalized_source_tasks",
        )
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT
                    evidence.id,
                    evidence.source_record_id,
                    EXISTS (
                        SELECT 1
                        FROM conclusion_evidence AS link
                        WHERE link.evidence_id = evidence.id
                    ) AS has_dependency
                FROM source_evidence AS evidence
                JOIN normalized_source_tasks AS task
                    ON task.evidence_id = evidence.id
                WHERE evidence.source = ?
                  AND (
                      (? IS NULL AND evidence.connector_instance_id IS NULL)
                      OR evidence.connector_instance_id = ?
                  )
                """,
                (source, connector_instance_id, connector_instance_id),
            ).fetchall()
            previous_ids = {
                str(row["source_record_id"])
                for row in rows
                if str(row["id"]) not in current_evidence_ids.values()
            }
            current_ids = set(current_evidence_ids)
            superseded = tuple(
                row
                for row in rows
                if current_evidence_ids.get(str(row["source_record_id"]))
                != str(row["id"])
            )
            deletable_ids = tuple(
                str(row["id"]) for row in superseded if not bool(row["has_dependency"])
            )
            connection.executemany(
                "DELETE FROM source_evidence WHERE id = ?",
                ((evidence_id,) for evidence_id in deletable_ids),
            )
            final_rows = connection.execute(
                """
                SELECT DISTINCT evidence.source_record_id
                FROM source_evidence AS evidence
                JOIN normalized_source_tasks AS task
                    ON task.evidence_id = evidence.id
                WHERE evidence.source = ?
                  AND (
                      (? IS NULL AND evidence.connector_instance_id IS NULL)
                      OR evidence.connector_instance_id = ?
                  )
                """,
                (source, connector_instance_id, connector_instance_id),
            ).fetchall()
            final_unique_count = len(
                current_ids & {str(row["source_record_id"]) for row in final_rows}
            )
        return SourceTaskReconciliation(
            previous_unique_count=len(previous_ids),
            final_unique_count=final_unique_count,
            newly_selected_count=len(current_ids - previous_ids),
            retained_count=len(current_ids & previous_ids),
            removed_count=len(previous_ids - current_ids),
            superseded_snapshot_count=len(deletable_ids),
            dependency_preserved_count=len(superseded) - len(deletable_ids),
        )

    def reconcile_jira_issue_snapshot(
        self,
        *,
        current_evidence_ids: dict[str, str],
        connector_instance_id: str | None = None,
    ) -> SourceTaskReconciliation:
        """Replace the complete Jira issue snapshot while preserving dependencies."""

        if any(
            not key.strip() or not value.strip()
            for key, value in current_evidence_ids.items()
        ):
            raise ValueError("current Jira evidence identifiers must not be empty")
        connector_instance_id = self._source_snapshot_instance(
            source="jira",
            connector_instance_id=connector_instance_id,
            normalized_table="normalized_jira_issues",
        )
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT
                    evidence.id,
                    evidence.source_record_id,
                    EXISTS (
                        SELECT 1
                        FROM conclusion_evidence AS link
                        WHERE link.evidence_id = evidence.id
                    ) AS has_dependency
                FROM source_evidence AS evidence
                JOIN normalized_jira_issues AS issue
                    ON issue.evidence_id = evidence.id
                WHERE evidence.source = 'jira'
                  AND (
                      (? IS NULL AND evidence.connector_instance_id IS NULL)
                      OR evidence.connector_instance_id = ?
                  )
                """,
                (connector_instance_id, connector_instance_id),
            ).fetchall()
            previous_ids = {
                str(row["source_record_id"])
                for row in rows
                if str(row["id"]) not in current_evidence_ids.values()
            }
            current_ids = set(current_evidence_ids)
            superseded = tuple(
                row
                for row in rows
                if current_evidence_ids.get(str(row["source_record_id"]))
                != str(row["id"])
            )
            deletable_ids = tuple(
                str(row["id"]) for row in superseded if not bool(row["has_dependency"])
            )
            connection.executemany(
                "DELETE FROM source_evidence WHERE id = ?",
                ((evidence_id,) for evidence_id in deletable_ids),
            )
            final_rows = connection.execute(
                """
                SELECT DISTINCT evidence.source_record_id
                FROM source_evidence AS evidence
                JOIN normalized_jira_issues AS issue
                    ON issue.evidence_id = evidence.id
                WHERE evidence.source = 'jira'
                  AND (
                      (? IS NULL AND evidence.connector_instance_id IS NULL)
                      OR evidence.connector_instance_id = ?
                  )
                """,
                (connector_instance_id, connector_instance_id),
            ).fetchall()
            final_unique_count = len(
                current_ids & {str(row["source_record_id"]) for row in final_rows}
            )
        return SourceTaskReconciliation(
            previous_unique_count=len(previous_ids),
            final_unique_count=final_unique_count,
            newly_selected_count=len(current_ids - previous_ids),
            retained_count=len(current_ids & previous_ids),
            removed_count=len(previous_ids - current_ids),
            superseded_snapshot_count=len(deletable_ids),
            dependency_preserved_count=len(superseded) - len(deletable_ids),
        )

    def add_conclusion(self, conclusion: Conclusion) -> None:
        """Persist a conclusion and its ordered source-evidence links."""

        if not conclusion.evidence_ids:
            raise ValueError("a conclusion requires at least one evidence reference")

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO conclusions(
                    id,
                    kind,
                    classification,
                    statement,
                    explanation,
                    confidence,
                    evidence_fingerprint,
                    processing_version,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conclusion.id,
                    conclusion.kind.value,
                    conclusion.classification.value,
                    conclusion.statement,
                    conclusion.explanation,
                    conclusion.confidence,
                    conclusion.evidence_fingerprint,
                    conclusion.processing_version,
                    _serialize_datetime(conclusion.created_at),
                ),
            )
            connection.executemany(
                """
                INSERT INTO conclusion_evidence(
                    conclusion_id,
                    evidence_id,
                    ordinal
                )
                VALUES (?, ?, ?)
                """,
                (
                    (conclusion.id, evidence_id, ordinal)
                    for ordinal, evidence_id in enumerate(conclusion.evidence_ids)
                ),
            )
            connection.execute(
                """
                INSERT INTO conclusion_current_state(
                    conclusion_id,
                    current_state,
                    display_statement,
                    version,
                    updated_at
                )
                VALUES (?, 'active', ?, 0, ?)
                """,
                (
                    conclusion.id,
                    conclusion.statement,
                    _serialize_datetime(conclusion.created_at),
                ),
            )

    def append_disposition(self, event: DispositionEvent) -> None:
        """Append a user-controlled disposition without replacing history."""

        projection = self.get_conclusion_projection(event.conclusion_id)
        if projection is None:
            raise ValueError("conclusion is missing")
        self.apply_disposition(
            conclusion_id=event.conclusion_id,
            disposition=event.disposition,
            expected_version=projection.version,
            idempotency_key=f"legacy-api:{event.id}",
            created_at=event.created_at,
            briefing_run_id=event.briefing_run_id,
            replacement_text=event.replacement_text,
            explanation=event.note,
            delegate_description=event.delegate_description,
            follow_up_at=event.follow_up_at,
            rescheduled_for=event.rescheduled_for,
            event_id=event.id,
            allow_legacy_missing_fields=True,
        )

    def get_conclusion_projection(
        self,
        conclusion_id: str,
    ) -> ConclusionProjection | None:
        """Return the derived current local state for one conclusion."""

        row = self.database.connection.execute(
            """
            SELECT *
            FROM conclusion_current_state
            WHERE conclusion_id = ?
            """,
            (conclusion_id,),
        ).fetchone()
        return None if row is None else _conclusion_projection_from_row(row)

    def apply_disposition(
        self,
        *,
        conclusion_id: str,
        disposition: DispositionKind,
        expected_version: int,
        idempotency_key: str,
        created_at: datetime,
        briefing_run_id: str | None = None,
        replacement_text: str | None = None,
        explanation: str | None = None,
        delegate_description: str | None = None,
        follow_up_at: datetime | None = None,
        rescheduled_for: datetime | None = None,
        event_id: str | None = None,
        allow_legacy_missing_fields: bool = False,
    ) -> DispositionResult:
        """Apply one validated local-only disposition transactionally."""

        if disposition is DispositionKind.DELETED:
            raise InvalidDispositionError(
                "deletion uses the dedicated local-deletion operation"
            )
        _require_aware(created_at)
        if follow_up_at is not None:
            _require_aware(follow_up_at)
        if rescheduled_for is not None:
            _require_aware(rescheduled_for)
        normalized_key = idempotency_key.strip()
        if len(normalized_key) < 16 or len(normalized_key) > 200:
            raise InvalidDispositionError("idempotency key is invalid")
        normalized_replacement = _bounded_optional_text(
            replacement_text,
            field="corrected interpretation",
            maximum=1000,
        )
        normalized_explanation = _bounded_optional_text(
            explanation,
            field="explanation",
            maximum=1000,
        )
        normalized_delegate = _bounded_optional_text(
            delegate_description,
            field="delegate description",
            maximum=300,
        )
        if disposition is DispositionKind.CORRECTED and not normalized_replacement:
            raise InvalidDispositionError(
                "a corrected disposition requires corrected interpretation"
            )
        if (
            disposition is DispositionKind.DELEGATED
            and not normalized_delegate
            and not allow_legacy_missing_fields
        ):
            raise InvalidDispositionError(
                "a delegated disposition requires a delegate description"
            )
        if (
            disposition is DispositionKind.RESCHEDULED
            and rescheduled_for is None
            and not allow_legacy_missing_fields
        ):
            raise InvalidDispositionError(
                "a rescheduled disposition requires a local date and time"
            )

        with self.database.transaction() as connection:
            existing_row = connection.execute(
                """
                SELECT *
                FROM disposition_events
                WHERE idempotency_key = ?
                """,
                (normalized_key,),
            ).fetchone()
            if existing_row is not None:
                if (
                    str(existing_row["conclusion_id"]) != conclusion_id
                    or str(existing_row["disposition"]) != disposition.value
                ):
                    raise InvalidDispositionError(
                        "idempotency key was already used for another action"
                    )
                projection_row = connection.execute(
                    """
                    SELECT *
                    FROM conclusion_current_state
                    WHERE conclusion_id = ?
                    """,
                    (conclusion_id,),
                ).fetchone()
                if projection_row is None:
                    raise RuntimeError("conclusion projection is missing")
                return DispositionResult(
                    applied=False,
                    projection=_conclusion_projection_from_row(projection_row),
                    event=_disposition_from_row(existing_row),
                )

            state_row = connection.execute(
                """
                SELECT
                    state.*,
                    conclusion.evidence_fingerprint,
                    conclusion.processing_version
                FROM conclusion_current_state AS state
                JOIN conclusions AS conclusion
                    ON conclusion.id = state.conclusion_id
                WHERE state.conclusion_id = ?
                """,
                (conclusion_id,),
            ).fetchone()
            if state_row is None:
                raise KeyError("conclusion is missing")
            current_version = int(state_row["version"])
            if expected_version != current_version:
                raise StaleConclusionVersionError(
                    "the local conclusion changed; reload before trying again"
                )

            previous_state = str(state_row["current_state"])
            resulting_version = current_version + 1
            new_display_statement = str(state_row["display_statement"])
            if disposition is DispositionKind.CORRECTED:
                if normalized_replacement is None:
                    raise AssertionError("corrected text was validated")
                new_display_statement = normalized_replacement

            new_delegate = (
                normalized_delegate
                if disposition is DispositionKind.DELEGATED
                else None
            )
            new_follow_up = (
                follow_up_at if disposition is DispositionKind.DELEGATED else None
            )
            new_rescheduled = (
                rescheduled_for if disposition is DispositionKind.RESCHEDULED else None
            )
            selected_event_id = event_id or uuid.uuid4().hex
            connection.execute(
                """
                INSERT INTO disposition_events(
                    id,
                    conclusion_id,
                    originating_briefing_id,
                    disposition,
                    previous_state,
                    new_state,
                    replacement_text,
                    explanation,
                    delegate_description,
                    follow_up_at,
                    rescheduled_for,
                    evidence_fingerprint,
                    processing_version,
                    expected_version,
                    resulting_version,
                    idempotency_key,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    selected_event_id,
                    conclusion_id,
                    briefing_run_id,
                    disposition.value,
                    previous_state,
                    disposition.value,
                    normalized_replacement,
                    normalized_explanation,
                    new_delegate,
                    _serialize_optional_datetime(new_follow_up),
                    _serialize_optional_datetime(new_rescheduled),
                    str(state_row["evidence_fingerprint"]),
                    str(state_row["processing_version"]),
                    current_version,
                    resulting_version,
                    normalized_key,
                    _serialize_datetime(created_at),
                ),
            )
            connection.execute(
                """
                UPDATE conclusion_current_state
                SET current_state = ?,
                    display_statement = ?,
                    delegate_description = ?,
                    follow_up_at = ?,
                    rescheduled_for = ?,
                    version = ?,
                    last_event_id = ?,
                    updated_at = ?
                WHERE conclusion_id = ?
                """,
                (
                    disposition.value,
                    new_display_statement,
                    new_delegate,
                    _serialize_optional_datetime(new_follow_up),
                    _serialize_optional_datetime(new_rescheduled),
                    resulting_version,
                    selected_event_id,
                    _serialize_datetime(created_at),
                    conclusion_id,
                ),
            )
            event_row = connection.execute(
                "SELECT * FROM disposition_events WHERE id = ?",
                (selected_event_id,),
            ).fetchone()
            projection_row = connection.execute(
                """
                SELECT *
                FROM conclusion_current_state
                WHERE conclusion_id = ?
                """,
                (conclusion_id,),
            ).fetchone()
            if event_row is None or projection_row is None:
                raise RuntimeError("disposition projection failed")
            return DispositionResult(
                applied=True,
                projection=_conclusion_projection_from_row(projection_row),
                event=_disposition_from_row(event_row),
            )

    def inspect_conclusion(self, conclusion_id: str) -> ConclusionState | None:
        """Return a conclusion with ordered evidence and full event history."""

        connection = self.database.connection
        conclusion_row = connection.execute(
            "SELECT * FROM conclusions WHERE id = ?",
            (conclusion_id,),
        ).fetchone()
        if conclusion_row is None:
            return None

        evidence_rows = connection.execute(
            """
            SELECT evidence.*
            FROM source_evidence AS evidence
            JOIN conclusion_evidence AS link ON link.evidence_id = evidence.id
            WHERE link.conclusion_id = ?
            ORDER BY link.ordinal
            """,
            (conclusion_id,),
        ).fetchall()
        history_rows = connection.execute(
            """
            SELECT *
            FROM disposition_events
            WHERE conclusion_id = ?
            ORDER BY created_at, id
            """,
            (conclusion_id,),
        ).fetchall()

        evidence = tuple(_source_evidence_from_row(row) for row in evidence_rows)
        conclusion = _conclusion_from_row(
            conclusion_row,
            tuple(item.id for item in evidence),
        )
        history = tuple(_disposition_from_row(row) for row in history_rows)
        projection = self.get_conclusion_projection(conclusion_id)
        return ConclusionState(
            conclusion=conclusion,
            evidence=evidence,
            history=history,
            projection=projection,
        )

    def find_conclusion_id_by_source_records(
        self,
        source_records: tuple[tuple[str, str], ...],
    ) -> str | None:
        """Resolve one unambiguous local conclusion from source-owned identity."""

        conclusion_ids: set[str] = set()
        for source, source_record_id in source_records:
            rows = self.database.connection.execute(
                """
                SELECT DISTINCT conclusion.id
                FROM conclusions AS conclusion
                JOIN conclusion_evidence AS link
                    ON link.conclusion_id = conclusion.id
                JOIN source_evidence AS evidence
                    ON evidence.id = link.evidence_id
                WHERE evidence.source = ?
                  AND evidence.source_record_id = ?
                """,
                (source, source_record_id),
            ).fetchall()
            conclusion_ids.update(str(row["id"]) for row in rows)
        if len(conclusion_ids) != 1:
            return None
        return next(iter(conclusion_ids))

    def recurrence_decision(
        self,
        evidence_fingerprint: str,
        *,
        source_records: tuple[tuple[str, str], ...] = (),
        effective_at: datetime | None = None,
    ) -> RecurrenceDecision:
        """Project prior local state for materially unchanged evidence."""

        connection = self.database.connection
        if effective_at is not None:
            _require_aware(effective_at)
        effective_timestamp = _serialize_optional_datetime(effective_at)
        tombstone_row = connection.execute(
            """
            SELECT evidence_fingerprint
            FROM conclusion_tombstones
            WHERE evidence_fingerprint = ?
              AND (? IS NULL OR deleted_at <= ?)
            """,
            (
                evidence_fingerprint,
                effective_timestamp,
                effective_timestamp,
            ),
        ).fetchone()
        if tombstone_row is not None:
            return RecurrenceDecision(
                action=RecurrenceAction.SUPPRESS,
                disposition=DispositionKind.DELETED,
            )

        conclusion_row = connection.execute(
            """
            SELECT id
            FROM conclusions
            WHERE evidence_fingerprint = ?
              AND (? IS NULL OR created_at <= ?)
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (
                evidence_fingerprint,
                effective_timestamp,
                effective_timestamp,
            ),
        ).fetchone()
        if conclusion_row is None:
            if source_records:
                return self.changed_evidence_decision(
                    evidence_fingerprint,
                    source_records=source_records,
                )
            return RecurrenceDecision(action=RecurrenceAction.SHOW)

        conclusion_id = str(conclusion_row["id"])
        event_row = connection.execute(
            """
            SELECT disposition, replacement_text
            FROM disposition_events
            WHERE conclusion_id = ?
              AND (? IS NULL OR created_at <= ?)
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (conclusion_id, effective_timestamp, effective_timestamp),
        ).fetchone()
        if event_row is None:
            exact = RecurrenceDecision(
                action=RecurrenceAction.SHOW,
                prior_conclusion_id=conclusion_id,
            )
        else:
            disposition = DispositionKind(str(event_row["disposition"]))
            if disposition is DispositionKind.CORRECTED:
                exact = RecurrenceDecision(
                    action=RecurrenceAction.REPLACE,
                    prior_conclusion_id=conclusion_id,
                    replacement_text=str(event_row["replacement_text"]),
                    disposition=disposition,
                )
            elif disposition in _SUPPRESSING_DISPOSITIONS:
                exact = RecurrenceDecision(
                    action=RecurrenceAction.SUPPRESS,
                    prior_conclusion_id=conclusion_id,
                    disposition=disposition,
                )
            else:
                exact = RecurrenceDecision(
                    action=RecurrenceAction.SHOW,
                    prior_conclusion_id=conclusion_id,
                    disposition=disposition,
                )
        return exact

    def changed_evidence_decision(
        self,
        evidence_fingerprint: str,
        *,
        source_records: tuple[tuple[str, str], ...],
    ) -> RecurrenceDecision:
        """Explain reconsideration when known source identity has new evidence."""

        exact = self.recurrence_decision(evidence_fingerprint)
        if (
            exact.prior_conclusion_id is not None
            or exact.disposition is DispositionKind.DELETED
            or not source_records
        ):
            return exact

        prior_rows: list[sqlite3.Row] = []
        for source, source_record_id in source_records:
            row = self.database.connection.execute(
                """
                SELECT conclusion.id, conclusion.evidence_fingerprint,
                       conclusion.created_at
                FROM conclusions AS conclusion
                JOIN conclusion_evidence AS link
                    ON link.conclusion_id = conclusion.id
                JOIN source_evidence AS evidence
                    ON evidence.id = link.evidence_id
                WHERE evidence.source = ?
                  AND evidence.source_record_id = ?
                  AND conclusion.evidence_fingerprint != ?
                ORDER BY conclusion.created_at DESC, conclusion.id DESC
                LIMIT 1
                """,
                (source, source_record_id, evidence_fingerprint),
            ).fetchone()
            if row is not None:
                prior_rows.append(row)
        if not prior_rows:
            return exact
        prior_row = max(
            prior_rows,
            key=lambda row: (str(row["created_at"]), str(row["id"])),
        )

        prior_conclusion_id = str(prior_row["id"])
        event_row = self.database.connection.execute(
            """
            SELECT disposition
            FROM disposition_events
            WHERE conclusion_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (prior_conclusion_id,),
        ).fetchone()
        if event_row is None:
            return exact
        disposition = DispositionKind(str(event_row["disposition"]))
        if (
            disposition not in _SUPPRESSING_DISPOSITIONS
            and disposition is not DispositionKind.CORRECTED
        ):
            return exact
        return RecurrenceDecision(
            action=RecurrenceAction.SHOW,
            prior_conclusion_id=prior_conclusion_id,
            disposition=disposition,
            material_evidence_changed=True,
            reappearance_explanation=(
                "Material source evidence changed after the prior local "
                f"{_disposition_display_name(disposition)} action, so the "
                "conclusion is being reconsidered."
            ),
        )

    def save_briefing_presentation(
        self,
        presentation: BriefingPresentation,
    ) -> None:
        """Persist one minimized structured briefing for local presentation."""

        _require_aware(presentation.created_at)
        with self.database.transaction() as connection:
            run_row = connection.execute(
                "SELECT id FROM briefing_runs WHERE id = ?",
                (presentation.briefing_run_id,),
            ).fetchone()
            if run_row is None:
                raise ValueError("briefing run is missing")
            connection.execute(
                """
                INSERT INTO briefing_presentations(
                    briefing_run_id,
                    generation_mode,
                    chief_of_staff_note,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    presentation.briefing_run_id,
                    _required_bounded_text(
                        presentation.generation_mode,
                        field="generation mode",
                        maximum=100,
                    ),
                    _required_bounded_text(
                        presentation.chief_of_staff_note,
                        field="Chief of Staff Note",
                        maximum=4000,
                    ),
                    _serialize_datetime(presentation.created_at),
                ),
            )
            connection.execute(
                """
                DELETE FROM briefing_sections
                WHERE briefing_run_id = ?
                """,
                (presentation.briefing_run_id,),
            )
            seen_item_ids: set[str] = set()
            for section_ordinal, section in enumerate(presentation.sections):
                section_cursor = connection.execute(
                    """
                    INSERT INTO briefing_sections(
                        briefing_run_id,
                        ordinal,
                        name,
                        summary
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        presentation.briefing_run_id,
                        section_ordinal,
                        _required_bounded_text(
                            section.name,
                            field="section name",
                            maximum=100,
                        ),
                        _bounded_optional_text(
                            section.summary,
                            field="section summary",
                            maximum=2000,
                        ),
                    ),
                )
                if section_cursor.lastrowid is None:
                    raise RuntimeError("briefing section insert failed")
                section_id = int(section_cursor.lastrowid)
                for item_ordinal, item in enumerate(section.items):
                    if item.id in seen_item_ids:
                        raise ValueError("briefing item IDs must be unique")
                    seen_item_ids.add(item.id)
                    connection.execute(
                        """
                        INSERT INTO briefing_items(
                            id,
                            briefing_run_id,
                            section_id,
                            conclusion_id,
                            ordinal,
                            headline,
                            detail,
                            content_kind,
                            uncertainty,
                            explanation,
                            temporal_state,
                            starts_at,
                            ends_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item.id,
                            presentation.briefing_run_id,
                            section_id,
                            item.conclusion_id,
                            item_ordinal,
                            _required_bounded_text(
                                item.headline,
                                field="item headline",
                                maximum=1000,
                            ),
                            _required_bounded_text(
                                item.detail,
                                field="item detail",
                                maximum=4000,
                                allow_empty=True,
                            ),
                            item.content_kind,
                            _bounded_optional_text(
                                item.uncertainty,
                                field="uncertainty",
                                maximum=500,
                            ),
                            _bounded_optional_text(
                                item.explanation,
                                field="item explanation",
                                maximum=2000,
                            ),
                            item.temporal_state,
                            _serialize_optional_datetime(item.starts_at),
                            _serialize_optional_datetime(item.ends_at),
                        ),
                    )
                    for source_ordinal, source in enumerate(item.sources):
                        connection.execute(
                            """
                            INSERT INTO briefing_item_sources(
                                briefing_item_id,
                                ordinal,
                                source,
                                display_url,
                                freshness_at
                            )
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                item.id,
                                source_ordinal,
                                _required_bounded_text(
                                    source.source,
                                    field="source",
                                    maximum=100,
                                ),
                                source.display_url,
                                _serialize_optional_datetime(source.freshness_at),
                            ),
                        )

    def save_briefing_archived_facts(
        self,
        briefing_run_id: str,
        facts: tuple[BriefingArchivedFact, ...],
    ) -> None:
        """Persist minimized normalized facts for replay lineage."""

        if any(fact.briefing_run_id != briefing_run_id for fact in facts):
            raise ValueError("archived fact run identity is inconsistent")
        with self.database.transaction() as connection:
            run = connection.execute(
                "SELECT status FROM briefing_runs WHERE id = ?",
                (briefing_run_id,),
            ).fetchone()
            if run is None or str(run["status"]) != BriefingStatus.SUCCEEDED.value:
                raise ValueError("only a successful briefing may archive facts")
            existing = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM briefing_archived_facts
                WHERE briefing_run_id = ?
                """,
                (briefing_run_id,),
            ).fetchone()
            if existing is not None and int(existing["count"]) > 0:
                raise ValueError("archived briefing facts cannot be overwritten")
            for fact in facts:
                parsed = json.loads(fact.normalized_fact_json)
                if not isinstance(parsed, dict):
                    raise ValueError("archived normalized fact must be a JSON object")
                connection.execute(
                    """
                    INSERT INTO briefing_archived_facts(
                        briefing_run_id,
                        ordinal,
                        source,
                        source_record_id,
                        normalized_fact_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        fact.briefing_run_id,
                        fact.ordinal,
                        fact.source,
                        fact.source_record_id,
                        fact.normalized_fact_json,
                    ),
                )

    def get_briefing_archived_facts(
        self,
        briefing_run_id: str,
    ) -> tuple[BriefingArchivedFact, ...]:
        """Load minimized replay facts without provider payloads."""

        rows = self.database.connection.execute(
            """
            SELECT *
            FROM briefing_archived_facts
            WHERE briefing_run_id = ?
            ORDER BY ordinal
            """,
            (briefing_run_id,),
        ).fetchall()
        return tuple(
            BriefingArchivedFact(
                briefing_run_id=str(row["briefing_run_id"]),
                ordinal=int(row["ordinal"]),
                source=str(row["source"]),
                source_record_id=str(row["source_record_id"]),
                normalized_fact_json=str(row["normalized_fact_json"]),
            )
            for row in rows
        )

    def list_briefing_presentations_for_date(
        self,
        briefing_date: date,
    ) -> tuple[BriefingPresentationState, ...]:
        """Return every recorded run for one day in generation order."""

        rows = self.database.connection.execute(
            """
            SELECT run.id
            FROM briefing_runs AS run
            JOIN briefing_presentations AS presentation
                ON presentation.briefing_run_id = run.id
            WHERE run.status = 'succeeded' AND run.briefing_date = ?
            ORDER BY run.generated_at, run.completed_at, run.started_at, run.id
            """,
            (briefing_date.isoformat(),),
        ).fetchall()
        loaded = tuple(self.get_briefing_presentation(str(row["id"])) for row in rows)
        return tuple(item for item in loaded if item is not None)

    def latest_briefing_presentation(
        self,
    ) -> BriefingPresentationState | None:
        """Return the latest successfully generated local briefing."""

        row = self.database.connection.execute(
            """
            SELECT run.id
            FROM briefing_runs AS run
            JOIN briefing_presentations AS presentation
                ON presentation.briefing_run_id = run.id
            WHERE run.status = 'succeeded'
            ORDER BY run.briefing_date DESC,
                     run.completed_at DESC,
                     run.started_at DESC,
                     run.id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        return self.get_briefing_presentation(str(row["id"]))

    def get_briefing_presentation(
        self,
        briefing_run_id: str,
    ) -> BriefingPresentationState | None:
        """Load one structured local briefing and its source coverage."""

        connection = self.database.connection
        run_row = connection.execute(
            """
            SELECT run.*, presentation.generation_mode,
                   presentation.chief_of_staff_note,
                   presentation.created_at AS presentation_created_at
            FROM briefing_runs AS run
            JOIN briefing_presentations AS presentation
                ON presentation.briefing_run_id = run.id
            WHERE run.id = ?
            """,
            (briefing_run_id,),
        ).fetchone()
        if run_row is None:
            return None

        section_rows = connection.execute(
            """
            SELECT *
            FROM briefing_sections
            WHERE briefing_run_id = ?
            ORDER BY ordinal
            """,
            (briefing_run_id,),
        ).fetchall()
        sections: list[BriefingPresentationSection] = []
        for section_row in section_rows:
            item_rows = connection.execute(
                """
                SELECT *
                FROM briefing_items
                WHERE section_id = ?
                ORDER BY ordinal
                """,
                (int(section_row["id"]),),
            ).fetchall()
            items: list[BriefingPresentationItem] = []
            for item_row in item_rows:
                source_rows = connection.execute(
                    """
                    SELECT *
                    FROM briefing_item_sources
                    WHERE briefing_item_id = ?
                    ORDER BY ordinal
                    """,
                    (str(item_row["id"]),),
                ).fetchall()
                sources = tuple(
                    BriefingPresentationSource(
                        source=str(source_row["source"]),
                        display_url=(
                            None
                            if source_row["display_url"] is None
                            else str(source_row["display_url"])
                        ),
                        freshness_at=_parse_optional_datetime(
                            None
                            if source_row["freshness_at"] is None
                            else str(source_row["freshness_at"])
                        ),
                    )
                    for source_row in source_rows
                )
                items.append(
                    BriefingPresentationItem(
                        id=str(item_row["id"]),
                        conclusion_id=(
                            None
                            if item_row["conclusion_id"] is None
                            else str(item_row["conclusion_id"])
                        ),
                        headline=str(item_row["headline"]),
                        detail=str(item_row["detail"]),
                        content_kind=str(item_row["content_kind"]),
                        uncertainty=(
                            None
                            if item_row["uncertainty"] is None
                            else str(item_row["uncertainty"])
                        ),
                        explanation=(
                            None
                            if item_row["explanation"] is None
                            else str(item_row["explanation"])
                        ),
                        sources=sources,
                        temporal_state=(
                            None
                            if item_row["temporal_state"] is None
                            else str(item_row["temporal_state"])
                        ),
                        starts_at=_parse_optional_datetime(
                            None
                            if item_row["starts_at"] is None
                            else str(item_row["starts_at"])
                        ),
                        ends_at=_parse_optional_datetime(
                            None
                            if item_row["ends_at"] is None
                            else str(item_row["ends_at"])
                        ),
                    )
                )
            sections.append(
                BriefingPresentationSection(
                    name=str(section_row["name"]),
                    summary=(
                        None
                        if section_row["summary"] is None
                        else str(section_row["summary"])
                    ),
                    items=tuple(items),
                )
            )

        coverage_rows = connection.execute(
            """
            SELECT run.source, run.coverage_status, run.freshness_at,
                   run.error_category, run.approved_scope, run.record_count
            FROM connector_runs AS run
            JOIN briefing_connector_runs AS link
                ON link.connector_run_id = run.id
            WHERE link.briefing_run_id = ?
            ORDER BY run.source, run.id
            """,
            (briefing_run_id,),
        ).fetchall()
        coverage = tuple(
            BriefingCoverage(
                source=str(row["source"]),
                coverage_status=CoverageStatus(str(row["coverage_status"])),
                freshness_at=_parse_optional_datetime(
                    None if row["freshness_at"] is None else str(row["freshness_at"])
                ),
                error_category=(
                    None
                    if row["error_category"] is None
                    else str(row["error_category"])
                ),
                approved_scope=str(row["approved_scope"]),
                record_count=(
                    0 if row["record_count"] is None else int(row["record_count"])
                ),
            )
            for row in coverage_rows
        )
        run = BriefingRun(
            id=str(run_row["id"]),
            briefing_date=date.fromisoformat(str(run_row["briefing_date"])),
            timezone=str(run_row["timezone"]),
            invocation_mode=str(run_row["invocation_mode"]),
            started_at=_parse_datetime(str(run_row["started_at"])),
            completed_at=_parse_optional_datetime(
                None
                if run_row["completed_at"] is None
                else str(run_row["completed_at"])
            ),
            status=BriefingStatus(str(run_row["status"])),
            generated_at=_parse_optional_datetime(
                None
                if run_row["generated_at"] is None
                else str(run_row["generated_at"])
            ),
            as_of=_parse_optional_datetime(
                None if run_row["as_of"] is None else str(run_row["as_of"])
            ),
            historical_mode=str(run_row["historical_mode"]),
            originating_recorded_run_id=(
                None
                if run_row["originating_recorded_run_id"] is None
                else str(run_row["originating_recorded_run_id"])
            ),
            processing_versions_json=str(run_row["processing_versions_json"]),
        )
        return BriefingPresentationState(
            run=run,
            presentation=BriefingPresentation(
                briefing_run_id=briefing_run_id,
                generation_mode=str(run_row["generation_mode"]),
                chief_of_staff_note=str(run_row["chief_of_staff_note"]),
                created_at=_parse_datetime(str(run_row["presentation_created_at"])),
                sections=tuple(sections),
            ),
            coverage=coverage,
        )

    def save_scheduled_trial(self, trial: ScheduledTrial) -> None:
        """Create or update one non-secret bounded scheduling trial."""

        _require_aware(trial.created_at)
        _require_aware(trial.updated_at)
        if trial.completed_at is not None:
            _require_aware(trial.completed_at)
        if (
            not trial.eligible_weekdays
            or any(day < 0 or day > 6 for day in trial.eligible_weekdays)
            or len(set(trial.eligible_weekdays)) != len(trial.eligible_weekdays)
        ):
            raise ValueError("scheduled weekdays must be unique values from 0 to 6")
        if trial.first_eligible_date > trial.final_eligible_date:
            raise ValueError("scheduled trial date boundary is invalid")
        weekdays_json = json.dumps(
            list(trial.eligible_weekdays),
            separators=(",", ":"),
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO scheduled_trials(
                    id,
                    timezone,
                    eligible_weekdays_json,
                    trigger_hour,
                    trigger_minute,
                    cutoff_hour,
                    cutoff_minute,
                    first_eligible_date,
                    final_eligible_date,
                    maximum_eligible_dates,
                    enabled,
                    application_version,
                    created_at,
                    updated_at,
                    completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    enabled = excluded.enabled,
                    application_version = excluded.application_version,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at
                """,
                (
                    trial.id,
                    trial.timezone,
                    weekdays_json,
                    trial.trigger_hour,
                    trial.trigger_minute,
                    trial.cutoff_hour,
                    trial.cutoff_minute,
                    trial.first_eligible_date.isoformat(),
                    trial.final_eligible_date.isoformat(),
                    trial.maximum_eligible_dates,
                    int(trial.enabled),
                    trial.application_version,
                    _serialize_datetime(trial.created_at),
                    _serialize_datetime(trial.updated_at),
                    _serialize_optional_datetime(trial.completed_at),
                ),
            )
            row = connection.execute(
                """
                SELECT
                    timezone,
                    eligible_weekdays_json,
                    trigger_hour,
                    trigger_minute,
                    cutoff_hour,
                    cutoff_minute,
                    first_eligible_date,
                    final_eligible_date,
                    maximum_eligible_dates
                FROM scheduled_trials
                WHERE id = ?
                """,
                (trial.id,),
            ).fetchone()
            if row is None or (
                str(row["timezone"]) != trial.timezone
                or str(row["eligible_weekdays_json"]) != weekdays_json
                or int(row["trigger_hour"]) != trial.trigger_hour
                or int(row["trigger_minute"]) != trial.trigger_minute
                or int(row["cutoff_hour"]) != trial.cutoff_hour
                or int(row["cutoff_minute"]) != trial.cutoff_minute
                or str(row["first_eligible_date"])
                != trial.first_eligible_date.isoformat()
                or str(row["final_eligible_date"])
                != trial.final_eligible_date.isoformat()
                or int(row["maximum_eligible_dates"]) != trial.maximum_eligible_dates
            ):
                raise ValueError("an existing scheduled trial has different policy")

    def get_scheduled_trial(self, trial_id: str) -> ScheduledTrial | None:
        """Return one non-content trial configuration."""

        row = self.database.connection.execute(
            "SELECT * FROM scheduled_trials WHERE id = ?",
            (trial_id,),
        ).fetchone()
        if row is None:
            return None
        weekdays = json.loads(str(row["eligible_weekdays_json"]))
        if not isinstance(weekdays, list) or any(
            not isinstance(value, int) or isinstance(value, bool) for value in weekdays
        ):
            raise ValueError("stored scheduled weekdays are invalid")
        return ScheduledTrial(
            id=str(row["id"]),
            timezone=str(row["timezone"]),
            eligible_weekdays=tuple(weekdays),
            trigger_hour=int(row["trigger_hour"]),
            trigger_minute=int(row["trigger_minute"]),
            cutoff_hour=int(row["cutoff_hour"]),
            cutoff_minute=int(row["cutoff_minute"]),
            first_eligible_date=date.fromisoformat(str(row["first_eligible_date"])),
            final_eligible_date=date.fromisoformat(str(row["final_eligible_date"])),
            maximum_eligible_dates=int(row["maximum_eligible_dates"]),
            enabled=bool(row["enabled"]),
            application_version=str(row["application_version"]),
            created_at=_parse_datetime(str(row["created_at"])),
            updated_at=_parse_datetime(str(row["updated_at"])),
            completed_at=_parse_optional_datetime(
                None if row["completed_at"] is None else str(row["completed_at"])
            ),
        )

    def delete_empty_scheduled_trial(self, trial_id: str) -> bool:
        """Roll back an unstarted trial when service installation fails."""

        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                DELETE FROM scheduled_trials
                WHERE id = ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM scheduled_occurrences
                      WHERE trial_id = scheduled_trials.id
                  )
                """,
                (trial_id,),
            )
        return cursor.rowcount == 1

    def save_scheduled_occurrence(
        self,
        occurrence: ScheduledOccurrence,
    ) -> None:
        """Upsert one bounded non-content status row for a scheduled date."""

        _require_aware(occurrence.scheduled_for)
        _require_aware(occurrence.actual_start_at)
        _require_aware(occurrence.updated_at)
        for field_name, value, maximum in (
            ("source health", occurrence.source_health_json, 4000),
            ("aggregate counts", occurrence.aggregate_counts_json, 1000),
        ):
            parsed = json.loads(value)
            if not isinstance(parsed, dict) or len(value) > maximum:
                raise ValueError(
                    f"scheduled {field_name} must be a bounded JSON object"
                )
        with self.database.transaction() as connection:
            existing = connection.execute(
                """
                SELECT *
                FROM scheduled_occurrences
                WHERE trial_id = ? AND occurrence_date = ?
                """,
                (
                    occurrence.trial_id,
                    occurrence.occurrence_date.isoformat(),
                ),
            ).fetchone()
            if existing is not None:
                existing_occurrence = _scheduled_occurrence_from_row(existing)
                if existing_occurrence == occurrence:
                    return
                if str(existing["idempotency_key"]) != occurrence.idempotency_key:
                    raise ValueError(
                        "scheduled occurrence idempotency key is immutable"
                    )
                if (
                    ScheduledOutcome(str(existing["outcome"]))
                    is not ScheduledOutcome.BEFORE_WINDOW
                ):
                    raise ValueError("terminal scheduled occurrence is immutable")
            connection.execute(
                """
                INSERT INTO scheduled_occurrences(
                    trial_id,
                    occurrence_date,
                    idempotency_key,
                    scheduled_for,
                    actual_start_at,
                    eligibility_decision,
                    outcome,
                    briefing_run_id,
                    source_health_json,
                    aggregate_counts_json,
                    duration_ms,
                    trial_ordinal,
                    application_version,
                    notification_result,
                    diagnostic_category,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trial_id, occurrence_date) DO UPDATE SET
                    actual_start_at = excluded.actual_start_at,
                    eligibility_decision = excluded.eligibility_decision,
                    outcome = excluded.outcome,
                    briefing_run_id = excluded.briefing_run_id,
                    source_health_json = excluded.source_health_json,
                    aggregate_counts_json = excluded.aggregate_counts_json,
                    duration_ms = excluded.duration_ms,
                    trial_ordinal = excluded.trial_ordinal,
                    application_version = excluded.application_version,
                    notification_result = excluded.notification_result,
                    diagnostic_category = excluded.diagnostic_category,
                    updated_at = excluded.updated_at
                """,
                (
                    occurrence.trial_id,
                    occurrence.occurrence_date.isoformat(),
                    occurrence.idempotency_key,
                    _serialize_datetime(occurrence.scheduled_for),
                    _serialize_datetime(occurrence.actual_start_at),
                    occurrence.eligibility_decision,
                    occurrence.outcome.value,
                    occurrence.briefing_run_id,
                    occurrence.source_health_json,
                    occurrence.aggregate_counts_json,
                    occurrence.duration_ms,
                    occurrence.trial_ordinal,
                    occurrence.application_version,
                    occurrence.notification_result,
                    occurrence.diagnostic_category,
                    _serialize_datetime(occurrence.updated_at),
                ),
            )

    def get_scheduled_occurrence(
        self,
        trial_id: str,
        occurrence_date: date,
    ) -> ScheduledOccurrence | None:
        """Return one non-content scheduled occurrence."""

        row = self.database.connection.execute(
            """
            SELECT *
            FROM scheduled_occurrences
            WHERE trial_id = ? AND occurrence_date = ?
            """,
            (trial_id, occurrence_date.isoformat()),
        ).fetchone()
        return None if row is None else _scheduled_occurrence_from_row(row)

    def list_scheduled_occurrences(
        self,
        trial_id: str,
    ) -> tuple[ScheduledOccurrence, ...]:
        """Return bounded trial occurrences in local-date order."""

        rows = self.database.connection.execute(
            """
            SELECT *
            FROM scheduled_occurrences
            WHERE trial_id = ?
            ORDER BY occurrence_date
            """,
            (trial_id,),
        ).fetchall()
        return tuple(_scheduled_occurrence_from_row(row) for row in rows)

    def delete_local_conclusion(
        self,
        *,
        conclusion_id: str,
        expected_version: int,
        idempotency_key: str,
        deleted_at: datetime,
    ) -> bool:
        """Delete local conclusion payloads while retaining a minimal tombstone."""

        _require_aware(deleted_at)
        normalized_key = idempotency_key.strip()
        if len(normalized_key) < 16 or len(normalized_key) > 200:
            raise InvalidDispositionError("idempotency key is invalid")
        with self.database.transaction() as connection:
            prior_tombstone = connection.execute(
                """
                SELECT evidence_fingerprint
                FROM conclusion_tombstones
                WHERE idempotency_key = ?
                """,
                (normalized_key,),
            ).fetchone()
            if prior_tombstone is not None:
                return False

            row = connection.execute(
                """
                SELECT
                    conclusion.evidence_fingerprint,
                    conclusion.processing_version,
                    state.version
                FROM conclusions AS conclusion
                JOIN conclusion_current_state AS state
                    ON state.conclusion_id = conclusion.id
                WHERE conclusion.id = ?
                """,
                (conclusion_id,),
            ).fetchone()
            if row is None:
                raise KeyError("conclusion is missing")
            if int(row["version"]) != expected_version:
                raise StaleConclusionVersionError(
                    "the local conclusion changed; reload before trying again"
                )
            evidence_rows = connection.execute(
                """
                SELECT link.evidence_id, evidence.source,
                       evidence.source_record_id
                FROM conclusion_evidence AS link
                JOIN source_evidence AS evidence
                    ON evidence.id = link.evidence_id
                WHERE conclusion_id = ?
                """,
                (conclusion_id,),
            ).fetchall()
            for evidence_row in evidence_rows:
                connection.execute(
                    """
                    DELETE FROM briefing_archived_facts
                    WHERE source = ? AND source_record_id = ?
                    """,
                    (
                        str(evidence_row["source"]),
                        str(evidence_row["source_record_id"]),
                    ),
                )
            presentation_section_rows = connection.execute(
                """
                SELECT DISTINCT section_id
                FROM briefing_items
                WHERE conclusion_id = ?
                """,
                (conclusion_id,),
            ).fetchall()
            connection.execute(
                """
                INSERT INTO conclusion_tombstones(
                    evidence_fingerprint,
                    processing_version,
                    idempotency_key,
                    deleted_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(evidence_fingerprint) DO UPDATE SET
                    processing_version = excluded.processing_version,
                    idempotency_key = excluded.idempotency_key,
                    deleted_at = excluded.deleted_at
                """,
                (
                    str(row["evidence_fingerprint"]),
                    str(row["processing_version"]),
                    normalized_key,
                    _serialize_datetime(deleted_at),
                ),
            )
            delete_cursor = connection.execute(
                "DELETE FROM conclusions WHERE id = ?",
                (conclusion_id,),
            )
            if delete_cursor.rowcount != 1:
                raise RuntimeError("local conclusion deletion failed")
            for section_row in presentation_section_rows:
                section_id = int(section_row["section_id"])
                connection.execute(
                    """
                    UPDATE briefing_sections
                    SET summary = NULL
                    WHERE id = ?
                    """,
                    (section_id,),
                )
                connection.execute(
                    """
                    DELETE FROM briefing_sections
                    WHERE id = ?
                      AND NOT EXISTS (
                          SELECT 1
                          FROM briefing_items
                          WHERE section_id = ?
                      )
                    """,
                    (section_id, section_id),
                )
            for evidence_row in evidence_rows:
                evidence_id = str(evidence_row["evidence_id"])
                remaining_link = connection.execute(
                    """
                    SELECT 1
                    FROM conclusion_evidence
                    WHERE evidence_id = ?
                    LIMIT 1
                    """,
                    (evidence_id,),
                ).fetchone()
                if remaining_link is None:
                    connection.execute(
                        "DELETE FROM source_evidence WHERE id = ?",
                        (evidence_id,),
                    )
        return True

    def inspect_state(self) -> StateInspection:
        """Return non-content counts and applied migration versions."""

        connection = self.database.connection
        versions = tuple(
            int(row["version"])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        )
        return StateInspection(
            schema_versions=versions,
            connector_runs=_table_count(connection, "connector_runs"),
            briefing_runs=_table_count(connection, "briefing_runs"),
            source_evidence=_table_count(connection, "source_evidence"),
            conclusions=_table_count(connection, "conclusions"),
            disposition_events=_table_count(connection, "disposition_events"),
            oauth_clients=_table_count(connection, "oauth_clients"),
            connector_authorizations=_table_count(
                connection,
                "connector_authorizations",
            ),
            connector_resources=_table_count(connection, "connector_resources"),
            normalized_source_tasks=_table_count(
                connection,
                "normalized_source_tasks",
            ),
            normalized_source_task_labels=_table_count(
                connection,
                "normalized_source_task_labels",
            ),
            normalized_jira_issues=_table_count(
                connection,
                "normalized_jira_issues",
            ),
            normalized_jira_issue_labels=_table_count(
                connection,
                "normalized_jira_issue_labels",
            ),
            normalized_jira_issue_links=_table_count(
                connection,
                "normalized_jira_issue_links",
            ),
            normalized_gmail_messages=_table_count(
                connection,
                "normalized_gmail_messages",
            ),
            connector_instances=_table_count(connection, "connector_instances"),
            inference_audits=_table_count(connection, "inference_audits"),
            conclusion_current_states=_table_count(
                connection,
                "conclusion_current_state",
            ),
            conclusion_tombstones=_table_count(
                connection,
                "conclusion_tombstones",
            ),
            briefing_presentations=_table_count(
                connection,
                "briefing_presentations",
            ),
            briefing_items=_table_count(connection, "briefing_items"),
            briefing_archived_facts=_table_count(
                connection,
                "briefing_archived_facts",
            ),
            scheduled_trials=_table_count(connection, "scheduled_trials"),
            scheduled_occurrences=_table_count(
                connection,
                "scheduled_occurrences",
            ),
        )

    def delete_disposition_history(self, conclusion_id: str) -> int:
        """Delete correction history while preserving the conclusion."""

        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM disposition_events WHERE conclusion_id = ?",
                (conclusion_id,),
            )
        return cursor.rowcount

    def delete_conclusion(self, conclusion_id: str) -> bool:
        """Delete a conclusion and all dependent disposition history."""

        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM conclusions WHERE id = ?",
                (conclusion_id,),
            )
        return cursor.rowcount > 0

    def delete_briefing_run(self, briefing_run_id: str) -> bool:
        """Delete a briefing run without modifying any external source."""

        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM briefing_runs WHERE id = ?",
                (briefing_run_id,),
            )
        return cursor.rowcount > 0

    def delete_source_evidence(self, evidence_id: str) -> bool:
        """Delete evidence and conclusions that depend on it."""

        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM source_evidence WHERE id = ?",
                (evidence_id,),
            )
        return cursor.rowcount > 0

    def prune_run_metadata(self, completed_before: datetime) -> tuple[int, int]:
        """Enforce bounded run retention without deleting correction evidence."""

        cutoff = _serialize_datetime(completed_before)
        with self.database.transaction() as connection:
            connector_cursor = connection.execute(
                """
                DELETE FROM connector_runs
                WHERE completed_at IS NOT NULL AND completed_at < ?
                """,
                (cutoff,),
            )
            briefing_cursor = connection.execute(
                """
                DELETE FROM briefing_runs
                WHERE completed_at IS NOT NULL AND completed_at < ?
                """,
                (cutoff,),
            )
        return connector_cursor.rowcount, briefing_cursor.rowcount

    def prune_inference_audits(self, created_before: datetime) -> int:
        """Delete non-content inference audit metadata before a cutoff."""

        cutoff = _serialize_datetime(created_before)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM inference_audits WHERE created_at < ?",
                (cutoff,),
            )
        return cursor.rowcount

    def reset(self) -> StateInspection:
        """Delete all application state while preserving schema history."""

        with self.database.transaction() as connection:
            connection.execute("DELETE FROM scheduled_occurrences")
            connection.execute("DELETE FROM scheduled_trials")
            connection.execute("DELETE FROM inference_audits")
            connection.execute("DELETE FROM conclusion_tombstones")
            connection.execute("DELETE FROM disposition_events")
            connection.execute("DELETE FROM conclusion_evidence")
            connection.execute("DELETE FROM conclusions")
            connection.execute("DELETE FROM source_evidence")
            connection.execute("DELETE FROM briefing_connector_runs")
            connection.execute("DELETE FROM connector_runs")
            connection.execute("DELETE FROM briefing_runs")
        return self.inspect_state()


def _serialize_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _serialize_optional_datetime(value: datetime | None) -> str | None:
    return None if value is None else _serialize_datetime(value)


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _parse_optional_datetime(value: str | None) -> datetime | None:
    return None if value is None else _parse_datetime(value)


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")


def _bounded_optional_text(
    value: str | None,
    *,
    field: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise InvalidDispositionError(f"{field} exceeds its size limit")
    return normalized


def _required_bounded_text(
    value: str,
    *,
    field: str,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds its size limit")
    return normalized


def _connector_instance_values(
    metadata: ConnectorInstanceMetadata,
) -> tuple[object, ...]:
    return (
        metadata.id,
        metadata.provider,
        metadata.alias,
        metadata.domain_classification.value,
        metadata.approved_resource_boundary,
        metadata.approved_scopes,
        metadata.retrieval_configuration,
        (
            None
            if metadata.last_coverage_status is None
            else metadata.last_coverage_status.value
        ),
        _serialize_optional_datetime(metadata.last_freshness_at),
        int(metadata.enabled),
        metadata.retention_policy_reference,
        _serialize_datetime(metadata.created_at),
        _serialize_datetime(metadata.updated_at),
    )


def _connector_instance_from_row(row: sqlite3.Row) -> ConnectorInstanceMetadata:
    return ConnectorInstanceMetadata(
        id=str(row["id"]),
        provider=str(row["provider"]),
        alias=str(row["alias"]),
        domain_classification=ConnectorDomain(str(row["domain_classification"])),
        approved_resource_boundary=str(row["approved_resource_boundary"]),
        approved_scopes=str(row["approved_scopes"]),
        retrieval_configuration=str(row["retrieval_configuration"]),
        last_coverage_status=(
            None
            if row["last_coverage_status"] is None
            else CoverageStatus(str(row["last_coverage_status"]))
        ),
        last_freshness_at=_parse_optional_datetime(
            None if row["last_freshness_at"] is None else str(row["last_freshness_at"])
        ),
        enabled=bool(row["enabled"]),
        retention_policy_reference=str(row["retention_policy_reference"]),
        created_at=_parse_datetime(str(row["created_at"])),
        updated_at=_parse_datetime(str(row["updated_at"])),
    )


def _source_evidence_from_row(row: sqlite3.Row) -> SourceEvidence:
    return SourceEvidence(
        id=str(row["id"]),
        connector_run_id=(
            None if row["connector_run_id"] is None else str(row["connector_run_id"])
        ),
        source=str(row["source"]),
        source_record_id=str(row["source_record_id"]),
        display_url=None if row["display_url"] is None else str(row["display_url"]),
        excerpt=None if row["excerpt"] is None else str(row["excerpt"]),
        evidence_fingerprint=str(row["evidence_fingerprint"]),
        retrieved_at=_parse_datetime(str(row["retrieved_at"])),
        freshness_at=_parse_optional_datetime(
            None if row["freshness_at"] is None else str(row["freshness_at"])
        ),
        connector_instance_id=(
            None
            if row["connector_instance_id"] is None
            else str(row["connector_instance_id"])
        ),
    )


def _conclusion_from_row(
    row: sqlite3.Row,
    evidence_ids: tuple[str, ...],
) -> Conclusion:
    confidence_value = row["confidence"]
    return Conclusion(
        id=str(row["id"]),
        kind=ConclusionKind(str(row["kind"])),
        classification=Classification(str(row["classification"])),
        statement=str(row["statement"]),
        explanation=str(row["explanation"]),
        confidence=None if confidence_value is None else float(confidence_value),
        evidence_fingerprint=str(row["evidence_fingerprint"]),
        processing_version=str(row["processing_version"]),
        created_at=_parse_datetime(str(row["created_at"])),
        evidence_ids=evidence_ids,
    )


def _disposition_from_row(row: sqlite3.Row) -> DispositionEvent:
    return DispositionEvent(
        id=str(row["id"]),
        conclusion_id=str(row["conclusion_id"]),
        briefing_run_id=(
            None
            if row["originating_briefing_id"] is None
            else str(row["originating_briefing_id"])
        ),
        disposition=DispositionKind(str(row["disposition"])),
        replacement_text=(
            None if row["replacement_text"] is None else str(row["replacement_text"])
        ),
        note=(None if row["explanation"] is None else str(row["explanation"])),
        created_at=_parse_datetime(str(row["created_at"])),
        previous_state=str(row["previous_state"]),
        new_state=str(row["new_state"]),
        delegate_description=(
            None
            if row["delegate_description"] is None
            else str(row["delegate_description"])
        ),
        follow_up_at=_parse_optional_datetime(
            None if row["follow_up_at"] is None else str(row["follow_up_at"])
        ),
        rescheduled_for=_parse_optional_datetime(
            None if row["rescheduled_for"] is None else str(row["rescheduled_for"])
        ),
        evidence_fingerprint=str(row["evidence_fingerprint"]),
        processing_version=str(row["processing_version"]),
        expected_version=int(row["expected_version"]),
        resulting_version=int(row["resulting_version"]),
        idempotency_key=str(row["idempotency_key"]),
    )


def _scheduled_occurrence_from_row(row: sqlite3.Row) -> ScheduledOccurrence:
    return ScheduledOccurrence(
        trial_id=str(row["trial_id"]),
        occurrence_date=date.fromisoformat(str(row["occurrence_date"])),
        idempotency_key=str(row["idempotency_key"]),
        scheduled_for=_parse_datetime(str(row["scheduled_for"])),
        actual_start_at=_parse_datetime(str(row["actual_start_at"])),
        eligibility_decision=str(row["eligibility_decision"]),
        outcome=ScheduledOutcome(str(row["outcome"])),
        trial_ordinal=(
            None if row["trial_ordinal"] is None else int(row["trial_ordinal"])
        ),
        application_version=str(row["application_version"]),
        updated_at=_parse_datetime(str(row["updated_at"])),
        briefing_run_id=(
            None if row["briefing_run_id"] is None else str(row["briefing_run_id"])
        ),
        source_health_json=str(row["source_health_json"]),
        aggregate_counts_json=str(row["aggregate_counts_json"]),
        duration_ms=(None if row["duration_ms"] is None else int(row["duration_ms"])),
        notification_result=(
            None
            if row["notification_result"] is None
            else str(row["notification_result"])
        ),
        diagnostic_category=(
            None
            if row["diagnostic_category"] is None
            else str(row["diagnostic_category"])
        ),
    )


def _conclusion_projection_from_row(row: sqlite3.Row) -> ConclusionProjection:
    return ConclusionProjection(
        conclusion_id=str(row["conclusion_id"]),
        current_state=str(row["current_state"]),
        display_statement=str(row["display_statement"]),
        delegate_description=(
            None
            if row["delegate_description"] is None
            else str(row["delegate_description"])
        ),
        follow_up_at=_parse_optional_datetime(
            None if row["follow_up_at"] is None else str(row["follow_up_at"])
        ),
        rescheduled_for=_parse_optional_datetime(
            None if row["rescheduled_for"] is None else str(row["rescheduled_for"])
        ),
        version=int(row["version"]),
        last_event_id=(
            None if row["last_event_id"] is None else str(row["last_event_id"])
        ),
        updated_at=_parse_datetime(str(row["updated_at"])),
    )


def _disposition_display_name(disposition: DispositionKind) -> str:
    return disposition.value.replace("_", " ")


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    queries = {
        "briefing_runs": "SELECT COUNT(*) AS count FROM briefing_runs",
        "conclusions": "SELECT COUNT(*) AS count FROM conclusions",
        "connector_runs": "SELECT COUNT(*) AS count FROM connector_runs",
        "disposition_events": "SELECT COUNT(*) AS count FROM disposition_events",
        "oauth_clients": "SELECT COUNT(*) AS count FROM oauth_clients",
        "connector_authorizations": (
            "SELECT COUNT(*) AS count FROM connector_authorizations"
        ),
        "connector_resources": "SELECT COUNT(*) AS count FROM connector_resources",
        "connector_instances": "SELECT COUNT(*) AS count FROM connector_instances",
        "source_evidence": "SELECT COUNT(*) AS count FROM source_evidence",
        "normalized_source_tasks": (
            "SELECT COUNT(*) AS count FROM normalized_source_tasks"
        ),
        "normalized_source_task_labels": (
            "SELECT COUNT(*) AS count FROM normalized_source_task_labels"
        ),
        "normalized_jira_issues": (
            "SELECT COUNT(*) AS count FROM normalized_jira_issues"
        ),
        "normalized_jira_issue_labels": (
            "SELECT COUNT(*) AS count FROM normalized_jira_issue_labels"
        ),
        "normalized_jira_issue_links": (
            "SELECT COUNT(*) AS count FROM normalized_jira_issue_links"
        ),
        "normalized_gmail_messages": (
            "SELECT COUNT(*) AS count FROM normalized_gmail_messages"
        ),
        "inference_audits": "SELECT COUNT(*) AS count FROM inference_audits",
        "conclusion_current_state": (
            "SELECT COUNT(*) AS count FROM conclusion_current_state"
        ),
        "conclusion_tombstones": (
            "SELECT COUNT(*) AS count FROM conclusion_tombstones"
        ),
        "briefing_presentations": (
            "SELECT COUNT(*) AS count FROM briefing_presentations"
        ),
        "briefing_items": "SELECT COUNT(*) AS count FROM briefing_items",
        "briefing_archived_facts": (
            "SELECT COUNT(*) AS count FROM briefing_archived_facts"
        ),
        "scheduled_trials": "SELECT COUNT(*) AS count FROM scheduled_trials",
        "scheduled_occurrences": (
            "SELECT COUNT(*) AS count FROM scheduled_occurrences"
        ),
    }
    query = queries.get(table)
    if query is None:
        raise ValueError("unsupported table")
    row = connection.execute(query).fetchone()
    if row is None:
        raise RuntimeError("count query returned no result")
    return int(row["count"])
