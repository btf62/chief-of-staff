"""Synthetic on-demand reduced-coverage persistence tests."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import pytest

from chief_of_staff.connector_health import (
    APPROVED_CONNECTORS,
    ConnectorHealth,
    ConnectorHealthReport,
)
from chief_of_staff.connectors import (
    GoogleCalendarConnector,
    StaticConnector,
    TodoistAuthorization,
    TodoistConnector,
    TodoistLabelPage,
    TodoistPageRequest,
    TodoistProject,
    TodoistSection,
    TodoistTaskPage,
    TodoistUser,
)
from chief_of_staff.domain import CoverageStatus
from chief_of_staff.on_demand import (
    InsufficientBriefingEvidence,
    OnDemandBriefingRunner,
)
from chief_of_staff.persistence import Database, StateStore

NOW = datetime(2026, 7, 30, 13, 20, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _TodoistAuthorizationProvider:
    def get_todoist_authorization(
        self,
        account_reference: str,
    ) -> TodoistAuthorization:
        return TodoistAuthorization(
            account_reference=account_reference,
            account_identity="synthetic@example.invalid",
            granted_scopes=frozenset({"data:read"}),
            credential_reference="synthetic",
        )


@dataclass(frozen=True, slots=True)
class _EmptyTodoistTransport:
    def get_authenticated_user(
        self,
        authorization: TodoistAuthorization,
    ) -> TodoistUser:
        del authorization
        return TodoistUser(
            id="synthetic-user",
            email="synthetic@example.invalid",
            timezone="America/New_York",
        )

    def list_tasks(
        self,
        authorization: TodoistAuthorization,
        request: TodoistPageRequest,
    ) -> TodoistTaskPage:
        del authorization, request
        return TodoistTaskPage(tasks=())

    def get_project(
        self,
        authorization: TodoistAuthorization,
        project_id: str,
    ) -> TodoistProject:
        del authorization, project_id
        raise AssertionError("no project lookup is expected")

    def get_section(
        self,
        authorization: TodoistAuthorization,
        section_id: str,
    ) -> TodoistSection:
        del authorization, section_id
        raise AssertionError("no section lookup is expected")

    def list_labels(
        self,
        authorization: TodoistAuthorization,
        request: TodoistPageRequest,
    ) -> TodoistLabelPage:
        del authorization, request
        raise AssertionError("no label lookup is expected")


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


def _preflight_many(
    healthy_instances: set[str],
) -> tuple[ConnectorHealthReport, ...]:
    return tuple(
        ConnectorHealthReport(
            connector=connector,
            health=(
                ConnectorHealth.HEALTHY
                if connector.instance_id in healthy_instances
                else ConnectorHealth.UNAUTHORIZED
            ),
            can_retrieve=connector.instance_id in healthy_instances,
            detail="Synthetic safe health.",
        )
        for connector in APPROVED_CONNECTORS
    )


def _runner(
    tmp_path: Path,
    store: StateStore,
    *,
    calendar_available: bool,
    scheduled_policy: bool = False,
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
        invocation_mode=("scheduled_morning" if scheduled_policy else "on_demand"),
        run_id_prefix=("scheduled-morning" if scheduled_policy else "on-demand"),
        require_calendar_and_action_source=scheduled_policy,
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
        assert inspection.briefing_archived_facts == 1


def test_insufficient_evidence_creates_no_run_or_archive(tmp_path: Path) -> None:
    with Database.open(tmp_path / ".local" / "state.sqlite3") as database:
        store = StateStore(database)

        with pytest.raises(InsufficientBriefingEvidence):
            _runner(tmp_path, store, calendar_available=False).run()

        inspection = store.inspect_state()
        assert inspection.briefing_runs == 0
        assert store.latest_briefing_presentation() is None
        assert not (tmp_path / ".local" / "briefings").exists()


def test_scheduled_policy_rejects_calendar_only_before_persistence(
    tmp_path: Path,
) -> None:
    with Database.open(tmp_path / ".local" / "state.sqlite3") as database:
        store = StateStore(database)

        with pytest.raises(InsufficientBriefingEvidence):
            _runner(
                tmp_path,
                store,
                calendar_available=True,
                scheduled_policy=True,
            ).run()

        inspection = store.inspect_state()
        assert inspection.briefing_runs == 0
        assert store.latest_briefing_presentation() is None


def test_scheduled_policy_archives_distinct_invocation_with_action_source(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    document = repository_root / "context.md"
    document.parent.mkdir(parents=True)
    document.write_text("# Synthetic governing context\n", encoding="utf-8")
    calendar = cast(
        GoogleCalendarConnector,
        StaticConnector(
            source_name="google_calendar",
            approved_scope=APPROVED_CONNECTORS[0].expected_scope,
            items=(),
            status=CoverageStatus.COMPLETE,
        ),
    )
    todoist = TodoistConnector(
        account_reference="primary-user",
        authorization_provider=_TodoistAuthorizationProvider(),
        transport=_EmptyTodoistTransport(),
        clock=lambda: NOW,
    )
    healthy = {
        APPROVED_CONNECTORS[0].instance_id,
        APPROVED_CONNECTORS[1].instance_id,
    }
    with Database.open(tmp_path / ".local" / "state.sqlite3") as database:
        store = StateStore(database)
        report = OnDemandBriefingRunner(
            state_store=store,
            repository_root=repository_root,
            repository_paths=(Path("context.md"),),
            approved_connectors=APPROVED_CONNECTORS,
            preflight=_preflight_many(healthy),
            calendar_connector=calendar,
            todoist_connector=todoist,
            jira_connector=None,
            gmail_connector=None,
            briefing_directory=tmp_path / ".local" / "briefings",
            review_directory=tmp_path / ".local" / "reviews",
            briefing_date_override=date(2026, 7, 30),
            clock=lambda: NOW,
            invocation_mode="scheduled_morning",
            run_id_prefix="scheduled-morning",
            require_calendar_and_action_source=True,
        ).run()

        presentation = store.get_briefing_presentation(report.briefing_run_id)
        assert report.briefing_run_id.startswith("scheduled-morning-")
        assert presentation is not None
        assert presentation.run.invocation_mode == "scheduled_morning"
