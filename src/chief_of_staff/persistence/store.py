"""Application-owned repositories for inspectable local state."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from chief_of_staff.domain.models import (
    BriefingRun,
    Classification,
    Conclusion,
    ConclusionKind,
    ConclusionState,
    ConnectorRun,
    DispositionEvent,
    DispositionKind,
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
                    error_category
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )

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
        "source_evidence": "SELECT COUNT(*) AS count FROM source_evidence",
    }
    query = queries.get(table)
    if query is None:
        raise ValueError("unsupported table")
    row = connection.execute(query).fetchone()
    if row is None:
        raise RuntimeError("count query returned no result")
    return int(row["count"])
