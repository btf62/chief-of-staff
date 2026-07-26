"""Application-owned repositories for inspectable local state."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from chief_of_staff.domain.models import (
    AuthorizationStatus,
    BriefingRun,
    Classification,
    Conclusion,
    ConclusionKind,
    ConclusionState,
    ConnectorAuthorizationMetadata,
    ConnectorRun,
    CredentialHealth,
    DispositionEvent,
    DispositionKind,
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


class StateStore:
    """Transactional persistence for runs, evidence, and correction history."""

    def __init__(self, database: Database) -> None:
        self.database = database

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
                    page_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )

    def save_oauth_client(self, metadata: OAuthClientMetadata) -> None:
        """Persist non-secret OAuth client metadata and Keychain references."""

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO oauth_clients(
                    connector,
                    oauth_project_id,
                    oauth_client_id,
                    credential_service,
                    client_secret_account,
                    configured_at,
                    application_owner
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connector) DO UPDATE SET
                    oauth_project_id = excluded.oauth_project_id,
                    oauth_client_id = excluded.oauth_client_id,
                    credential_service = excluded.credential_service,
                    client_secret_account = excluded.client_secret_account,
                    configured_at = excluded.configured_at,
                    application_owner = excluded.application_owner
                """,
                (
                    metadata.connector,
                    metadata.oauth_project_id,
                    metadata.oauth_client_id,
                    metadata.credential_service,
                    metadata.client_secret_account,
                    _serialize_datetime(metadata.configured_at),
                    metadata.application_owner,
                ),
            )

    def get_oauth_client(self, connector: str) -> OAuthClientMetadata | None:
        """Return non-secret OAuth client metadata."""

        row = self.database.connection.execute(
            "SELECT * FROM oauth_clients WHERE connector = ?",
            (connector,),
        ).fetchone()
        if row is None:
            return None
        return OAuthClientMetadata(
            connector=str(row["connector"]),
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
        )

    def save_connector_authorization(
        self,
        metadata: ConnectorAuthorizationMetadata,
    ) -> None:
        """Persist non-secret authorization health and Keychain references."""

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO connector_authorizations(
                    connector,
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connector) DO UPDATE SET
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

    def get_connector_authorization(
        self,
        connector: str,
    ) -> ConnectorAuthorizationMetadata | None:
        """Return inspectable authorization metadata without secret values."""

        row = self.database.connection.execute(
            "SELECT * FROM connector_authorizations WHERE connector = ?",
            (connector,),
        ).fetchone()
        if row is None:
            return None
        return ConnectorAuthorizationMetadata(
            connector=str(row["connector"]),
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
        )

    def mark_connector_authorization_used(
        self,
        connector: str,
        *,
        used_at: datetime,
    ) -> None:
        """Record successful use without changing or reading a credential."""

        timestamp = _serialize_datetime(used_at)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE connector_authorizations
                SET last_used_at = ?, updated_at = ?
                WHERE connector = ?
                """,
                (timestamp, timestamp, connector),
            )
            if cursor.rowcount != 1:
                raise ValueError("connector authorization metadata is missing")

    def set_connector_authorization_health(
        self,
        connector: str,
        *,
        status: AuthorizationStatus,
        health: CredentialHealth,
        updated_at: datetime,
    ) -> None:
        """Update non-secret health after expiry or provider rejection."""

        timestamp = _serialize_datetime(updated_at)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE connector_authorizations
                SET authorization_status = ?,
                    credential_health = ?,
                    updated_at = ?
                WHERE connector = ?
                """,
                (status.value, health.value, timestamp, connector),
            )
            if cursor.rowcount != 1:
                raise ValueError("connector authorization metadata is missing")

    def delete_connector_configuration(self, connector: str) -> None:
        """Delete non-secret metadata after credentials are removed."""

        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM oauth_clients WHERE connector = ?",
                (connector,),
            )

    def delete_connector_authorization(self, connector: str) -> bool:
        """Delete only non-secret grant metadata after token cleanup."""

        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM connector_authorizations WHERE connector = ?",
                (connector,),
            )
        return cursor.rowcount > 0

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
                    source,
                    source_record_id,
                    display_url,
                    excerpt,
                    evidence_fingerprint,
                    retrieved_at,
                    freshness_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.id,
                    evidence.connector_run_id,
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

    def prune_unselected_source_tasks(
        self,
        *,
        source: str,
        retained_source_record_ids: frozenset[str],
    ) -> int:
        """Delete stale selected-task snapshots unless correction state needs them."""

        if not source.strip():
            raise ValueError("source must not be empty")
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT evidence.id, evidence.source_record_id
                FROM source_evidence AS evidence
                JOIN normalized_source_tasks AS task
                    ON task.evidence_id = evidence.id
                WHERE evidence.source = ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM conclusion_evidence AS link
                      WHERE link.evidence_id = evidence.id
                  )
                """,
                (source,),
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
            normalized_source_tasks=_table_count(
                connection,
                "normalized_source_tasks",
            ),
            normalized_source_task_labels=_table_count(
                connection,
                "normalized_source_task_labels",
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
        "source_evidence": "SELECT COUNT(*) AS count FROM source_evidence",
        "normalized_source_tasks": (
            "SELECT COUNT(*) AS count FROM normalized_source_tasks"
        ),
        "normalized_source_task_labels": (
            "SELECT COUNT(*) AS count FROM normalized_source_task_labels"
        ),
    }
    query = queries.get(table)
    if query is None:
        raise ValueError("unsupported table")
    row = connection.execute(query).fetchone()
    if row is None:
        raise RuntimeError("count query returned no result")
    return int(row["count"])
