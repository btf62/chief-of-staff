"""Orchestrate retrieval, normalization, deduplication, and composition."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from chief_of_staff.connectors import (
    ConnectorInstance,
    ConnectorRequest,
    GmailAuthenticationError,
    GmailError,
    ReadOnlyConnector,
    SourceCoverage,
    connector_instance_key,
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
            instance = (
                connector.identity if isinstance(connector, ConnectorInstance) else None
            )
            request = ConnectorRequest(
                run_id=context.run_id,
                briefing_date=context.briefing_date,
                timezone=context.timezone,
                approved_scope=connector.approved_scope,
                window=context.retrieval_window,
            )
            try:
                result = connector.retrieve(request)
            except GmailAuthenticationError as error:
                coverage.append(
                    SourceCoverage(
                        source=connector.source_name,
                        approved_scope=connector.approved_scope,
                        status=CoverageStatus.UNAUTHORIZED,
                        retrieved_at=datetime.now(UTC),
                        record_count=0,
                        error_category=error.category.value,
                        connector_instance_id=(
                            None if instance is None else instance.id
                        ),
                        account_alias=None if instance is None else instance.alias,
                        domain_classification=(
                            None if instance is None else instance.domain_classification
                        ),
                    )
                )
                continue
            except GmailError as error:
                coverage.append(
                    SourceCoverage(
                        source=connector.source_name,
                        approved_scope=connector.approved_scope,
                        status=CoverageStatus.UNAVAILABLE,
                        retrieved_at=datetime.now(UTC),
                        record_count=0,
                        error_category=error.category.value,
                        connector_instance_id=(
                            None if instance is None else instance.id
                        ),
                        account_alias=None if instance is None else instance.alias,
                        domain_classification=(
                            None if instance is None else instance.domain_classification
                        ),
                    )
                )
                continue
            except Exception as error:
                coverage.append(
                    SourceCoverage(
                        source=connector.source_name,
                        approved_scope=connector.approved_scope,
                        status=CoverageStatus.UNAVAILABLE,
                        retrieved_at=datetime.now(UTC),
                        record_count=0,
                        error_category=type(error).__name__,
                        connector_instance_id=(
                            None if instance is None else instance.id
                        ),
                        account_alias=None if instance is None else instance.alias,
                        domain_classification=(
                            None if instance is None else instance.domain_classification
                        ),
                    )
                )
                continue

            if result.coverage.source != connector.source_name:
                raise ValueError(
                    "connector coverage source does not match its identity"
                )
            if result.coverage.record_count != len(result.items):
                raise ValueError("connector coverage record count is inconsistent")
            if instance is not None:
                if result.coverage.connector_instance_id != instance.id:
                    raise ValueError(
                        "connector coverage instance does not match its identity"
                    )
                if any(
                    item.connector_instance_id != instance.id for item in result.items
                ):
                    raise ValueError(
                        "connector item instance does not match its identity"
                    )
            coverage.append(result.coverage)
            normalized.extend(
                normalize_item(
                    connector.source_name,
                    item,
                    timezone=context.timezone,
                )
                for item in result.items
            )

        associated = _associate_explicit_cross_source_records(tuple(normalized))
        deduplication = deduplicate_records(associated)
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
        (
            source.source,
            source.connector_instance_id,
            source.source_record_id,
        )
        for section in plan.sections
        if section.name.value != "Source Coverage"
        for item in section.items
        for source in item.sources
    }
    displayed: dict[tuple[str, str], int] = {}
    for source, instance_id, _ in displayed_records:
        key = connector_instance_key(
            source=source,
            connector_instance_id=instance_id,
        )
        displayed[key] = displayed.get(key, 0) + 1
    candidates = {
        connector_instance_key(
            source=audit.source,
            connector_instance_id=audit.connector_instance_id,
        ): audit.candidate_count
        for audit in plan.task_candidate_audits
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
            candidate_count=candidates.get(
                connector_instance_key(
                    source=report.source,
                    connector_instance_id=report.connector_instance_id,
                ),
                0,
            ),
            displayed_count=displayed.get(
                connector_instance_key(
                    source=report.source,
                    connector_instance_id=report.connector_instance_id,
                ),
                0,
            ),
        )
        for report in coverage
    )


def _associate_explicit_cross_source_records(
    records: tuple[NormalizedRecord, ...],
) -> tuple[NormalizedRecord, ...]:
    """Associate only explicit stable cross-references without merging records."""

    jira_by_key = {
        record.provenance.source_record_id: record
        for record in records
        if record.provenance.source == "jira" and record.kind is RecordKind.TASK
    }
    related_ids = {record.id: set(record.related_source_ids) for record in records}
    for record in records:
        if record.provenance.source != "todoist" or record.kind is not RecordKind.TASK:
            continue
        for key, jira_record in jira_by_key.items():
            pattern = rf"(?<![A-Z0-9_]){re.escape(key)}(?![A-Z0-9_])"
            if re.search(pattern, record.title, flags=re.IGNORECASE) is None:
                continue
            related_ids[record.id].add(jira_record.id)
            related_ids[jira_record.id].add(record.id)

    by_id = {record.id: record for record in records}
    associated: list[NormalizedRecord] = []
    for record in records:
        linked = tuple(
            by_id[related_id]
            for related_id in sorted(related_ids[record.id])
            if related_id in by_id
            and connector_instance_key(
                source=by_id[related_id].provenance.source,
                connector_instance_id=(
                    by_id[related_id].provenance.connector_instance_id
                ),
            )
            != connector_instance_key(
                source=record.provenance.source,
                connector_instance_id=record.provenance.connector_instance_id,
            )
        )
        conflicts = {
            field
            for related in linked
            for field, first, second in (
                ("status", record.status, related.status),
                ("due date", record.due_at, related.due_at),
                (
                    "source priority",
                    record.source_priority,
                    related.source_priority,
                ),
            )
            if first is not None and second is not None and first != second
        }
        associated.append(
            replace(
                record,
                related_source_ids=tuple(sorted(related_ids[record.id])),
                associated_provenance=tuple(related.provenance for related in linked),
                association_conflicts=tuple(sorted(conflicts)),
            )
        )
    return tuple(associated)
