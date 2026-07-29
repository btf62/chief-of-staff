"""One bounded input-complete MVP trial with private Gmail review artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
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
    GmailFailureAudit,
    GmailStreamAudit,
    GoogleCalendarConnector,
    JiraConnector,
    RepositoryContextConnector,
    TodoistConnector,
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
class GmailStreamTrialReport:
    """Private-content-free coverage report for one Gmail stream."""

    status: str
    retrieval_window_start: datetime
    retrieval_window_end: datetime
    messages_listed: int
    pages: int
    duplicate_message_ids: int
    metadata_records_inspected: int
    body_candidates: int
    body_candidates_selected: int
    body_candidates_omitted: int
    body_fetches_attempted: int
    body_records_retrieved: int
    bodies_unavailable_or_unsupported: int
    automated_bulk_exclusions: int
    opaque_or_unsupported_messages: int


@dataclass(frozen=True, slots=True)
class GmailMvpTrialReport:
    """Private-content-free aggregate report for the mandatory stop."""

    oauth_project_id: str
    oauth_application_owner: str
    account_confirmed: bool
    granted_scope: str
    credential_health: str
    refresh_health: str | None
    inbound: GmailStreamTrialReport
    sent: GmailStreamTrialReport
    messages_listed: int
    pages: int
    metadata_records_inspected: int
    direct_inbound_candidates: int
    outbound_candidates: int
    automated_bulk_exclusions: int
    body_candidates_eligible: int
    body_candidates_selected: int
    body_candidates_omitted: int
    body_fetches_attempted: int
    body_records_retrieved: int
    bodies_unavailable_or_unsupported: int
    body_candidate_cap_caused_partial_coverage: bool
    extracted_content_limit_caused_partial_coverage: bool
    opaque_or_unsupported_messages: int
    unique_threads: int
    explicit_requests_detected: int
    proposed_people_waiting: int
    proposed_acknowledgment_obligations: int
    proposed_preparation_items: int
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
    retrieval_attempts: int
    failure_report_paths: tuple[Path, ...]
    raw_payload_persisted: bool = False
    complete_body_persisted: bool = False
    attachment_retrieval_used: bool = False
    hosted_inference_used: bool = False
    external_mutation_used: bool = False
    personal_gmail_authorized: bool = False
    google_drive_invoked: bool = False


@dataclass(frozen=True, slots=True)
class GmailMvpTrialFailureReport:
    """Private-content-free aggregate report for a failed bounded trial."""

    failure: GmailFailureAudit
    retrieval_attempts: int
    failure_report_paths: tuple[Path, ...]
    gmail_coverage: str
    source_coverage: tuple[tuple[str, str, int], ...]
    records_persisted: int = 0
    briefing_run_persisted: bool = False
    review_artifact_created: bool = False
    combined_briefing_created: bool = False
    raw_payload_persisted: bool = False
    complete_body_persisted: bool = False
    hosted_inference_used: bool = False
    external_mutation_used: bool = False
    personal_gmail_authorized: bool = False
    google_drive_invoked: bool = False


class GmailMvpTrialFailure(LiveTrialError):
    """Expose a safe aggregate report without persisting failed trial data."""

    def __init__(self, report: GmailMvpTrialFailureReport) -> None:
        super().__init__(
            f"Work Gmail trial stopped: {report.failure.failure_category.value}"
        )
        self.report = report


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
        """Perform one bounded Gmail and input-complete briefing invocation."""

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
        failure_report_paths: list[Path] = []

        def write_failure_report(failure: GmailFailureAudit) -> None:
            failure_report_paths.append(
                _write_private(
                    self.review_directory.parent,
                    (
                        f"{run_id}-failure-attempt-"
                        f"{len(failure_report_paths) + 1:02}.json"
                    ),
                    json.dumps(
                        asdict(failure),
                        default=_json_default,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                )
            )

        prior_window_fallback = self.gmail_connector.allow_window_fallback
        prior_authorization_refresh = self.gmail_connector.allow_authorization_refresh
        prior_transient_attempts = self.gmail_connector.max_transient_attempts
        prior_failure_reporter = self.gmail_connector.failure_reporter
        self.gmail_connector.allow_window_fallback = True
        self.gmail_connector.allow_authorization_refresh = True
        self.gmail_connector.max_transient_attempts = 3
        self.gmail_connector.failure_reporter = write_failure_report
        try:
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
        finally:
            self.gmail_connector.allow_window_fallback = prior_window_fallback
            self.gmail_connector.allow_authorization_refresh = (
                prior_authorization_refresh
            )
            self.gmail_connector.max_transient_attempts = prior_transient_attempts
            self.gmail_connector.failure_reporter = prior_failure_reporter
        completed_at = self.clock()
        coverage_by_source = {
            coverage.source: coverage for coverage in result.plan.coverage
        }
        gmail_coverage = coverage_by_source["gmail"]
        if gmail_coverage.status in {
            CoverageStatus.UNAUTHORIZED,
            CoverageStatus.UNAVAILABLE,
        }:
            failure = self.gmail_connector.last_failure_audit
            if failure is None:
                raise LiveTrialError(
                    "Work Gmail failed without a current diagnostic audit"
                )
            raise GmailMvpTrialFailure(
                GmailMvpTrialFailureReport(
                    failure=failure,
                    retrieval_attempts=self.gmail_connector.last_attempt_count,
                    failure_report_paths=tuple(failure_report_paths),
                    gmail_coverage=gmail_coverage.status.value,
                    source_coverage=tuple(
                        (
                            coverage.account_alias or coverage.source,
                            coverage.status.value,
                            coverage.record_count,
                        )
                        for coverage in result.plan.coverage
                    ),
                    personal_gmail_authorized=(
                        self.state_store.get_connector_authorization("gmail:personal")
                        is not None
                    ),
                )
            )
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
        displayed_gmail_source_ids = {
            source.source_record_id
            for section in result.plan.sections
            for item in section.items
            for source in item.sources
            if source.source == "gmail"
        }
        review_path = self._write_review(
            run_id,
            displayed_source_record_ids=frozenset(displayed_gmail_source_ids),
        )
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
            inbound=_stream_report(audit.inbound),
            sent=_stream_report(audit.sent),
            messages_listed=audit.messages_listed,
            pages=audit.pages,
            metadata_records_inspected=audit.metadata_inspected,
            direct_inbound_candidates=audit.direct_inbound_candidates,
            outbound_candidates=audit.outbound_candidates,
            automated_bulk_exclusions=audit.automated_bulk_exclusions,
            body_candidates_eligible=audit.body_candidates_eligible,
            body_candidates_selected=audit.body_candidates_selected,
            body_candidates_omitted=audit.body_candidates_omitted,
            body_fetches_attempted=audit.body_fetches_attempted,
            body_records_retrieved=audit.body_records_retrieved,
            bodies_unavailable_or_unsupported=(
                audit.body_records_unavailable_or_unsupported
            ),
            body_candidate_cap_caused_partial_coverage=(
                audit.body_candidate_cap_caused_partial_coverage
            ),
            extracted_content_limit_caused_partial_coverage=(
                audit.extracted_content_limit_caused_partial_coverage
            ),
            opaque_or_unsupported_messages=audit.opaque_or_unsupported_messages,
            unique_threads=audit.unique_threads,
            explicit_requests_detected=audit.explicit_requests_detected,
            proposed_people_waiting=audit.people_waiting_proposed,
            proposed_acknowledgment_obligations=(
                audit.acknowledgment_obligations_proposed
            ),
            proposed_preparation_items=audit.preparation_items_proposed,
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
            retrieval_attempts=self.gmail_connector.last_attempt_count,
            failure_report_paths=tuple(failure_report_paths),
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
                        if detection.type
                        in {
                            GmailDetectionType.PEOPLE_WAITING,
                            GmailDetectionType.PREPARATION,
                        }
                        else "outbound"
                    ),
                    occurred_at=detection.detected_at,
                    participant_references=(),
                    subject=None,
                    label_classification=(
                        "direct_inbound"
                        if detection.type
                        in {
                            GmailDetectionType.PEOPLE_WAITING,
                            GmailDetectionType.PREPARATION,
                        }
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
                            else (
                                ConclusionKind.PREPARATION_ITEM
                                if detection.type is GmailDetectionType.PREPARATION
                                else ConclusionKind.COMMITMENT
                            )
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

    def _write_review(
        self,
        run_id: str,
        *,
        displayed_source_record_ids: frozenset[str],
    ) -> Path:
        audit = self.gmail_connector.last_audit
        if audit is None:
            raise LiveTrialError("Work Gmail lifecycle audit is unavailable")
        lines = [
            "# Private Milestone 7 deterministic review",
            "",
            "This local artifact contains authorized private email evidence. "
            "Do not commit or share it.",
            "",
            "## Effective retrieval coverage",
            "",
            (
                f"- Inbound: {audit.inbound.window_start.isoformat()} through "
                f"{audit.inbound.window_end.isoformat()}"
            ),
            (
                f"- Sent: {audit.sent.window_start.isoformat()} through "
                f"{audit.sent.window_end.isoformat()}"
            ),
            "",
            "## Bounded body-candidate coverage",
            "",
            f"- Eligible: {audit.body_candidates_eligible}",
            f"- Selected under the hard cap: {audit.body_candidates_selected}",
            f"- Omitted without body retrieval: {audit.body_candidates_omitted}",
            f"- Body fetches attempted: {audit.body_fetches_attempted}",
            f"- Usable bodies: {audit.body_records_retrieved}",
            (
                "- Bodies unavailable or unsupported: "
                f"{audit.body_records_unavailable_or_unsupported}"
            ),
            (
                "- Candidate-cap partial coverage: "
                f"{audit.body_candidate_cap_caused_partial_coverage}"
            ),
            (
                "- Extracted-content partial coverage: "
                f"{audit.extracted_content_limit_caused_partial_coverage}"
            ),
            (
                "- Inbound eligible / selected / omitted: "
                f"{audit.inbound.body_candidates} / "
                f"{audit.inbound.body_candidates_selected} / "
                f"{audit.inbound.body_candidates_omitted}"
            ),
            (
                "- Sent eligible / selected / omitted: "
                f"{audit.sent.body_candidates} / "
                f"{audit.sent.body_candidates_selected} / "
                f"{audit.sent.body_candidates_omitted}"
            ),
            "",
            "## Source-coverage limitations",
            "",
            (
                "- Work Gmail coverage: "
                + (
                    "partial because the body-candidate cap omitted eligible "
                    "messages without retrieval."
                    if audit.body_candidate_cap_caused_partial_coverage
                    else "complete within the accepted bounded windows."
                )
            ),
            (
                "- Unsupported or unavailable selected bodies: "
                f"{audit.body_records_unavailable_or_unsupported}"
            ),
        ]
        displayed = tuple(
            detection
            for detection in self.gmail_connector.last_proposed_detections
            if detection.message_id in displayed_source_record_ids
        )
        nondisplayed = tuple(
            detection
            for detection in self.gmail_connector.last_proposed_detections
            if detection.message_id not in displayed_source_record_ids
        )
        lines.extend(("", "## Displayed conclusions"))
        if not displayed:
            lines.extend(("", "- None."))
        for detection in displayed:
            lines.extend(
                (
                    "",
                    f"### {detection.type.value}",
                    f"- Classification: {detection.evidence_classification.value}",
                    f"- Proposed conclusion: {detection.statement}",
                    f"- Reason: {detection.explanation}",
                    f"- Source: {detection.display_url}",
                    f"- Minimal evidence: {detection.evidence_excerpt}",
                )
            )
        lines.extend(("", "## Supported but nondisplayed conclusions"))
        if not nondisplayed:
            lines.extend(("", "- None."))
        for detection in nondisplayed:
            lines.extend(
                (
                    "",
                    f"### {detection.type.value}",
                    f"- Classification: {detection.evidence_classification.value}",
                    f"- Proposed conclusion: {detection.statement}",
                    f"- Reason: {detection.explanation}",
                    f"- Source: {detection.display_url}",
                    f"- Minimal evidence: {detection.evidence_excerpt}",
                )
            )

        recurrence_results = tuple(
            rejection
            for rejection in self.gmail_connector.last_rejections
            if rejection.reason.startswith("local disposition ")
        )
        insufficient = tuple(
            rejection
            for rejection in self.gmail_connector.last_rejections
            if rejection not in recurrence_results
        )
        lines.extend(("", "## Insufficient-evidence cases"))
        if not insufficient:
            lines.extend(("", "- None."))
        for rejection in insufficient:
            lines.extend(
                (
                    "",
                    f"- Classification: {rejection.evidence_classification.value}",
                    f"  Reason: {rejection.reason}",
                    f"  Source: {rejection.display_url}",
                )
            )

        lines.extend(("", "## Correction recurrence results"))
        if not recurrence_results:
            lines.extend(
                (
                    "",
                    "- No materially unchanged conclusion was suppressed or "
                    "reworded by local correction state in this run.",
                )
            )
        else:
            for rejection in recurrence_results:
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


def _stream_report(audit: GmailStreamAudit) -> GmailStreamTrialReport:
    return GmailStreamTrialReport(
        status=audit.status,
        retrieval_window_start=audit.window_start,
        retrieval_window_end=audit.window_end,
        messages_listed=audit.messages_listed,
        pages=audit.pages,
        duplicate_message_ids=audit.duplicate_message_ids,
        metadata_records_inspected=audit.metadata_inspected,
        body_candidates=audit.body_candidates,
        body_candidates_selected=audit.body_candidates_selected,
        body_candidates_omitted=audit.body_candidates_omitted,
        body_fetches_attempted=audit.body_fetches_attempted,
        body_records_retrieved=audit.bodies_retrieved,
        bodies_unavailable_or_unsupported=(audit.bodies_unavailable_or_unsupported),
        automated_bulk_exclusions=audit.automated_bulk_exclusions,
        opaque_or_unsupported_messages=audit.opaque_or_unsupported_messages,
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


def _json_default(value: object) -> str:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")
