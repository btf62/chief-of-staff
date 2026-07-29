"""One bounded input-complete MVP trial with private Gmail review artifacts."""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from chief_of_staff.connectors import (
    GMAIL_PROCESSING_VERSION,
    GMAIL_READONLY_SCOPE,
    GMAIL_WORK_ALIAS,
    GMAIL_WORK_INSTANCE,
    GOOGLE_CALENDAR_PRIMARY_INSTANCE,
    JIRA_PRIMARY_INSTANCE,
    TODOIST_PRIMARY_INSTANCE,
    ConnectorInstance,
    ConnectorInstanceIdentity,
    GmailConnector,
    GmailDetectionType,
    GoogleCalendarConnector,
    JiraConnector,
    RepositoryContextConnector,
    TodoistConnector,
    gmail_bounded_query,
)
from chief_of_staff.domain import (
    Classification,
    Conclusion,
    ConclusionKind,
    ConnectorDomain,
    CoverageStatus,
    NormalizedGmailMessage,
)
from chief_of_staff.live_trial import (
    LiveCalendarTrialRunner,
    LiveJiraIssueTrialRunner,
    LiveTodoistTrialRunner,
    LiveTrialError,
    _with_persistence_coverage,
)
from chief_of_staff.persistence import StateStore
from chief_of_staff.pipeline import (
    BriefingSectionName,
    DeterministicBriefingPipeline,
    resolve_context,
)


@dataclass(frozen=True, slots=True)
class GmailMvpTrialReport:
    """Private-content-free aggregate report for the mandatory stop."""

    oauth_project_id: str
    oauth_application_owner: str
    account_confirmed: bool
    granted_scope: str
    credential_health: str
    refresh_health: str | None
    retrieval_window_start: datetime
    retrieval_window_end: datetime
    messages_listed: int
    pages: int
    metadata_records_inspected: int
    direct_inbound_candidates: int
    outbound_candidates: int
    automated_bulk_exclusions: int
    body_records_retrieved: int
    opaque_or_unsupported_messages: int
    unique_threads: int
    explicit_requests_detected: int
    proposed_people_waiting: int
    explicit_sent_commitments_detected: int
    proposed_commitments_at_risk: int
    records_persisted: int
    records_displayed: int
    gmail_coverage: str
    source_coverage: tuple[tuple[str, str, int], ...]
    review_path: Path
    briefing_path: Path
    briefing_word_count: int
    displayed_sections: tuple[str, ...]
    raw_payload_persisted: bool = False
    complete_body_persisted: bool = False
    attachment_retrieval_used: bool = False
    hosted_inference_used: bool = False
    external_mutation_used: bool = False
    personal_gmail_authorized: bool = False
    google_drive_invoked: bool = False


@dataclass(frozen=True, slots=True)
class GmailMvpTrialRunner:
    """Retrieve the five approved input sources once and stop."""

    state_store: StateStore
    repository_root: Path
    repository_paths: tuple[Path, ...]
    calendar_connector: GoogleCalendarConnector
    todoist_connector: TodoistConnector
    jira_connector: JiraConnector
    gmail_connector: GmailConnector
    briefing_directory: Path
    review_directory: Path
    briefing_date_override: date | None = None
    timezone: str = "America/New_York"
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def run(self) -> GmailMvpTrialReport:
        """Perform exactly one bounded Gmail and input-complete briefing trial."""

        started_at = self.clock()
        briefing_date = (
            self.briefing_date_override
            or started_at.astimezone(ZoneInfo(self.timezone)).date()
        )
        run_id = f"live-gmail-mvp-{uuid.uuid4().hex}"
        context = resolve_context(
            run_id=run_id,
            briefing_date=briefing_date,
            timezone=self.timezone,
            invocation_mode="bounded_work_gmail_mvp_trial",
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
                _instance(
                    GOOGLE_CALENDAR_PRIMARY_INSTANCE,
                    "Primary Calendar",
                    "google_calendar",
                    self.calendar_connector,
                ),
                _instance(
                    TODOIST_PRIMARY_INSTANCE,
                    "Todoist",
                    "todoist",
                    self.todoist_connector,
                ),
                _instance(
                    JIRA_PRIMARY_INSTANCE,
                    "NRC Jira",
                    "jira",
                    self.jira_connector,
                ),
                _instance(
                    GMAIL_WORK_INSTANCE,
                    GMAIL_WORK_ALIAS,
                    "gmail",
                    self.gmail_connector,
                ),
            ),
        )
        completed_at = self.clock()
        coverage_by_source = {
            coverage.source: coverage for coverage in result.plan.coverage
        }
        for source in ("google_calendar", "todoist", "jira", "gmail"):
            coverage = coverage_by_source[source]
            if coverage.status is CoverageStatus.UNAUTHORIZED:
                raise LiveTrialError(f"{source} authorization failed")
            if coverage.status is CoverageStatus.UNAVAILABLE:
                raise LiveTrialError(f"{source} retrieval was unavailable")

        audit = self.gmail_connector.last_audit
        if audit is None:
            raise LiveTrialError("Work Gmail lifecycle audit is unavailable")
        client = self.state_store.get_oauth_client(GMAIL_WORK_INSTANCE)
        authorization = self.state_store.get_connector_authorization(
            GMAIL_WORK_INSTANCE
        )
        if client is None or authorization is None:
            raise LiveTrialError("Work Gmail authorization metadata is missing")
        if authorization.granted_scope != GMAIL_READONLY_SCOPE:
            raise LiveTrialError("Work Gmail authorization scope is not exact")

        persistence_helper = LiveCalendarTrialRunner(
            state_store=self.state_store,
            repository_root=self.repository_root,
            repository_paths=self.repository_paths,
            calendar_connector=self.calendar_connector,
            output_directory=self.briefing_directory,
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
            output_directory=self.briefing_directory,
            timezone=self.timezone,
            clock=self.clock,
        )._persist_todoist_tasks(
            evidence_ids=evidence_ids,
            timezone=context.timezone,
            prune_stale=(
                coverage_by_source["todoist"].status is CoverageStatus.COMPLETE
            ),
        )
        jira_runner = LiveJiraIssueTrialRunner(
            state_store=self.state_store,
            repository_root=self.repository_root,
            repository_paths=self.repository_paths,
            calendar_connector=self.calendar_connector,
            todoist_connector=self.todoist_connector,
            jira_connector=self.jira_connector,
            output_directory=self.briefing_directory,
            timezone=self.timezone,
            clock=self.clock,
        )
        jira_runner._persist_jira_issues(
            evidence_ids=evidence_ids,
            prune_stale=coverage_by_source["jira"].status is CoverageStatus.COMPLETE,
        )
        gmail_persisted = self._persist_gmail(
            evidence_ids=evidence_ids,
            run_id=run_id,
            created_at=completed_at,
        )
        persisted_by_source = {
            source: sum(
                evidence_source == source
                for evidence_source, _instance_id, _record_id in evidence_ids
            )
            for source in coverage_by_source
        }
        result = _with_persistence_coverage(
            result=result,
            persisted_by_source=persisted_by_source,
            context_persisted_by_source={
                "todoist": {
                    "projects": todoist_persistence.projects_persisted,
                    "sections": todoist_persistence.sections_persisted,
                    "labels": todoist_persistence.labels_persisted,
                }
            },
        )
        review_path = self._write_review(run_id)
        briefing_path = persistence_helper._write_briefing(
            briefing_date=briefing_date.isoformat(),
            run_id=run_id,
            content=result.rendered.text,
        )
        for connector_id in (
            GOOGLE_CALENDAR_PRIMARY_INSTANCE,
            TODOIST_PRIMARY_INSTANCE,
            JIRA_PRIMARY_INSTANCE,
            GMAIL_WORK_INSTANCE,
        ):
            self.state_store.mark_connector_authorization_used(
                connector_id,
                used_at=completed_at,
            )

        gmail_coverage = coverage_by_source["gmail"]
        _query, gmail_window_start, gmail_window_end = gmail_bounded_query(
            briefing_date,
            self.timezone,
        )
        displayed_sections = tuple(
            section.name.value
            for section in result.plan.sections
            if section.name is not BriefingSectionName.SOURCE_COVERAGE
        )
        return GmailMvpTrialReport(
            oauth_project_id=client.oauth_project_id,
            oauth_application_owner=client.application_owner or "unspecified",
            account_confirmed=True,
            granted_scope=authorization.granted_scope,
            credential_health=authorization.credential_health.value,
            refresh_health=(
                None
                if authorization.refresh_health is None
                else authorization.refresh_health.value
            ),
            retrieval_window_start=gmail_window_start,
            retrieval_window_end=gmail_window_end,
            messages_listed=audit.messages_listed,
            pages=audit.pages,
            metadata_records_inspected=audit.metadata_inspected,
            direct_inbound_candidates=audit.direct_inbound_candidates,
            outbound_candidates=audit.outbound_candidates,
            automated_bulk_exclusions=audit.automated_bulk_exclusions,
            body_records_retrieved=audit.body_records_retrieved,
            opaque_or_unsupported_messages=audit.opaque_or_unsupported_messages,
            unique_threads=audit.unique_threads,
            explicit_requests_detected=audit.explicit_requests_detected,
            proposed_people_waiting=audit.people_waiting_proposed,
            explicit_sent_commitments_detected=audit.explicit_commitments_detected,
            proposed_commitments_at_risk=audit.commitments_at_risk_proposed,
            records_persisted=gmail_persisted,
            records_displayed=gmail_coverage.displayed_count or 0,
            gmail_coverage=gmail_coverage.status.value,
            source_coverage=tuple(
                (
                    coverage.account_alias or coverage.source,
                    coverage.status.value,
                    coverage.record_count,
                )
                for coverage in result.plan.coverage
            ),
            review_path=review_path,
            briefing_path=briefing_path,
            briefing_word_count=result.rendered.word_count,
            displayed_sections=displayed_sections,
            personal_gmail_authorized=(
                self.state_store.get_connector_authorization("gmail:personal")
                is not None
            ),
        )

    def _persist_gmail(
        self,
        *,
        evidence_ids: dict[tuple[str, str | None, str], str],
        run_id: str,
        created_at: datetime,
    ) -> int:
        persisted = 0
        for detection in self.gmail_connector.last_proposed_detections:
            evidence_id = evidence_ids.get(
                ("gmail", GMAIL_WORK_INSTANCE, detection.message_id)
            )
            if evidence_id is None:
                continue
            self.state_store.update_source_evidence_excerpt(
                evidence_id,
                detection.evidence_excerpt,
            )
            self.state_store.add_normalized_gmail_message(
                NormalizedGmailMessage(
                    evidence_id=evidence_id,
                    thread_id=detection.thread_id,
                    direction=(
                        "direct_inbound"
                        if detection.type is GmailDetectionType.PEOPLE_WAITING
                        else "outbound"
                    ),
                    occurred_at=detection.detected_at,
                    participant_references=(),
                    subject=None,
                    label_classification=(
                        "direct_inbound"
                        if detection.type is GmailDetectionType.PEOPLE_WAITING
                        else "outbound"
                    ),
                    detection_type=detection.type.value,
                    processing_version=GMAIL_PROCESSING_VERSION,
                )
            )
            decision = self.state_store.recurrence_decision(
                detection.evidence_fingerprint
            )
            if decision.prior_conclusion_id is None:
                self.state_store.add_conclusion(
                    Conclusion(
                        id=(
                            f"{run_id}:gmail-conclusion:"
                            f"{hashlib.sha256(detection.evidence_fingerprint.encode()).hexdigest()[:20]}"
                        ),
                        kind=(
                            ConclusionKind.WAITING_ITEM
                            if detection.type is GmailDetectionType.PEOPLE_WAITING
                            else ConclusionKind.COMMITMENT
                        ),
                        classification=Classification.EXPLICIT,
                        statement=detection.statement,
                        explanation=detection.explanation,
                        confidence=1.0,
                        evidence_fingerprint=detection.evidence_fingerprint,
                        processing_version=GMAIL_PROCESSING_VERSION,
                        created_at=created_at,
                        evidence_ids=(evidence_id,),
                    )
                )
            persisted += 1
        return persisted

    def _write_review(self, run_id: str) -> Path:
        lines = [
            "# Private Work Gmail candidate review",
            "",
            "This local artifact contains authorized private email evidence. "
            "Do not commit or share it.",
        ]
        for detection in self.gmail_connector.last_proposed_detections:
            lines.extend(
                (
                    "",
                    f"## {detection.type.value}",
                    "",
                    f"- Proposed conclusion: {detection.statement}",
                    f"- Reason: {detection.explanation}",
                    f"- Source: {detection.display_url}",
                    f"- Minimal evidence: {detection.evidence_excerpt}",
                )
            )
        if self.gmail_connector.last_rejections:
            lines.extend(("", "## Bounded rejected sample"))
            for rejection in self.gmail_connector.last_rejections:
                lines.extend(
                    (
                        "",
                        f"- Reason: {rejection.reason}",
                        f"  Source: {rejection.display_url}",
                    )
                )
        return _write_private(
            self.review_directory,
            f"{run_id}.md",
            "\n".join(lines).rstrip() + "\n",
        )


def _instance(
    instance_id: str,
    alias: str,
    provider: str,
    connector: object,
) -> ConnectorInstance:
    from chief_of_staff.connectors import ReadOnlyConnector

    if not isinstance(connector, ReadOnlyConnector):
        raise TypeError("connector instance received an invalid connector")
    return ConnectorInstance(
        identity=ConnectorInstanceIdentity(
            id=instance_id,
            provider=provider,
            alias=alias,
            domain_classification=ConnectorDomain.WORK,
        ),
        connector=connector,
    )


def _write_private(directory: Path, name: str, content: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    path = directory / name
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)
    return path
