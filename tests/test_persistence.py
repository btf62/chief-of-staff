"""Synthetic tests for domain persistence and local-state lifecycle."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from chief_of_staff.domain import (
    BriefingRun,
    BriefingStatus,
    Classification,
    Conclusion,
    ConclusionKind,
    ConnectorRun,
    ConnectorStatus,
    CoverageStatus,
    DispositionEvent,
    DispositionKind,
    NormalizedSourceTask,
    RecurrenceAction,
    SourceEvidence,
)
from chief_of_staff.persistence import (
    Database,
    Migration,
    MigrationError,
    StateStore,
    apply_migrations,
    load_migrations,
)

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def _connector_run(
    *,
    run_id: str = "connector-run-1",
    completed_at: datetime | None = NOW,
) -> ConnectorRun:
    return ConnectorRun(
        id=run_id,
        source="synthetic_tasks",
        approved_scope="repository-owned synthetic fixtures",
        started_at=NOW - timedelta(minutes=1),
        completed_at=completed_at,
        status=ConnectorStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        retrieval_window_start=NOW - timedelta(days=1),
        retrieval_window_end=NOW,
        freshness_at=NOW,
    )


def _briefing_run(*, run_id: str = "briefing-run-1") -> BriefingRun:
    return BriefingRun(
        id=run_id,
        briefing_date=date(2026, 7, 25),
        timezone="America/New_York",
        invocation_mode="test",
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        status=BriefingStatus.SUCCEEDED,
    )


def _evidence(
    *,
    evidence_id: str = "evidence-1",
    connector_run_id: str | None = "connector-run-1",
    fingerprint: str = "fingerprint-v1",
    source_record_id: str = "task-1",
) -> SourceEvidence:
    return SourceEvidence(
        id=evidence_id,
        connector_run_id=connector_run_id,
        source="synthetic_tasks",
        source_record_id=source_record_id,
        display_url="https://example.invalid/tasks/1",
        excerpt="Prepare the synthetic planning agenda.",
        evidence_fingerprint=fingerprint,
        retrieved_at=NOW,
        freshness_at=NOW,
    )


def _conclusion(
    *,
    conclusion_id: str = "conclusion-1",
    evidence_id: str = "evidence-1",
    fingerprint: str = "fingerprint-v1",
) -> Conclusion:
    return Conclusion(
        id=conclusion_id,
        kind=ConclusionKind.COMMITMENT,
        classification=Classification.EXPLICIT,
        statement="Prepare the planning agenda.",
        explanation="The synthetic task has an explicit due date.",
        confidence=1.0,
        evidence_fingerprint=fingerprint,
        processing_version="rules-v1",
        created_at=NOW,
        evidence_ids=(evidence_id,),
    )


def _disposition(
    disposition: DispositionKind,
    *,
    event_id: str = "event-1",
    conclusion_id: str = "conclusion-1",
    created_at: datetime = NOW + timedelta(minutes=1),
    replacement_text: str | None = None,
) -> DispositionEvent:
    return DispositionEvent(
        id=event_id,
        conclusion_id=conclusion_id,
        briefing_run_id="briefing-run-1",
        disposition=disposition,
        replacement_text=replacement_text,
        note="Synthetic correction.",
        created_at=created_at,
    )


def _populate_graph(store: StateStore) -> None:
    store.add_connector_run(_connector_run())
    store.add_briefing_run(_briefing_run())
    store.link_connector_run("briefing-run-1", "connector-run-1")
    store.add_source_evidence(_evidence())
    store.add_conclusion(_conclusion())


def test_fresh_database_applies_all_migrations_and_enforces_foreign_keys(
    tmp_path: Path,
) -> None:
    with Database.open(tmp_path / "state.sqlite3") as database:
        inspection = StateStore(database).inspect_state()

        assert inspection.schema_versions == (1, 2, 3, 4)
        assert database.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_database_upgrades_from_first_migration_and_is_idempotent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "upgrade.sqlite3"
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrations = load_migrations()

    apply_migrations(connection, migrations[:1])
    first_versions = [
        int(row["version"])
        for row in connection.execute("SELECT version FROM schema_migrations")
    ]
    assert first_versions == [1]

    apply_migrations(connection, migrations)
    apply_migrations(connection, migrations)
    upgraded_versions = [
        int(row["version"])
        for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
    ]
    assert upgraded_versions == [1, 2, 3, 4]
    connection.close()


def test_selected_normalized_task_persists_minimum_context_and_cascades(
    tmp_path: Path,
) -> None:
    with Database.open(tmp_path / "todoist-state.sqlite3") as database:
        store = StateStore(database)
        store.add_connector_run(_connector_run())
        store.add_source_evidence(_evidence())
        store.add_normalized_source_task(
            NormalizedSourceTask(
                evidence_id="evidence-1",
                title="Synthetic selected task",
                provider_priority=1,
                recurring=False,
                all_day=True,
                due_at=NOW,
                project_id="project-1",
                project_name="Synthetic project",
                section_id="section-1",
                section_name="Synthetic section",
                responsible_user_id="primary-user",
                labels=(("label-1", "Selected"),),
            )
        )

        inspection = store.inspect_state()
        assert inspection.normalized_source_tasks == 1
        assert inspection.normalized_source_task_labels == 1
        task_row = database.connection.execute(
            "SELECT * FROM normalized_source_tasks"
        ).fetchone()
        assert task_row is not None
        assert task_row["title"] == "Synthetic selected task"
        assert task_row["project_name"] == "Synthetic project"
        assert "description" not in task_row
        assert store.delete_source_evidence("evidence-1")
        assert store.inspect_state().normalized_source_tasks == 0
        assert store.inspect_state().normalized_source_task_labels == 0


def test_task_cleanup_removes_stale_records_but_preserves_correction_evidence(
    tmp_path: Path,
) -> None:
    with Database.open(tmp_path / "todoist-cleanup.sqlite3") as database:
        store = StateStore(database)
        store.add_connector_run(_connector_run())
        store.add_briefing_run(_briefing_run())
        for index in range(1, 4):
            evidence_id = f"evidence-{index}"
            store.add_source_evidence(
                _evidence(
                    evidence_id=evidence_id,
                    fingerprint=f"fingerprint-{index}",
                    source_record_id=f"task-{index}",
                )
            )
            store.add_normalized_source_task(
                NormalizedSourceTask(
                    evidence_id=evidence_id,
                    title=f"Synthetic task {index}",
                    provider_priority=1,
                    recurring=False,
                    all_day=True,
                    due_at=NOW,
                )
            )
        store.add_conclusion(_conclusion())
        store.append_disposition(_disposition(DispositionKind.DISMISSED))

        removed = store.prune_unselected_source_tasks(
            source="synthetic_tasks",
            retained_source_record_ids=frozenset({"task-3"}),
        )

        assert removed == 1
        remaining = database.connection.execute(
            """
            SELECT source_record_id
            FROM source_evidence
            ORDER BY source_record_id
            """
        ).fetchall()
        assert [str(row["source_record_id"]) for row in remaining] == [
            "task-1",
            "task-3",
        ]
        assert store.inspect_conclusion("conclusion-1") is not None
        assert store.inspect_state().normalized_source_tasks == 2


def test_applied_migration_checksum_cannot_change(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "checksum.sqlite3", isolation_level=None)
    connection.row_factory = sqlite3.Row
    original = Migration.create(1, "synthetic", "CREATE TABLE sample(id INTEGER);")
    changed = Migration.create(1, "synthetic", "CREATE TABLE changed(id INTEGER);")

    apply_migrations(connection, (original,))
    with pytest.raises(MigrationError):
        apply_migrations(connection, (changed,))

    connection.close()


def test_transactions_roll_back_and_foreign_keys_reject_orphans(
    tmp_path: Path,
) -> None:
    with Database.open(tmp_path / "transactions.sqlite3") as database:
        with (
            pytest.raises(RuntimeError, match="synthetic rollback"),
            database.transaction() as connection,
        ):
            connection.execute(
                """
                INSERT INTO briefing_runs(
                    id,
                    briefing_date,
                    timezone,
                    invocation_mode,
                    started_at,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "rolled-back-run",
                    "2026-07-25",
                    "America/New_York",
                    "test",
                    NOW.isoformat(),
                    "running",
                ),
            )
            raise RuntimeError("synthetic rollback")

        store = StateStore(database)
        assert store.inspect_state().briefing_runs == 0
        with pytest.raises(sqlite3.IntegrityError):
            store.add_source_evidence(_evidence(connector_run_id="missing-run"))
        assert store.inspect_state().source_evidence == 0


def test_conclusion_history_is_append_oriented_and_inspectable(
    tmp_path: Path,
) -> None:
    with Database.open(tmp_path / "history.sqlite3") as database:
        store = StateStore(database)
        _populate_graph(store)
        store.append_disposition(_disposition(DispositionKind.CONFIRMED))
        store.append_disposition(
            _disposition(
                DispositionKind.CORRECTED,
                event_id="event-2",
                created_at=NOW + timedelta(minutes=2),
                replacement_text="Prepare the revised planning agenda.",
            )
        )

        state = store.inspect_conclusion("conclusion-1")

        assert state is not None
        assert state.conclusion.statement == "Prepare the planning agenda."
        assert [event.disposition for event in state.history] == [
            DispositionKind.CONFIRMED,
            DispositionKind.CORRECTED,
        ]
        assert state.latest_disposition is not None
        assert (
            state.latest_disposition.replacement_text
            == "Prepare the revised planning agenda."
        )
        assert state.evidence[0].source_record_id == "task-1"
        assert database.connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_corrections_replace_and_dispositions_suppress_unchanged_evidence(
    tmp_path: Path,
) -> None:
    with Database.open(tmp_path / "recurrence.sqlite3") as database:
        store = StateStore(database)
        _populate_graph(store)

        untouched = store.recurrence_decision("fingerprint-v1")
        assert untouched.action is RecurrenceAction.SHOW

        store.append_disposition(
            _disposition(
                DispositionKind.CORRECTED,
                replacement_text="Prepare the revised planning agenda.",
            )
        )
        corrected = store.recurrence_decision("fingerprint-v1")
        assert corrected.action is RecurrenceAction.REPLACE
        assert corrected.replacement_text == "Prepare the revised planning agenda."

        store.append_disposition(
            _disposition(
                DispositionKind.DISMISSED,
                event_id="event-2",
                created_at=NOW + timedelta(minutes=2),
            )
        )
        dismissed = store.recurrence_decision("fingerprint-v1")
        assert dismissed.action is RecurrenceAction.SUPPRESS
        assert dismissed.disposition is DispositionKind.DISMISSED

        materially_changed = store.recurrence_decision("fingerprint-v2")
        assert materially_changed.action is RecurrenceAction.SHOW


@pytest.mark.parametrize(
    "disposition",
    [
        DispositionKind.DELEGATED,
        DispositionKind.RESCHEDULED,
        DispositionKind.COMPLETED,
        DispositionKind.INTENTIONALLY_ABANDONED,
    ],
)
def test_terminal_dispositions_prevent_recurrence(
    tmp_path: Path,
    disposition: DispositionKind,
) -> None:
    with Database.open(tmp_path / f"{disposition}.sqlite3") as database:
        store = StateStore(database)
        _populate_graph(store)
        store.append_disposition(_disposition(disposition))

        decision = store.recurrence_decision("fingerprint-v1")

        assert decision.action is RecurrenceAction.SUPPRESS
        assert decision.disposition is disposition


def test_history_conclusions_evidence_and_briefings_can_be_deleted(
    tmp_path: Path,
) -> None:
    with Database.open(tmp_path / "deletion.sqlite3") as database:
        store = StateStore(database)
        _populate_graph(store)
        store.append_disposition(_disposition(DispositionKind.DISMISSED))

        assert store.delete_disposition_history("conclusion-1") == 1
        state = store.inspect_conclusion("conclusion-1")
        assert state is not None
        assert state.history == ()

        assert store.delete_conclusion("conclusion-1")
        assert store.inspect_conclusion("conclusion-1") is None
        assert store.inspect_state().source_evidence == 1

        store.add_conclusion(_conclusion(conclusion_id="conclusion-2"))
        assert store.delete_source_evidence("evidence-1")
        assert store.inspect_state().conclusions == 0

        assert store.delete_briefing_run("briefing-run-1")
        assert store.inspect_state().briefing_runs == 0


def test_conclusion_survives_until_its_final_evidence_is_deleted(
    tmp_path: Path,
) -> None:
    with Database.open(tmp_path / "multi-evidence.sqlite3") as database:
        store = StateStore(database)
        store.add_connector_run(_connector_run())
        store.add_source_evidence(_evidence())
        store.add_source_evidence(
            _evidence(
                evidence_id="evidence-2",
                fingerprint="supporting-fingerprint",
            )
        )
        conclusion = _conclusion()
        store.add_conclusion(
            Conclusion(
                id=conclusion.id,
                kind=conclusion.kind,
                classification=conclusion.classification,
                statement=conclusion.statement,
                explanation=conclusion.explanation,
                confidence=conclusion.confidence,
                evidence_fingerprint=conclusion.evidence_fingerprint,
                processing_version=conclusion.processing_version,
                created_at=conclusion.created_at,
                evidence_ids=("evidence-1", "evidence-2"),
            )
        )

        assert store.delete_source_evidence("evidence-1")
        state = store.inspect_conclusion("conclusion-1")
        assert state is not None
        assert state.conclusion.evidence_ids == ("evidence-2",)

        assert store.delete_source_evidence("evidence-2")
        assert store.inspect_conclusion("conclusion-1") is None


def test_pruning_run_metadata_preserves_correction_evidence(
    tmp_path: Path,
) -> None:
    with Database.open(tmp_path / "retention.sqlite3") as database:
        store = StateStore(database)
        _populate_graph(store)
        store.append_disposition(_disposition(DispositionKind.DISMISSED))

        deleted = store.prune_run_metadata(NOW + timedelta(days=31))
        state = store.inspect_conclusion("conclusion-1")

        assert deleted == (1, 1)
        assert state is not None
        assert state.evidence[0].connector_run_id is None
        assert state.history[0].briefing_run_id is None
        assert (
            store.recurrence_decision("fingerprint-v1").action
            is RecurrenceAction.SUPPRESS
        )


def test_reset_removes_product_state_but_preserves_migrations(tmp_path: Path) -> None:
    with Database.open(tmp_path / "reset.sqlite3") as database:
        store = StateStore(database)
        _populate_graph(store)
        store.append_disposition(_disposition(DispositionKind.DISMISSED))

        inspection = store.reset()

        assert inspection.schema_versions == (1, 2, 3, 4)
        assert inspection.connector_runs == 0
        assert inspection.briefing_runs == 0
        assert inspection.source_evidence == 0
        assert inspection.conclusions == 0
        assert inspection.disposition_events == 0
        assert inspection.oauth_clients == 0
        assert inspection.connector_authorizations == 0


def test_timezone_naive_timestamps_and_oversized_excerpts_are_rejected(
    tmp_path: Path,
) -> None:
    with Database.open(tmp_path / "validation.sqlite3") as database:
        store = StateStore(database)
        naive_run = _connector_run()
        naive_run = ConnectorRun(
            id=naive_run.id,
            source=naive_run.source,
            approved_scope=naive_run.approved_scope,
            started_at=datetime(2026, 7, 25, 12, 0),
            status=naive_run.status,
            coverage_status=naive_run.coverage_status,
        )
        with pytest.raises(ValueError, match="timezone-aware"):
            store.add_connector_run(naive_run)

        store.add_connector_run(_connector_run())
        oversized = _evidence()
        oversized = SourceEvidence(
            id=oversized.id,
            connector_run_id=oversized.connector_run_id,
            source=oversized.source,
            source_record_id=oversized.source_record_id,
            evidence_fingerprint=oversized.evidence_fingerprint,
            retrieved_at=oversized.retrieved_at,
            excerpt="x" * 2001,
        )
        with pytest.raises(sqlite3.IntegrityError):
            store.add_source_evidence(oversized)
