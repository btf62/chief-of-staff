"""Orchestrate retrieval, normalization, deduplication, and composition."""

from __future__ import annotations

from dataclasses import dataclass
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
from chief_of_staff.pipeline.context import InvocationContext
from chief_of_staff.pipeline.deduplication import (
    DeduplicationResult,
    deduplicate_records,
)
from chief_of_staff.pipeline.normalization import NormalizedRecord, normalize_item


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
        plan = build_reduced_plan(
            context,
            deduplication.records,
            tuple(coverage),
        )
        rendered = render_briefing(plan)
        validate_briefing(plan, rendered)
        return PipelineResult(
            deduplication=deduplication,
            plan=plan,
            rendered=rendered,
        )
