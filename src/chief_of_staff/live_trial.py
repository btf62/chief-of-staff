"""Bounded live Calendar trial with local-only persistence and safe reporting."""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from chief_of_staff.connectors import (
    GoogleCalendarConnector,
    RepositoryContextConnector,
)
from chief_of_staff.domain import (
    AuthorizationStatus,
    BriefingRun,
    BriefingStatus,
    ConnectorRun,
    ConnectorStatus,
    CoverageStatus,
    CredentialHealth,
    SourceEvidence,
)
from chief_of_staff.persistence import StateStore
from chief_of_staff.pipeline import DeterministicBriefingPipeline, resolve_context


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

        connector_run_ids = self._persist_run_graph(
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            context=context,
            result=result,
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
    ) -> dict[str, str]:
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
        return connector_run_ids

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
