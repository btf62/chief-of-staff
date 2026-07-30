"""Operational on-demand briefing with honest partial-source behavior."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from chief_of_staff.connector_health import (
    ApprovedConnector,
    ConnectorHealth,
    ConnectorHealthReport,
    retrieval_failure_report,
)
from chief_of_staff.connectors import (
    GMAIL_WORK_ALIAS,
    GMAIL_WORK_INSTANCE,
    GOOGLE_CALENDAR_PRIMARY_INSTANCE,
    JIRA_PRIMARY_INSTANCE,
    TODOIST_PRIMARY_INSTANCE,
    ConnectorInstance,
    ConnectorInstanceIdentity,
    GmailConnector,
    GoogleCalendarConnector,
    JiraConnector,
    ReadOnlyConnector,
    RepositoryContextConnector,
    StaticConnector,
    TodoistConnector,
)
from chief_of_staff.domain import (
    ConnectorDomain,
    ConnectorInstanceMetadata,
    CoverageStatus,
)
from chief_of_staff.gmail_mvp_trial import GmailMvpTrialRunner
from chief_of_staff.live_trial import (
    LiveCalendarTrialRunner,
    LiveJiraIssueTrialRunner,
    LiveTodoistTrialRunner,
    _with_persistence_coverage,
)
from chief_of_staff.persistence import StateStore
from chief_of_staff.pipeline import DeterministicBriefingPipeline, resolve_context
from chief_of_staff.web import presentation_from_plan


class InsufficientBriefingEvidence(RuntimeError):
    """Raised before persistence when no approved external source was checked."""


@dataclass(frozen=True, slots=True)
class OnDemandBriefingReport:
    """Safe operational result for one successful full or reduced briefing."""

    briefing_path: Path
    review_path: Path | None
    briefing_word_count: int
    source_coverage: tuple[tuple[str, str], ...]
    degraded_sources: tuple[ConnectorHealthReport, ...]


@dataclass(frozen=True, slots=True)
class OnDemandBriefingRunner:
    """Run healthy sources independently and archive only a completed result."""

    state_store: StateStore
    repository_root: Path
    repository_paths: tuple[Path, ...]
    approved_connectors: tuple[ApprovedConnector, ...]
    preflight: tuple[ConnectorHealthReport, ...]
    calendar_connector: GoogleCalendarConnector | None
    todoist_connector: TodoistConnector | None
    jira_connector: JiraConnector | None
    gmail_connector: GmailConnector | None
    briefing_directory: Path
    review_directory: Path
    briefing_date_override: date | None = None
    timezone: str = "America/New_York"
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def run(self) -> OnDemandBriefingReport:
        """Generate one briefing without contacting preflight-blocked sources."""

        started_at = self.clock()
        briefing_date = (
            self.briefing_date_override
            or started_at.astimezone(ZoneInfo(self.timezone)).date()
        )
        run_id = f"on-demand-{uuid.uuid4().hex}"
        context = resolve_context(
            run_id=run_id,
            briefing_date=briefing_date,
            timezone=self.timezone,
            invocation_mode="on_demand",
            lookahead_days=7,
        )
        connectors = (
            RepositoryContextConnector(
                root=self.repository_root,
                approved_paths=self.repository_paths,
                clock=self.clock,
            ),
            *self._external_connectors(),
        )
        gmail_refresh = None
        gmail_fallback = None
        if self.gmail_connector is not None:
            gmail_refresh = self.gmail_connector.allow_authorization_refresh
            gmail_fallback = self.gmail_connector.allow_window_fallback
            self.gmail_connector.allow_authorization_refresh = True
            self.gmail_connector.allow_window_fallback = True
        try:
            result = DeterministicBriefingPipeline().run(
                context,
                connectors,
            )
        finally:
            if self.gmail_connector is not None:
                self.gmail_connector.allow_authorization_refresh = cast(
                    bool,
                    gmail_refresh,
                )
                self.gmail_connector.allow_window_fallback = cast(
                    bool,
                    gmail_fallback,
                )
        coverage_by_source = {
            coverage.source: coverage for coverage in result.plan.coverage
        }
        useful_sources = tuple(
            coverage
            for source, coverage in coverage_by_source.items()
            if source != "repository_context"
            and coverage.status in {CoverageStatus.COMPLETE, CoverageStatus.PARTIAL}
        )
        if not useful_sources:
            raise InsufficientBriefingEvidence(
                "No approved external source completed; no briefing was archived."
            )

        completed_at = self.clock()
        self._ensure_approved_instance_metadata(completed_at)
        helper = LiveCalendarTrialRunner(
            state_store=self.state_store,
            repository_root=self.repository_root,
            repository_paths=self.repository_paths,
            calendar_connector=cast(
                GoogleCalendarConnector,
                self.calendar_connector,
            ),
            output_directory=self.briefing_directory,
            timezone=self.timezone,
            clock=self.clock,
        )
        _connector_run_ids, evidence_ids = helper._persist_run_graph(
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            context=context,
            result=result,
        )
        context_persisted: dict[str, dict[str, int]] = {}
        if self.todoist_connector is not None and coverage_by_source[
            "todoist"
        ].status in {CoverageStatus.COMPLETE, CoverageStatus.PARTIAL}:
            persisted = LiveTodoistTrialRunner(
                state_store=self.state_store,
                repository_root=self.repository_root,
                repository_paths=self.repository_paths,
                calendar_connector=cast(
                    GoogleCalendarConnector,
                    self.calendar_connector,
                ),
                todoist_connector=self.todoist_connector,
                output_directory=self.briefing_directory,
                timezone=self.timezone,
                clock=self.clock,
            )._persist_todoist_tasks(
                evidence_ids=evidence_ids,
                timezone=self.timezone,
                prune_stale=(
                    coverage_by_source["todoist"].status is CoverageStatus.COMPLETE
                ),
            )
            context_persisted["todoist"] = {
                "projects": persisted.projects_persisted,
                "sections": persisted.sections_persisted,
                "labels": persisted.labels_persisted,
            }
        if self.jira_connector is not None and coverage_by_source["jira"].status in {
            CoverageStatus.COMPLETE,
            CoverageStatus.PARTIAL,
        }:
            LiveJiraIssueTrialRunner(
                state_store=self.state_store,
                repository_root=self.repository_root,
                repository_paths=self.repository_paths,
                calendar_connector=cast(
                    GoogleCalendarConnector,
                    self.calendar_connector,
                ),
                todoist_connector=cast(TodoistConnector, self.todoist_connector),
                jira_connector=self.jira_connector,
                output_directory=self.briefing_directory,
                timezone=self.timezone,
                clock=self.clock,
            )._persist_jira_issues(
                evidence_ids=evidence_ids,
                prune_stale=(
                    coverage_by_source["jira"].status is CoverageStatus.COMPLETE
                ),
            )
        review_path = None
        if self.gmail_connector is not None and coverage_by_source["gmail"].status in {
            CoverageStatus.COMPLETE,
            CoverageStatus.PARTIAL,
        }:
            gmail_helper = GmailMvpTrialRunner(
                state_store=self.state_store,
                repository_root=self.repository_root,
                repository_paths=self.repository_paths,
                calendar_connector=cast(
                    GoogleCalendarConnector,
                    self.calendar_connector,
                ),
                todoist_connector=cast(TodoistConnector, self.todoist_connector),
                jira_connector=cast(JiraConnector, self.jira_connector),
                gmail_connector=self.gmail_connector,
                briefing_directory=self.briefing_directory,
                review_directory=self.review_directory,
                timezone=self.timezone,
                clock=self.clock,
            )
            gmail_helper._persist_gmail(
                evidence_ids=evidence_ids,
                run_id=run_id,
                created_at=completed_at,
            )
            displayed_gmail_ids = {
                source.source_record_id
                for section in result.plan.sections
                for item in section.items
                for source in item.sources
                if source.source == "gmail"
            }
            review_path = gmail_helper._write_review(
                run_id,
                displayed_source_record_ids=frozenset(displayed_gmail_ids),
            )
        result = _with_persistence_coverage(
            result=result,
            persisted_by_source={
                source: sum(
                    evidence_source == source
                    for evidence_source, _instance_id, _record_id in evidence_ids
                )
                for source in coverage_by_source
            },
            context_persisted_by_source=context_persisted,
        )
        self.state_store.save_briefing_presentation(
            presentation_from_plan(
                result.plan,
                briefing_run_id=run_id,
                created_at=completed_at,
                state_store=self.state_store,
            )
        )
        briefing_path = helper._write_briefing(
            briefing_date=briefing_date.isoformat(),
            run_id=run_id,
            content=result.rendered.text,
        )
        for coverage in result.plan.coverage:
            if coverage.source != "repository" and coverage.status in {
                CoverageStatus.COMPLETE,
                CoverageStatus.PARTIAL,
            }:
                connector_id = coverage.connector_instance_id or coverage.source
                if (
                    self.state_store.get_connector_authorization(connector_id)
                    is not None
                ):
                    self.state_store.mark_connector_authorization_used(
                        connector_id,
                        used_at=completed_at,
                    )
        degraded = self._degraded_reports(result.plan.coverage)
        return OnDemandBriefingReport(
            briefing_path=briefing_path,
            review_path=review_path,
            briefing_word_count=result.rendered.word_count,
            source_coverage=tuple(
                (
                    coverage.account_alias or coverage.source,
                    coverage.status.value,
                )
                for coverage in result.plan.coverage
            ),
            degraded_sources=degraded,
        )

    def _external_connectors(self) -> tuple[ReadOnlyConnector, ...]:
        actual: dict[str, ReadOnlyConnector | None] = {
            GOOGLE_CALENDAR_PRIMARY_INSTANCE: self.calendar_connector,
            TODOIST_PRIMARY_INSTANCE: self.todoist_connector,
            JIRA_PRIMARY_INSTANCE: self.jira_connector,
            GMAIL_WORK_INSTANCE: self.gmail_connector,
        }
        return tuple(
            _connector_instance(
                report.connector,
                actual[report.connector.instance_id] if report.can_retrieve else None,
                unavailable_health=report.health,
            )
            for report in self.preflight
        )

    def _degraded_reports(
        self,
        coverage: tuple[object, ...],
    ) -> tuple[ConnectorHealthReport, ...]:
        from chief_of_staff.connectors import SourceCoverage

        by_instance = {
            report.connector.instance_id: report for report in self.preflight
        }
        degraded: list[ConnectorHealthReport] = []
        for item in coverage:
            if not isinstance(item, SourceCoverage) or item.source == "repository":
                continue
            preflight = by_instance.get(item.connector_instance_id or "")
            if item.status in {CoverageStatus.COMPLETE, CoverageStatus.PARTIAL}:
                continue
            if preflight is not None and not preflight.can_retrieve:
                degraded.append(preflight)
                continue
            connector = next(
                candidate
                for candidate in self.approved_connectors
                if candidate.instance_id == item.connector_instance_id
            )
            degraded.append(
                retrieval_failure_report(
                    connector,
                    error_category=item.error_category,
                )
            )
        return tuple(degraded)

    def _ensure_approved_instance_metadata(self, now: datetime) -> None:
        providers = {
            GOOGLE_CALENDAR_PRIMARY_INSTANCE: "google_calendar",
            TODOIST_PRIMARY_INSTANCE: "todoist",
            JIRA_PRIMARY_INSTANCE: "jira",
            GMAIL_WORK_INSTANCE: "gmail",
        }
        for approved in self.approved_connectors:
            if (
                self.state_store.get_connector_instance(approved.instance_id)
                is not None
            ):
                continue
            self.state_store.save_connector_instance(
                ConnectorInstanceMetadata(
                    id=approved.instance_id,
                    provider=providers[approved.instance_id],
                    alias=approved.display_name,
                    domain_classification=ConnectorDomain.WORK,
                    approved_resource_boundary=approved.display_name,
                    approved_scopes=approved.expected_scope,
                    retrieval_configuration="on-demand preflight",
                    retention_policy_reference="ADR-0004",
                    enabled=False,
                    created_at=now,
                    updated_at=now,
                )
            )


def _connector_instance(
    approved: ApprovedConnector,
    connector: ReadOnlyConnector | None,
    *,
    unavailable_health: ConnectorHealth,
) -> ConnectorInstance:
    provider = {
        GOOGLE_CALENDAR_PRIMARY_INSTANCE: "google_calendar",
        TODOIST_PRIMARY_INSTANCE: "todoist",
        JIRA_PRIMARY_INSTANCE: "jira",
        GMAIL_WORK_INSTANCE: "gmail",
    }[approved.instance_id]
    alias = (
        GMAIL_WORK_ALIAS
        if approved.instance_id == GMAIL_WORK_INSTANCE
        else approved.display_name
    )
    selected = connector or StaticConnector(
        source_name=provider,
        approved_scope=approved.expected_scope,
        items=(),
        status=(
            CoverageStatus.UNAUTHORIZED
            if unavailable_health
            in {
                ConnectorHealth.EXPIRED,
                ConnectorHealth.MISSING,
                ConnectorHealth.UNAUTHORIZED,
                ConnectorHealth.BOUNDARY_EXCEEDED,
            }
            else CoverageStatus.UNAVAILABLE
        ),
        error_category=unavailable_health.value.replace(" ", "_"),
    )
    return ConnectorInstance(
        identity=ConnectorInstanceIdentity(
            id=approved.instance_id,
            provider=provider,
            alias=alias,
            domain_classification=ConnectorDomain.WORK,
        ),
        connector=selected,
    )
