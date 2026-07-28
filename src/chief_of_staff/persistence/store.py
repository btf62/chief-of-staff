"""Application-owned repositories for inspectable local state."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from chief_of_staff.domain.models import (
    AuthorizationStatus,
    BriefingRun,
    Classification,
    Conclusion,
    ConclusionKind,
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
    NormalizedJiraIssue,
    NormalizedSourceTask,
    OAuthClientMetadata,
    RecurrenceAction,
    RecurrenceDecision,
    SourceEvidence,
    StateInspection,
)
from chief_of_staff.persistence.database import Database

_SUPPRESSING_DISPOSITIONS = frozenset(
    {
        DispositionKind.DISMISSED,
        DispositionKind.DELEGATED,
        DispositionKind.RESCHEDULED,
        DispositionKind.COMPLETED,
        DispositionKind.INTENTIONALLY_ABANDONED,
    }
)


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
                    connector_instance_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.briefing_date.isoformat(),
                    run.timezone,
                    run.invocation_mode,
                    _serialize_datetime(run.started_at),
                    _serialize_optional_datetime(run.completed_at),
                    run.status.value,
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

    def append_disposition(self, event: DispositionEvent) -> None:
        """Append a user-controlled disposition without replacing history."""

        if (
            event.disposition is DispositionKind.CORRECTED
            and not event.replacement_text
        ):
            raise ValueError("a corrected disposition requires replacement text")

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO disposition_events(
                    id,
                    conclusion_id,
                    briefing_run_id,
                    disposition,
                    replacement_text,
                    note,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.conclusion_id,
                    event.briefing_run_id,
                    event.disposition.value,
                    event.replacement_text,
                    event.note,
                    _serialize_datetime(event.created_at),
                ),
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
        return ConclusionState(
            conclusion=conclusion,
            evidence=evidence,
            history=history,
        )

    def recurrence_decision(self, evidence_fingerprint: str) -> RecurrenceDecision:
        """Project prior local state for materially unchanged evidence."""

        conclusion_row = self.database.connection.execute(
            """
            SELECT id
            FROM conclusions
            WHERE evidence_fingerprint = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (evidence_fingerprint,),
        ).fetchone()
        if conclusion_row is None:
            return RecurrenceDecision(action=RecurrenceAction.SHOW)

        conclusion_id = str(conclusion_row["id"])
        event_row = self.database.connection.execute(
            """
            SELECT disposition, replacement_text
            FROM disposition_events
            WHERE conclusion_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (conclusion_id,),
        ).fetchone()
        if event_row is None:
            return RecurrenceDecision(
                action=RecurrenceAction.SHOW,
                prior_conclusion_id=conclusion_id,
            )

        disposition = DispositionKind(str(event_row["disposition"]))
        if disposition is DispositionKind.CORRECTED:
            return RecurrenceDecision(
                action=RecurrenceAction.REPLACE,
                prior_conclusion_id=conclusion_id,
                replacement_text=str(event_row["replacement_text"]),
                disposition=disposition,
            )
        if disposition in _SUPPRESSING_DISPOSITIONS:
            return RecurrenceDecision(
                action=RecurrenceAction.SUPPRESS,
                prior_conclusion_id=conclusion_id,
                disposition=disposition,
            )
        return RecurrenceDecision(
            action=RecurrenceAction.SHOW,
            prior_conclusion_id=conclusion_id,
            disposition=disposition,
        )

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
            connector_instances=_table_count(connection, "connector_instances"),
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

    def reset(self) -> StateInspection:
        """Delete all application state while preserving schema history."""

        with self.database.transaction() as connection:
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
            None if row["briefing_run_id"] is None else str(row["briefing_run_id"])
        ),
        disposition=DispositionKind(str(row["disposition"])),
        replacement_text=(
            None if row["replacement_text"] is None else str(row["replacement_text"])
        ),
        note=None if row["note"] is None else str(row["note"]),
        created_at=_parse_datetime(str(row["created_at"])),
    )


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
    }
    query = queries.get(table)
    if query is None:
        raise ValueError("unsupported table")
    row = connection.execute(query).fetchone()
    if row is None:
        raise RuntimeError("count query returned no result")
    return int(row["count"])
