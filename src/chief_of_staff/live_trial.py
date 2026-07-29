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
    GMAIL_WORK_INSTANCE,
    GOOGLE_CALENDAR_PRIMARY_INSTANCE,
    JIRA_PRIMARY_INSTANCE,
    TODOIST_PRIMARY_INSTANCE,
    ContextResourceCoverage,
    GoogleCalendarConnector,
    JiraConnector,
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
    NormalizedJiraIssue,
    NormalizedJiraIssueLink,
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
                    for evidence_source, _instance_id, _source_record_id in evidence_ids
                )
                for source, _instance_id in connector_run_ids
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
    ) -> tuple[
        dict[tuple[str, str | None], str],
        dict[tuple[str, str | None, str], str],
    ]:
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
        connector_run_ids: dict[tuple[str, str | None], str] = {}
        for coverage in result.plan.coverage:
            connector_instance_id = (
                coverage.connector_instance_id
                or _default_connector_instance_id(coverage.source)
            )
            connector_run_id = f"{run_id}:{connector_instance_id or coverage.source}"
            connector_run_ids[(coverage.source, connector_instance_id)] = (
                connector_run_id
            )
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
                    connector_instance_id=connector_instance_id,
                )
            )
            self.state_store.link_connector_run(run_id, connector_run_id)

        evidence_ids: dict[tuple[str, str | None, str], str] = {}
        for record in result.deduplication.records:
            source = record.provenance.source
            connector_instance_id = (
                record.provenance.connector_instance_id
                or _default_connector_instance_id(source)
            )
            fingerprint = _evidence_fingerprint(
                source=source,
                source_record_id=record.provenance.source_record_id,
                freshness_at=record.provenance.freshness_at,
                connector_instance_id=connector_instance_id,
            )
            evidence_id = f"{run_id}:evidence:{hashlib.sha256(fingerprint.encode()).hexdigest()[:20]}"
            self.state_store.add_source_evidence(
                SourceEvidence(
                    id=evidence_id,
                    connector_run_id=connector_run_ids[(source, connector_instance_id)],
                    source=source,
                    source_record_id=record.provenance.source_record_id,
                    display_url=record.provenance.display_url,
                    excerpt=None,
                    evidence_fingerprint=fingerprint,
                    retrieved_at=record.provenance.retrieved_at,
                    freshness_at=record.provenance.freshness_at,
                    connector_instance_id=connector_instance_id,
                )
            )
            evidence_ids[
                (
                    source,
                    connector_instance_id,
                    record.provenance.source_record_id,
                )
            ] = evidence_id
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
    connector_instance_id: str | None,
) -> str:
    freshness = "" if freshness_at is None else freshness_at.isoformat()
    material = (
        f"{source}\0{connector_instance_id or ''}\0{source_record_id}\0{freshness}"
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _default_connector_instance_id(source: str) -> str | None:
    return {
        "google_calendar": GOOGLE_CALENDAR_PRIMARY_INSTANCE,
        "todoist": TODOIST_PRIMARY_INSTANCE,
        "jira": JIRA_PRIMARY_INSTANCE,
        "gmail": GMAIL_WORK_INSTANCE,
    }.get(source)


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
                    for evidence_source, _instance_id, _source_record_id in evidence_ids
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
        evidence_ids: dict[tuple[str, str | None, str], str],
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
            evidence_id = evidence_ids.get(
                ("todoist", TODOIST_PRIMARY_INSTANCE, task.id)
            )
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
            task.id: evidence_ids[("todoist", TODOIST_PRIMARY_INSTANCE, task.id)]
            for task in audit.selected_tasks
            if ("todoist", TODOIST_PRIMARY_INSTANCE, task.id) in evidence_ids
        }
        reconciliation = (
            self.state_store.reconcile_source_task_snapshot(
                source="todoist",
                current_evidence_ids=current_evidence_ids,
                connector_instance_id=TODOIST_PRIMARY_INSTANCE,
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


@dataclass(frozen=True, slots=True)
class JiraIssuePersistenceResult:
    """Privacy-safe Jira snapshot persistence and reconciliation counts."""

    issues_persisted: int
    labels_persisted: int
    links_persisted: int
    reconciliation: SourceTaskReconciliation


@dataclass(frozen=True, slots=True)
class LiveJiraIssueTrialReport:
    """Private-content-free facts from the one approved Jira issue trial."""

    oauth_application_name: str
    oauth_application_owner: str
    account_identity: str
    account_identity_source: str
    site_url: str
    approved_project: str
    granted_scope: str
    credential_health: str
    endpoint: str
    jql_shape: str
    requested_fields: tuple[str, ...]
    issue_page_count: int
    total_issue_count: int
    duplicate_issue_id_count: int
    selected_issue_count: int
    persisted_issue_count: int
    newly_persisted_issue_count: int
    retained_issue_count: int
    removed_issue_count: int
    dependency_preserved_issue_count: int
    superseded_snapshot_count_removed: int
    daily_candidate_count: int
    displayed_issue_count: int
    due_state_counts: tuple[tuple[str, int], ...]
    status_category_counts: tuple[tuple[str, int], ...]
    issues_with_parent_count: int
    issues_with_labels_count: int
    issues_with_links_count: int
    label_reference_count: int
    link_reference_count: int
    retrieval_status: str
    pagination_occurred: bool
    concurrent_changes_cannot_be_excluded: bool
    raw_payload_persisted: bool
    cursor_persisted: bool
    description_persisted: bool
    refresh_token_requested: bool
    hosted_inference_used: bool
    external_mutation_used: bool
    briefing: BriefingValidationSummary


@dataclass(frozen=True, slots=True)
class LiveJiraIssueTrialRunner:
    """Run one repository, Calendar, Todoist, and bounded Jira briefing."""

    state_store: StateStore
    repository_root: Path
    repository_paths: tuple[Path, ...]
    calendar_connector: GoogleCalendarConnector
    todoist_connector: TodoistConnector
    jira_connector: JiraConnector
    output_directory: Path
    briefing_date_override: date | None = None
    timezone: str = "America/New_York"
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def run(self) -> LiveJiraIssueTrialReport:
        """Retrieve each approved source once and persist only minimized facts."""

        started_at = self.clock()
        briefing_date = (
            self.briefing_date_override
            or started_at.astimezone(ZoneInfo(self.timezone)).date()
        )
        run_id = f"live-jira-{uuid.uuid4().hex}"
        context = resolve_context(
            run_id=run_id,
            briefing_date=briefing_date,
            timezone=self.timezone,
            invocation_mode="bounded_jira_issue_live_trial",
            lookahead_days=7,
        )
        result = DeterministicBriefingPipeline().run(
            context,
            (
                RepositoryContextConnector(
                    root=self.repository_root,
                    approved_paths=self.repository_paths,
                    clock=self.clock,
                ),
                self.calendar_connector,
                self.todoist_connector,
                self.jira_connector,
            ),
        )
        completed_at = self.clock()
        coverage_by_source = {
            coverage.source: coverage for coverage in result.plan.coverage
        }
        for source in ("google_calendar", "todoist", "jira"):
            coverage = coverage_by_source[source]
            if coverage.status is CoverageStatus.UNAUTHORIZED:
                raise LiveTrialError(f"{source} authorization failed")
            if coverage.status is CoverageStatus.UNAVAILABLE:
                raise LiveTrialError(f"{source} retrieval was unavailable")

        jira_audit = self.jira_connector.last_audit
        todoist_audit = self.todoist_connector.last_audit
        if jira_audit is None or todoist_audit is None:
            raise LiveTrialError("live source lifecycle audit is unavailable")
        client = self.state_store.get_oauth_client("jira")
        authorization = self.state_store.get_connector_authorization("jira")
        resource = self.state_store.get_connector_resource("jira")
        if client is None or authorization is None or resource is None:
            raise LiveTrialError("Jira authorization metadata is missing")

        persistence_helper = LiveCalendarTrialRunner(
            state_store=self.state_store,
            repository_root=self.repository_root,
            repository_paths=self.repository_paths,
            calendar_connector=self.calendar_connector,
            output_directory=self.output_directory,
            timezone=self.timezone,
            clock=self.clock,
        )
        _connector_run_ids, evidence_ids = persistence_helper._persist_run_graph(
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            context=context,
            result=result,
        )
        todoist_persistence = LiveTodoistTrialRunner(
            state_store=self.state_store,
            repository_root=self.repository_root,
            repository_paths=self.repository_paths,
            calendar_connector=self.calendar_connector,
            todoist_connector=self.todoist_connector,
            output_directory=self.output_directory,
            timezone=self.timezone,
            clock=self.clock,
        )._persist_todoist_tasks(
            evidence_ids=evidence_ids,
            timezone=context.timezone,
            prune_stale=(
                coverage_by_source["todoist"].status is CoverageStatus.COMPLETE
            ),
        )
        jira_persistence = self._persist_jira_issues(
            evidence_ids=evidence_ids,
            prune_stale=coverage_by_source["jira"].status is CoverageStatus.COMPLETE,
        )
        result = _with_persistence_coverage(
            result=result,
            persisted_by_source={
                source: sum(
                    evidence_source == source
                    for evidence_source, _instance_id, _source_record_id in evidence_ids
                )
                for source in coverage_by_source
            },
            context_persisted_by_source={
                "todoist": {
                    "projects": todoist_persistence.projects_persisted,
                    "sections": todoist_persistence.sections_persisted,
                    "labels": todoist_persistence.labels_persisted,
                }
            },
        )
        briefing = LiveTodoistTrialRunner(
            state_store=self.state_store,
            repository_root=self.repository_root,
            repository_paths=self.repository_paths,
            calendar_connector=self.calendar_connector,
            todoist_connector=self.todoist_connector,
            output_directory=self.output_directory,
            timezone=self.timezone,
            clock=self.clock,
        )._briefing_summary(
            helper=persistence_helper,
            briefing_date=briefing_date,
            run_id=run_id,
            result=result,
        )
        for connector in ("google_calendar", "todoist", "jira"):
            self.state_store.mark_connector_authorization_used(
                connector,
                used_at=completed_at,
            )

        selected = jira_audit.selected_issues
        jira_candidate_audit = next(
            (
                audit
                for audit in result.plan.task_candidate_audits
                if audit.source == "jira"
            ),
            None,
        )
        jira_coverage = coverage_by_source["jira"]
        return LiveJiraIssueTrialReport(
            oauth_application_name=client.oauth_project_id,
            oauth_application_owner=client.application_owner or "unspecified",
            account_identity=authorization.account_identity,
            account_identity_source="user-confirmed",
            site_url=resource.resource_url,
            approved_project="NRC",
            granted_scope=authorization.granted_scope,
            credential_health=authorization.credential_health.value,
            endpoint="POST /rest/api/3/search/jql",
            jql_shape=(
                "project = NRC AND statusCategory != Done AND "
                "assignee = currentUser() ORDER BY updated DESC, key ASC"
            ),
            requested_fields=(
                "summary",
                "project",
                "issuetype",
                "status",
                "assignee",
                "priority",
                "duedate",
                "created",
                "updated",
                "parent",
                "labels",
                "issuelinks",
            ),
            issue_page_count=jira_audit.page_count,
            total_issue_count=jira_audit.retrieved_count,
            duplicate_issue_id_count=jira_audit.duplicate_issue_count,
            selected_issue_count=jira_audit.selected_count,
            persisted_issue_count=(jira_persistence.reconciliation.final_unique_count),
            newly_persisted_issue_count=(
                jira_persistence.reconciliation.newly_selected_count
            ),
            retained_issue_count=jira_persistence.reconciliation.retained_count,
            removed_issue_count=jira_persistence.reconciliation.removed_count,
            dependency_preserved_issue_count=(
                jira_persistence.reconciliation.dependency_preserved_count
            ),
            superseded_snapshot_count_removed=(
                jira_persistence.reconciliation.superseded_snapshot_count
            ),
            daily_candidate_count=(
                0
                if jira_candidate_audit is None
                else jira_candidate_audit.candidate_count
            ),
            displayed_issue_count=jira_coverage.displayed_count or 0,
            due_state_counts=_jira_due_state_counts(selected, briefing_date),
            status_category_counts=_jira_status_category_counts(selected),
            issues_with_parent_count=sum(
                issue.parent_key is not None for issue in selected
            ),
            issues_with_labels_count=sum(bool(issue.labels) for issue in selected),
            issues_with_links_count=sum(bool(issue.links) for issue in selected),
            label_reference_count=jira_persistence.labels_persisted,
            link_reference_count=jira_persistence.links_persisted,
            retrieval_status=jira_coverage.status.value,
            pagination_occurred=jira_audit.pagination_occurred,
            concurrent_changes_cannot_be_excluded=True,
            raw_payload_persisted=False,
            cursor_persisted=False,
            description_persisted=False,
            refresh_token_requested=False,
            hosted_inference_used=False,
            external_mutation_used=False,
            briefing=briefing,
        )

    def _persist_jira_issues(
        self,
        *,
        evidence_ids: dict[tuple[str, str | None, str], str],
        prune_stale: bool,
    ) -> JiraIssuePersistenceResult:
        audit = self.jira_connector.last_audit
        if audit is None:
            raise LiveTrialError("Jira lifecycle audit is unavailable")
        persisted = 0
        label_count = 0
        link_count = 0
        current_evidence_ids: dict[str, str] = {}
        for issue in audit.selected_issues:
            evidence_id = evidence_ids.get(("jira", JIRA_PRIMARY_INSTANCE, issue.key))
            if (
                evidence_id is None
                or issue.assignee_account_id is None
                or issue.created_at is None
                or issue.updated_at is None
            ):
                continue
            self.state_store.add_normalized_jira_issue(
                NormalizedJiraIssue(
                    evidence_id=evidence_id,
                    issue_key=issue.key,
                    summary=issue.summary,
                    project_key=issue.project_key,
                    issue_type=issue.issue_type,
                    status=issue.status,
                    status_category=issue.status_category,
                    assignee_account_id=issue.assignee_account_id,
                    priority_name=issue.priority_name,
                    due_date=issue.due_date,
                    created_at=issue.created_at,
                    updated_at=issue.updated_at,
                    parent_key=issue.parent_key,
                    labels=issue.labels,
                    links=tuple(
                        NormalizedJiraIssueLink(
                            relationship=link.relationship,
                            issue_id=link.issue_id,
                            issue_key=link.issue_key,
                            display_url=link.display_url,
                        )
                        for link in issue.links
                    ),
                )
            )
            persisted += 1
            label_count += len(issue.labels)
            link_count += len(issue.links)
            current_evidence_ids[issue.key] = evidence_id
        reconciliation = (
            self.state_store.reconcile_jira_issue_snapshot(
                current_evidence_ids=current_evidence_ids,
                connector_instance_id=JIRA_PRIMARY_INSTANCE,
            )
            if prune_stale
            else SourceTaskReconciliation(
                previous_unique_count=0,
                final_unique_count=persisted,
                newly_selected_count=persisted,
                retained_count=0,
                removed_count=0,
                superseded_snapshot_count=0,
                dependency_preserved_count=0,
            )
        )
        return JiraIssuePersistenceResult(
            issues_persisted=persisted,
            labels_persisted=label_count,
            links_persisted=link_count,
            reconciliation=reconciliation,
        )


def _jira_due_state_counts(
    issues: tuple[object, ...],
    briefing_date: date,
) -> tuple[tuple[str, int], ...]:
    from chief_of_staff.connectors import JiraIssue

    typed = tuple(issue for issue in issues if isinstance(issue, JiraIssue))
    counts = {
        "no_due_date": 0,
        "overdue": 0,
        "due_today": 0,
        "due_next_7_days": 0,
        "due_later": 0,
    }
    for issue in typed:
        if issue.due_date is None:
            counts["no_due_date"] += 1
        elif issue.due_date < briefing_date:
            counts["overdue"] += 1
        elif issue.due_date == briefing_date:
            counts["due_today"] += 1
        elif issue.due_date <= briefing_date + timedelta(days=7):
            counts["due_next_7_days"] += 1
        else:
            counts["due_later"] += 1
    return tuple(counts.items())


def _jira_status_category_counts(
    issues: tuple[object, ...],
) -> tuple[tuple[str, int], ...]:
    from chief_of_staff.connectors import JiraIssue

    counts: dict[str, int] = {}
    for issue in issues:
        if not isinstance(issue, JiraIssue):
            continue
        category = issue.status_category.casefold().replace(" ", "_")
        counts[category] = counts.get(category, 0) + 1
    return tuple(sorted(counts.items()))


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
