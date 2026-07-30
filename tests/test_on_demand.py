"""Synthetic on-demand reduced-coverage persistence tests."""

from __future__ import annotations

import stat
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import pytest

from chief_of_staff.connector_health import (
    APPROVED_CONNECTORS,
    ConnectorHealth,
    ConnectorHealthReport,
)
from chief_of_staff.connectors import GoogleCalendarConnector, StaticConnector
from chief_of_staff.domain import CoverageStatus
from chief_of_staff.on_demand import (
    InsufficientBriefingEvidence,
    OnDemandBriefingRunner,
)
from chief_of_staff.persistence import Database, StateStore

NOW = datetime(2026, 7, 30, 13, 20, tzinfo=UTC)


def _preflight(
    healthy_instance: str | None,
) -> tuple[ConnectorHealthReport, ...]:
    return tuple(
        ConnectorHealthReport(
            connector=connector,
            health=(
                ConnectorHealth.HEALTHY
                if connector.instance_id == healthy_instance
                else ConnectorHealth.UNAUTHORIZED
            ),
            can_retrieve=connector.instance_id == healthy_instance,
            detail=(
                f"{connector.display_name} is ready."
                if connector.instance_id == healthy_instance
                else f"{connector.display_name} has not been authorized."
            ),
        )
        for connector in APPROVED_CONNECTORS
    )


def _runner(
    tmp_path: Path,
    store: StateStore,
    *,
    calendar_available: bool,
) -> OnDemandBriefingRunner:
    repository_root = tmp_path / "repository"
    document = repository_root / "context.md"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text("# Synthetic governing context\n", encoding="utf-8")
    calendar = (
        cast(
            GoogleCalendarConnector,
            StaticConnector(
                source_name="google_calendar",
                approved_scope=APPROVED_CONNECTORS[0].expected_scope,
                items=(),
                status=CoverageStatus.COMPLETE,
            ),
        )
        if calendar_available
        else None
    )
    return OnDemandBriefingRunner(
        state_store=store,
        repository_root=repository_root,
        repository_paths=(Path("context.md"),),
        approved_connectors=APPROVED_CONNECTORS,
        preflight=_preflight(
            APPROVED_CONNECTORS[0].instance_id if calendar_available else None
        ),
        calendar_connector=calendar,
        todoist_connector=None,
        jira_connector=None,
        gmail_connector=None,
        briefing_directory=tmp_path / ".local" / "briefings",
        review_directory=tmp_path / ".local" / "reviews",
        briefing_date_override=date(2026, 7, 30),
        clock=lambda: NOW,
    )


def test_reduced_coverage_archives_only_after_one_source_completes(
    tmp_path: Path,
) -> None:
    with Database.open(tmp_path / ".local" / "state.sqlite3") as database:
        store = StateStore(database)
        report = _runner(tmp_path, store, calendar_available=True).run()

        assert report.briefing_path.exists()
        assert stat.S_IMODE(report.briefing_path.stat().st_mode) == 0o600
        assert len(report.degraded_sources) == 3
        assert store.latest_briefing_presentation() is not None
        inspection = store.inspect_state()
        assert inspection.briefing_runs == 1
        assert inspection.connector_runs == 5


def test_insufficient_evidence_creates_no_run_or_archive(tmp_path: Path) -> None:
    with Database.open(tmp_path / ".local" / "state.sqlite3") as database:
        store = StateStore(database)

        with pytest.raises(InsufficientBriefingEvidence):
            _runner(tmp_path, store, calendar_available=False).run()

        inspection = store.inspect_state()
        assert inspection.briefing_runs == 0
        assert store.latest_briefing_presentation() is None
        assert not (tmp_path / ".local" / "briefings").exists()
