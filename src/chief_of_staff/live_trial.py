"""Bounded live Calendar trial with local-only persistence and safe reporting."""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from chief_of_staff.connectors import (
    ContextResourceCoverage,
    GoogleCalendarConnector,
    RepositoryContextConnector,
    TodoistConnector,
    task_due_at,
)
from chief_of_staff.domain import (
    AuthorizationStatus,
    BriefingRun,
    BriefingStatus,
    ConnectorRun,
    ConnectorStatus,
    CoverageStatus,
    CredentialHealth,
    NormalizedSourceTask,
    SourceEvidence,
)
from chief_of_staff.persistence import SourceTaskReconciliation, StateStore
from chief_of_staff.pipeline import (
    BriefingSectionName,
    DeterministicBriefingPipeline,
    PipelineResult,
    build_reduced_plan,
    recompose_pipeline_result,
    render_briefing,
    resolve_context,
    validate_briefing,
)


class LiveTrialError(RuntimeError):
    """Raised when the bounded trial cannot produce an honest briefing."""


@dataclass(frozen=True, slots=True)
class LiveTrialReport:
    """Privacy-safe trial facts suitable for the mandatory stop report."""

    oauth_project_id: str
    account_identity: str
    granted_scope: str
    credential_health: str
    retrieval_window_start: datetime
    retrieval_window_end: datetime
    calendar_event_count: int
    calendar_page_count: int
    output_path: Path
    briefing_word_count: int
    connector_run_count: int
    evidence_reference_count: int
    raw_payload_persisted: bool = False
    hosted_inference_used: bool = False

    @property
    def pagination_occurred(self) -> bool:
        return self.calendar_page_count > 1


@dataclass(frozen=True, slots=True)
class LiveCalendarTrialRunner:
    """Run only approved repository context and live primary Calendar."""

    state_store: StateStore
    repository_root: Path
    repository_paths: tuple[Path, ...]
    calendar_connector: GoogleCalendarConnector
    output_directory: Path
    timezone: str = "America/New_York"
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def run(self) -> LiveTrialReport:
        """Generate, persist, and report one bounded deterministic briefing."""

        started_at = self.clock()
        briefing_date = started_at.astimezone(ZoneInfo(self.timezone)).date()
        run_id = f"live-calendar-{uuid.uuid4().hex}"
        context = resolve_context(
            run_id=run_id,
            briefing_date=briefing_date,
            timezone=self.timezone,
            invocation_mode="bounded_live_trial",
            lookahead_days=7,
        )
        repository_connector = RepositoryContextConnector(
            root=self.repository_root,
            approved_paths=self.repository_paths,
            clock=self.clock,
        )
        result = DeterministicBriefingPipeline().run(
            context,
            (repository_connector, self.calendar_connector),
        )
        completed_at = self.clock()

        calendar_coverage = next(
            coverage
            for coverage in result.plan.coverage
            if coverage.source == "google_calendar"
        )
        if calendar_coverage.status is CoverageStatus.UNAUTHORIZED:
            self.state_store.set_connector_authorization_health(
                "google_calendar",
                status=AuthorizationStatus.ERROR,
                health=CredentialHealth.ERROR,
                updated_at=completed_at,
            )
            raise LiveTrialError("Google Calendar authorization failed")
        if calendar_coverage.status is CoverageStatus.UNAVAILABLE:
            raise LiveTrialError("Google Calendar retrieval was unavailable")

        client = self.state_store.get_oauth_client("google_calendar")
        authorization = self.state_store.get_connector_authorization("google_calendar")
        if client is None or authorization is None:
            raise LiveTrialError("Google Calendar authorization metadata is missing")

        connector_run_ids, evidence_ids = self._persist_run_graph(
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            context=context,
            result=result,
        )
        result = _with_persistence_coverage(
            result=result,
            persisted_by_source={
                source: sum(
                    evidence_source == source
                    for evidence_source, _source_record_id in evidence_ids
                )
                for source in connector_run_ids
            },
        )
        output_path = self._write_briefing(
            briefing_date=briefing_date.isoformat(),
            run_id=run_id,
            content=result.rendered.text,
        )
        self.state_store.mark_connector_authorization_used(
            "google_calendar",
            used_at=completed_at,
        )

        calendar_records = tuple(
            record
            for record in result.deduplication.records
            if record.provenance.source == "google_calendar"
        )
        return LiveTrialReport(
            oauth_project_id=client.oauth_project_id,
            account_identity=authorization.account_identity,
            granted_scope=authorization.granted_scope,
            credential_health=authorization.credential_health.value,
            retrieval_window_start=context.retrieval_window.starts_at,
            retrieval_window_end=context.retrieval_window.ends_at,
            calendar_event_count=len(calendar_records),
            calendar_page_count=calendar_coverage.page_count or 0,
            output_path=output_path,
            briefing_word_count=result.rendered.word_count,
            connector_run_count=len(connector_run_ids),
            evidence_reference_count=len(result.deduplication.records),
        )

    def _persist_run_graph(
        self,
        *,
        run_id: str,
        started_at: datetime,
        completed_at: datetime,
        context: object,
        result: object,
    ) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
        from chief_of_staff.pipeline import InvocationContext, PipelineResult

        if not isinstance(context, InvocationContext) or not isinstance(
            result,
            PipelineResult,
        ):
            raise TypeError("trial persistence received invalid pipeline state")

        self.state_store.add_briefing_run(
            BriefingRun(
                id=run_id,
                briefing_date=context.briefing_date,
                timezone=context.timezone,
                invocation_mode=context.invocation_mode,
                started_at=started_at,
                completed_at=completed_at,
                status=BriefingStatus.SUCCEEDED,
            )
        )
        connector_run_ids: dict[str, str] = {}
        for coverage in result.plan.coverage:
            connector_run_id = f"{run_id}:{coverage.source}"
            connector_run_ids[coverage.source] = connector_run_id
            self.state_store.add_connector_run(
                ConnectorRun(
                    id=connector_run_id,
                    source=coverage.source,
                    approved_scope=coverage.approved_scope,
                    retrieval_window_start=context.retrieval_window.starts_at,
                    retrieval_window_end=context.retrieval_window.ends_at,
                    started_at=started_at,
                    completed_at=coverage.retrieved_at,
                    status=_connector_status(coverage.status),
                    coverage_status=coverage.status,
                    freshness_at=coverage.freshness_at,
                    error_category=coverage.error_category,
                    page_count=coverage.page_count,
                )
            )
            self.state_store.link_connector_run(run_id, connector_run_id)

        evidence_ids: dict[tuple[str, str], str] = {}
        for record in result.deduplication.records:
            source = record.provenance.source
            fingerprint = _evidence_fingerprint(
                source=source,
                source_record_id=record.provenance.source_record_id,
                freshness_at=record.provenance.freshness_at,
            )
            evidence_id = f"{run_id}:evidence:{hashlib.sha256(fingerprint.encode()).hexdigest()[:20]}"
            self.state_store.add_source_evidence(
                SourceEvidence(
                    id=evidence_id,
                    connector_run_id=connector_run_ids[source],
                    source=source,
                    source_record_id=record.provenance.source_record_id,
                    display_url=record.provenance.display_url,
                    excerpt=None,
                    evidence_fingerprint=fingerprint,
                    retrieved_at=record.provenance.retrieved_at,
                    freshness_at=record.provenance.freshness_at,
                )
            )
            evidence_ids[(source, record.provenance.source_record_id)] = evidence_id
        return connector_run_ids, evidence_ids

    def _write_briefing(
        self,
        *,
        briefing_date: str,
        run_id: str,
        content: str,
    ) -> Path:
        self.output_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.output_directory.chmod(0o700)
        output_path = self.output_directory / f"{briefing_date}-{run_id[-12:]}.md"
        descriptor = os.open(
            output_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        return output_path


def _connector_status(coverage_status: CoverageStatus) -> ConnectorStatus:
    if coverage_status is CoverageStatus.COMPLETE:
        return ConnectorStatus.SUCCEEDED
    if coverage_status is CoverageStatus.PARTIAL:
        return ConnectorStatus.PARTIAL
    return ConnectorStatus.FAILED


def _evidence_fingerprint(
    *,
    source: str,
    source_record_id: str,
    freshness_at: datetime | None,
) -> str:
    freshness = "" if freshness_at is None else freshness_at.isoformat()
    material = f"{source}\0{source_record_id}\0{freshness}"
    return hashlib.sha256(material.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class BriefingValidationSummary:
    """Privacy-safe deterministic briefing funnel for one date."""

    briefing_date: date
    output_path: Path
    word_count: int
    workday_type: str
    available_task_count: int
    candidate_task_count: int
    excluded_reasons: tuple[tuple[str, int], ...]
    displayed_task_count: int
    displayed_sections: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TodoistPersistenceResult:
    """Bounded persisted context and source-identity reconciliation."""

    tasks_persisted: int
    projects_persisted: int
    sections_persisted: int
    labels_persisted: int
    reconciliation: SourceTaskReconciliation


@dataclass(frozen=True, slots=True)
class LiveTodoistTrialReport:
    """Privacy-safe combined Calendar and Todoist trial facts."""

    oauth_application_owner: str
    account_identity: str
    granted_scope: str
    credential_health: str
    refresh_health: str | None
    retrieval_window_start: datetime
    retrieval_window_end: datetime
    active_task_count: int
    selected_task_count: int
    persisted_task_count: int
    previously_retained_task_count: int
    newly_persisted_task_count: int
    retained_task_count: int
    removed_task_count: int
    dependency_preserved_task_count: int
    projects_retrieved: int
    projects_persisted: int
    sections_retrieved: int
    sections_persisted: int
    labels_retrieved: int
    labels_persisted: int
    superseded_snapshot_count_removed: int
    duplicate_task_id_count: int
    full_active_task_collection_retrieved: bool
    concurrent_changes_cannot_be_excluded: bool
    qualification_counts: tuple[tuple[str, int], ...]
    qualification_overlaps: tuple[tuple[str, int], ...]
    task_page_count: int
    label_page_count: int
    calendar_event_count: int
    calendar_page_count: int
    briefings: tuple[BriefingValidationSummary, ...]
    descriptions_persisted: bool = False
    raw_payload_persisted: bool = False
    hosted_inference_used: bool = False
    other_live_source_used: bool = False

    @property
    def pagination_occurred(self) -> bool:
        return (
            self.task_page_count > 1
            or self.label_page_count > 1
            or self.calendar_page_count > 1
        )


@dataclass(frozen=True, slots=True)
class LiveTodoistTrialRunner:
    """Run the approved repository, Calendar, and Todoist trial once."""

    state_store: StateStore
    repository_root: Path
    repository_paths: tuple[Path, ...]
    calendar_connector: GoogleCalendarConnector
    todoist_connector: TodoistConnector
    output_directory: Path
    additional_briefing_dates: tuple[date, ...] = ()
    briefing_date_override: date | None = None
    timezone: str = "America/New_York"
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def run(self) -> LiveTodoistTrialReport:
        """Generate one combined deterministic briefing and persist bounded facts."""

        started_at = self.clock()
        briefing_date = (
            self.briefing_date_override
            or started_at.astimezone(ZoneInfo(self.timezone)).date()
        )
        run_id = f"live-todoist-{uuid.uuid4().hex}"
        context = resolve_context(
            run_id=run_id,
            briefing_date=briefing_date,
            timezone=self.timezone,
            invocation_mode="bounded_todoist_live_trial",
            lookahead_days=7,
        )
        repository_connector = RepositoryContextConnector(
            root=self.repository_root,
            approved_paths=self.repository_paths,
            clock=self.clock,
        )
        result = DeterministicBriefingPipeline().run(
            context,
            (
                repository_connector,
                self.calendar_connector,
                self.todoist_connector,
            ),
        )
        completed_at = self.clock()
        coverage_by_source = {
            coverage.source: coverage for coverage in result.plan.coverage
        }
        for source in ("google_calendar", "todoist"):
            coverage = coverage_by_source[source]
            if coverage.status is CoverageStatus.UNAUTHORIZED:
                raise LiveTrialError(f"{source} authorization failed")
            if coverage.status is CoverageStatus.UNAVAILABLE:
                raise LiveTrialError(f"{source} retrieval was unavailable")

        audit = self.todoist_connector.last_audit
        if audit is None:
            raise LiveTrialError("Todoist lifecycle audit is unavailable")
        client = self.state_store.get_oauth_client("todoist")
        authorization = self.state_store.get_connector_authorization("todoist")
        if client is None or authorization is None:
            raise LiveTrialError("Todoist authorization metadata is missing")

        helper = LiveCalendarTrialRunner(
            state_store=self.state_store,
            repository_root=self.repository_root,
            repository_paths=self.repository_paths,
            calendar_connector=self.calendar_connector,
            output_directory=self.output_directory,
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
        persistence = self._persist_todoist_tasks(
            evidence_ids=evidence_ids,
            timezone=context.timezone,
            prune_stale=(
                coverage_by_source["todoist"].status is CoverageStatus.COMPLETE
            ),
        )
        result = _with_persistence_coverage(
            result=result,
            persisted_by_source={
                source: sum(
                    evidence_source == source
                    for evidence_source, _source_record_id in evidence_ids
                )
                for source in coverage_by_source
            },
            context_persisted_by_source={
                "todoist": {
                    "projects": persistence.projects_persisted,
                    "sections": persistence.sections_persisted,
                    "labels": persistence.labels_persisted,
                }
            },
        )
        results_by_date = [(briefing_date, result)]
        for additional_date in self.additional_briefing_dates:
            additional_context = resolve_context(
                run_id=f"{run_id}:{additional_date.isoformat()}",
                briefing_date=additional_date,
                timezone=self.timezone,
                invocation_mode="bounded_todoist_live_validation",
                lookahead_days=7,
            )
            results_by_date.append(
                (
                    additional_date,
                    recompose_pipeline_result(result, additional_context),
                )
            )
        briefing_summaries = tuple(
            self._briefing_summary(
                helper=helper,
                briefing_date=output_date,
                run_id=run_id,
                result=output_result,
            )
            for output_date, output_result in results_by_date
        )
        self.state_store.mark_connector_authorization_used(
            "google_calendar",
            used_at=completed_at,
        )
        self.state_store.mark_connector_authorization_used(
            "todoist",
            used_at=completed_at,
        )
        calendar_coverage = coverage_by_source["google_calendar"]
        calendar_records = tuple(
            record
            for record in result.deduplication.records
            if record.provenance.source == "google_calendar"
        )
        return LiveTodoistTrialReport(
            oauth_application_owner=client.application_owner or "unspecified",
            account_identity=authorization.account_identity,
            granted_scope=authorization.granted_scope,
            credential_health=authorization.credential_health.value,
            refresh_health=(
                None
                if authorization.refresh_health is None
                else authorization.refresh_health.value
            ),
            retrieval_window_start=datetime.combine(
                briefing_date,
                datetime.min.time(),
                tzinfo=ZoneInfo(context.timezone),
            ),
            retrieval_window_end=datetime.combine(
                briefing_date + timedelta(days=15),
                datetime.min.time(),
                tzinfo=ZoneInfo(context.timezone),
            ),
            active_task_count=audit.active_task_count,
            selected_task_count=audit.selected_task_count,
            persisted_task_count=persistence.reconciliation.final_unique_count,
            previously_retained_task_count=(
                persistence.reconciliation.previous_unique_count
            ),
            newly_persisted_task_count=(
                persistence.reconciliation.newly_selected_count
            ),
            retained_task_count=persistence.reconciliation.retained_count,
            removed_task_count=persistence.reconciliation.removed_count,
            dependency_preserved_task_count=(
                persistence.reconciliation.dependency_preserved_count
            ),
            projects_retrieved=audit.projects_retrieved,
            projects_persisted=persistence.projects_persisted,
            sections_retrieved=audit.sections_retrieved,
            sections_persisted=persistence.sections_persisted,
            labels_retrieved=audit.labels_retrieved,
            labels_persisted=persistence.labels_persisted,
            superseded_snapshot_count_removed=(
                persistence.reconciliation.superseded_snapshot_count
            ),
            duplicate_task_id_count=audit.duplicate_task_id_count,
            full_active_task_collection_retrieved=(
                audit.full_active_task_collection_retrieved
            ),
            concurrent_changes_cannot_be_excluded=(
                audit.concurrent_changes_cannot_be_excluded
            ),
            qualification_counts=audit.qualification_counts,
            qualification_overlaps=audit.qualification_overlaps,
            task_page_count=audit.task_page_count,
            label_page_count=audit.label_page_count,
            calendar_event_count=len(calendar_records),
            calendar_page_count=calendar_coverage.page_count or 0,
            briefings=briefing_summaries,
        )

    def _persist_todoist_tasks(
        self,
        *,
        evidence_ids: dict[tuple[str, str], str],
        timezone: str,
        prune_stale: bool,
    ) -> TodoistPersistenceResult:
        audit = self.todoist_connector.last_audit
        if audit is None:
            raise LiveTrialError("Todoist lifecycle audit is unavailable")
        projects = {project.id: project for project in audit.projects}
        sections = {section.id: section for section in audit.sections}
        labels = {label.name.casefold(): label for label in audit.labels}
        persisted_projects: set[str] = set()
        persisted_sections: set[str] = set()
        persisted_labels: set[str] = set()
        persisted_tasks = 0
        for task in audit.selected_tasks:
            evidence_id = evidence_ids.get(("todoist", task.id))
            if evidence_id is None:
                continue
            project = None if task.project_id is None else projects.get(task.project_id)
            section = None if task.section_id is None else sections.get(task.section_id)
            resolved_labels = tuple(
                labels[name.casefold()]
                for name in task.label_names
                if name.casefold() in labels
            )
            due_at, all_day = task_due_at(task, timezone=timezone)
            self.state_store.add_normalized_source_task(
                NormalizedSourceTask(
                    evidence_id=evidence_id,
                    title=task.content,
                    provider_priority=task.priority,
                    recurring=task.recurring,
                    all_day=all_day,
                    due_at=due_at,
                    project_id=None if project is None else project.id,
                    project_name=None if project is None else project.name,
                    section_id=None if section is None else section.id,
                    section_name=None if section is None else section.name,
                    responsible_user_id=task.responsible_user_id,
                    parent_task_id=task.parent_id,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                    labels=tuple((label.id, label.name) for label in resolved_labels),
                )
            )
            persisted_tasks += 1
            if project is not None:
                persisted_projects.add(project.id)
            if section is not None:
                persisted_sections.add(section.id)
            persisted_labels.update(label.id for label in resolved_labels)
        current_evidence_ids = {
            task.id: evidence_ids[("todoist", task.id)]
            for task in audit.selected_tasks
            if ("todoist", task.id) in evidence_ids
        }
        reconciliation = (
            self.state_store.reconcile_source_task_snapshot(
                source="todoist",
                current_evidence_ids=current_evidence_ids,
            )
            if prune_stale
            else SourceTaskReconciliation(
                previous_unique_count=0,
                final_unique_count=persisted_tasks,
                newly_selected_count=persisted_tasks,
                retained_count=0,
                removed_count=0,
                superseded_snapshot_count=0,
                dependency_preserved_count=0,
            )
        )
        return TodoistPersistenceResult(
            tasks_persisted=persisted_tasks,
            projects_persisted=len(persisted_projects),
            sections_persisted=len(persisted_sections),
            labels_persisted=len(persisted_labels),
            reconciliation=reconciliation,
        )

    def _briefing_summary(
        self,
        *,
        helper: LiveCalendarTrialRunner,
        briefing_date: date,
        run_id: str,
        result: PipelineResult,
    ) -> BriefingValidationSummary:
        output_path = helper._write_briefing(
            briefing_date=briefing_date.isoformat(),
            run_id=run_id,
            content=result.rendered.text,
        )
        audit = next(
            (
                item
                for item in result.plan.task_candidate_audits
                if item.source == "todoist"
            ),
            None,
        )
        displayed_sections = tuple(
            section.name.value
            for section in result.plan.sections
            if section.name is not BriefingSectionName.SOURCE_COVERAGE
            and any(
                source.source == "todoist"
                for item in section.items
                for source in item.sources
            )
        )
        coverage = next(
            item for item in result.plan.coverage if item.source == "todoist"
        )
        return BriefingValidationSummary(
            briefing_date=briefing_date,
            output_path=output_path,
            word_count=result.rendered.word_count,
            workday_type=result.plan.context.workday_type.value,
            available_task_count=0 if audit is None else audit.available_count,
            candidate_task_count=0 if audit is None else audit.candidate_count,
            excluded_reasons=() if audit is None else audit.excluded_reasons,
            displayed_task_count=coverage.displayed_count or 0,
            displayed_sections=displayed_sections,
        )


def _with_persistence_coverage(
    *,
    result: PipelineResult,
    persisted_by_source: dict[str, int],
    context_persisted_by_source: dict[str, dict[str, int]] | None = None,
) -> PipelineResult:
    context = result.plan.context
    context_counts = context_persisted_by_source or {}
    coverage = tuple(
        replace(
            report,
            persisted_count=persisted_by_source.get(report.source, 0),
            context_resources=tuple(
                ContextResourceCoverage(
                    resource=resource.resource,
                    retrieved_count=resource.retrieved_count,
                    persisted_count=context_counts.get(report.source, {}).get(
                        resource.resource,
                        0,
                    ),
                )
                for resource in report.context_resources
            ),
        )
        for report in result.plan.coverage
    )
    plan = build_reduced_plan(context, result.deduplication.records, coverage)
    rendered = render_briefing(plan)
    validate_briefing(plan, rendered)
    return replace(result, plan=plan, rendered=rendered)
