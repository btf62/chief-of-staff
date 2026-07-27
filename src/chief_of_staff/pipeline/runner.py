"""Orchestrate retrieval, normalization, deduplication, and composition."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from chief_of_staff.connectors import (
    ConnectorRequest,
    ReadOnlyConnector,
    SourceCoverage,
)
from chief_of_staff.domain import CoverageStatus
from chief_of_staff.pipeline.briefing import (
    BriefingPlan,
    RenderedBriefing,
    build_reduced_plan,
    render_briefing,
    validate_briefing,
)
from chief_of_staff.pipeline.context import (
    InvocationContext,
    reconcile_calendar_workday_context,
)
from chief_of_staff.pipeline.deduplication import (
    DeduplicationResult,
    deduplicate_records,
)
from chief_of_staff.pipeline.normalization import (
    NormalizedRecord,
    RecordKind,
    normalize_item,
)


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Complete deterministic output with inspectable intermediate state."""

    deduplication: DeduplicationResult
    plan: BriefingPlan
    rendered: RenderedBriefing


class DeterministicBriefingPipeline:
    """Generate a reduced briefing with no probabilistic or external action."""

    def run(
        self,
        context: InvocationContext,
        connectors: tuple[ReadOnlyConnector, ...],
    ) -> PipelineResult:
        """Execute the deterministic pipeline on explicitly supplied connectors."""

        normalized: list[NormalizedRecord] = []
        coverage: list[SourceCoverage] = []
        for connector in connectors:
            request = ConnectorRequest(
                run_id=context.run_id,
                briefing_date=context.briefing_date,
                timezone=context.timezone,
                approved_scope=connector.approved_scope,
                window=context.retrieval_window,
            )
            try:
                result = connector.retrieve(request)
            except Exception as error:
                coverage.append(
                    SourceCoverage(
                        source=connector.source_name,
                        approved_scope=connector.approved_scope,
                        status=CoverageStatus.UNAVAILABLE,
                        retrieved_at=datetime.now(UTC),
                        record_count=0,
                        error_category=type(error).__name__,
                    )
                )
                continue

            if result.coverage.source != connector.source_name:
                raise ValueError(
                    "connector coverage source does not match its identity"
                )
            if result.coverage.record_count != len(result.items):
                raise ValueError("connector coverage record count is inconsistent")
            coverage.append(result.coverage)
            normalized.extend(
                normalize_item(
                    connector.source_name,
                    item,
                    timezone=context.timezone,
                )
                for item in result.items
            )

        deduplication = deduplicate_records(tuple(normalized))
        context = _reconcile_workday_context(context, deduplication.records)
        plan = build_reduced_plan(
            context,
            deduplication.records,
            tuple(coverage),
        )
        coverage_with_display_counts = _coverage_with_display_counts(
            plan,
            tuple(coverage),
        )
        plan = build_reduced_plan(
            context,
            deduplication.records,
            coverage_with_display_counts,
        )
        rendered = render_briefing(plan)
        validate_briefing(plan, rendered)
        return PipelineResult(
            deduplication=deduplication,
            plan=plan,
            rendered=rendered,
        )


def recompose_pipeline_result(
    result: PipelineResult,
    context: InvocationContext,
) -> PipelineResult:
    """Compose another date from an already retrieved normalized snapshot."""

    context = _reconcile_workday_context(context, result.deduplication.records)
    plan = build_reduced_plan(
        context,
        result.deduplication.records,
        result.plan.coverage,
    )
    coverage = _coverage_with_display_counts(plan, result.plan.coverage)
    plan = build_reduced_plan(context, result.deduplication.records, coverage)
    rendered = render_briefing(plan)
    validate_briefing(plan, rendered)
    return replace(result, plan=plan, rendered=rendered)


def _reconcile_workday_context(
    context: InvocationContext,
    records: tuple[NormalizedRecord, ...],
) -> InvocationContext:
    timed = tuple(
        record
        for record in records
        if record.kind is RecordKind.CALENDAR_EVENT
        and (record.status or "").casefold() == "confirmed"
        and (record.event_type or "").casefold()
        not in {"workinglocation", "outofoffice"}
        and not record.all_day
        and record.start_at is not None
        and record.end_at is not None
        and record.start_at.date() == context.briefing_date
    )
    scheduled_minutes = sum(
        max(0, int((record.end_at - record.start_at).total_seconds() // 60))
        for record in timed
        if record.start_at is not None and record.end_at is not None
    )
    return reconcile_calendar_workday_context(
        context,
        fixed_commitment_count=len(timed),
        scheduled_minutes=scheduled_minutes,
    )


def _coverage_with_display_counts(
    plan: BriefingPlan,
    coverage: tuple[SourceCoverage, ...],
) -> tuple[SourceCoverage, ...]:
    displayed_records = {
        (source.source, source.source_record_id)
        for section in plan.sections
        if section.name.value != "Source Coverage"
        for item in section.items
        for source in item.sources
    }
    displayed = {
        source: sum(item_source == source for item_source, _ in displayed_records)
        for source in {item_source for item_source, _ in displayed_records}
    }
    candidates = {
        audit.source: audit.candidate_count for audit in plan.task_candidate_audits
    }
    return tuple(
        replace(
            report,
            retrieved_count=(
                report.record_count
                if report.retrieved_count is None
                else report.retrieved_count
            ),
            selected_count=(
                report.record_count
                if report.selected_count is None
                else report.selected_count
            ),
            candidate_count=candidates.get(report.source, 0),
            displayed_count=displayed.get(report.source, 0),
        )
        for report in coverage
    )
