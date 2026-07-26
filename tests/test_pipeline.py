"""Synthetic tests for the deterministic reduced-briefing pipeline."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime

import pytest

from chief_of_staff.connectors import (
    ConnectorRequest,
    ConnectorResult,
    SourceCoverage,
    SourceItem,
    StaticConnector,
)
from chief_of_staff.domain import CoverageStatus
from chief_of_staff.pipeline import (
    BriefingItem,
    BriefingPlan,
    BriefingSection,
    BriefingSectionName,
    BriefingValidationError,
    DeterministicBriefingPipeline,
    RenderedBriefing,
    SourceLink,
    deduplicate_records,
    normalize_item,
    resolve_context,
    validate_briefing,
)

BRIEFING_DATE = date(2026, 7, 27)
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
SCOPE = "repository-owned synthetic fixtures"


def _item(
    item_id: str,
    *,
    source_record_id: str | None = None,
    item_type: str = "task",
    title: str = "Prepare the planning outline",
    retrieved_at: datetime = NOW,
    **facts: str | int | bool | None,
) -> SourceItem:
    item_facts: dict[str, str | int | bool | None] = {
        "title": title,
        **facts,
    }
    return SourceItem(
        id=item_id,
        source_record_id=source_record_id or item_id,
        item_type=item_type,
        facts=item_facts,
        display_url=f"https://example.invalid/source/{item_id}",
        retrieved_at=retrieved_at,
        freshness_at=retrieved_at,
    )


def _connector(
    source_name: str,
    *items: SourceItem,
    status: CoverageStatus = CoverageStatus.COMPLETE,
    warnings: tuple[str, ...] = (),
) -> StaticConnector:
    return StaticConnector(
        source_name=source_name,
        approved_scope=SCOPE,
        items=items,
        status=status,
        warnings=warnings,
    )


def test_context_resolves_workdays_weekends_and_explicit_overrides() -> None:
    weekday = resolve_context(
        run_id="weekday",
        briefing_date=date(2026, 7, 27),
        timezone="America/New_York",
    )
    weekend = resolve_context(
        run_id="weekend",
        briefing_date=date(2026, 7, 26),
        timezone="America/New_York",
    )
    override = resolve_context(
        run_id="override",
        briefing_date=date(2026, 7, 26),
        timezone="America/New_York",
        workday_override=True,
    )

    assert weekday.is_workday
    assert not weekend.is_workday
    assert override.is_workday
    assert override.workday_reason == "explicit invocation override"
    assert weekday.retrieval_window.starts_at.utcoffset() is not None


@pytest.mark.parametrize(
    ("timezone", "lookahead_days", "message"),
    [
        ("Not/A_Zone", 7, "recognized IANA"),
        ("America/New_York", 0, "positive"),
    ],
)
def test_context_rejects_invalid_invocation_inputs(
    timezone: str,
    lookahead_days: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_context(
            run_id="invalid",
            briefing_date=BRIEFING_DATE,
            timezone=timezone,
            lookahead_days=lookahead_days,
        )


def test_normalization_requires_typed_facts_and_aware_timestamps() -> None:
    normalized = normalize_item(
        "synthetic_tasks",
        _item(
            "task-1",
            due_at="2026-07-27T16:00:00-04:00",
            importance=5,
            explicit_commitment=True,
        ),
        timezone="America/New_York",
    )

    assert normalized.id == "synthetic_tasks:task-1"
    assert normalized.due_at is not None
    assert normalized.due_at.utcoffset() is not None
    assert normalized.explicit_commitment

    naive = replace(_item("naive"), retrieved_at=datetime(2026, 7, 27, 12, 0))
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_item("synthetic_tasks", naive, timezone="America/New_York")


def test_deduplication_collapses_only_exact_same_source_records() -> None:
    older = normalize_item(
        "synthetic_tasks",
        _item(
            "copy-a",
            source_record_id="task-1",
            retrieved_at=datetime(2026, 7, 27, 10, 0, tzinfo=UTC),
        ),
        timezone="America/New_York",
    )
    newer = normalize_item(
        "synthetic_tasks",
        _item(
            "copy-b",
            source_record_id="task-1",
            retrieved_at=datetime(2026, 7, 27, 11, 0, tzinfo=UTC),
        ),
        timezone="America/New_York",
    )
    conflict = normalize_item(
        "synthetic_tasks",
        _item(
            "copy-c",
            source_record_id="task-2",
            title="First version",
        ),
        timezone="America/New_York",
    )
    conflicting_copy = normalize_item(
        "synthetic_tasks",
        _item(
            "copy-d",
            source_record_id="task-2",
            title="Changed version",
        ),
        timezone="America/New_York",
    )

    result = deduplicate_records(
        (older, newer, conflict, conflicting_copy),
    )

    assert {record.id for record in result.records} == {
        newer.id,
        conflict.id,
        conflicting_copy.id,
    }
    assert len(result.exact_duplicates) == 1
    assert len(result.conflicts) == 1


def test_reduced_pipeline_is_deterministic_traceable_and_within_budget() -> None:
    calendar = _connector(
        "synthetic_calendar",
        _item(
            "event-1",
            item_type="calendar_event",
            title="Planning Session",
            start_at="2026-07-27T09:00:00-04:00",
            end_at="2026-07-27T10:00:00-04:00",
            preparation="Review the synthetic outline.",
        ),
        _item(
            "event-2",
            item_type="calendar_event",
            title="Tomorrow Review",
            start_at="2026-07-28T13:00:00-04:00",
        ),
    )
    tasks = _connector(
        "synthetic_tasks",
        _item(
            "task-1",
            title="Finish the briefing outline",
            due_at="2026-07-27T16:00:00-04:00",
            importance=5,
            explicit_commitment=True,
            status="open",
        ),
        _item(
            "task-2",
            title="Draft the next project brief",
            due_at="2026-07-29T12:00:00-04:00",
            importance=3,
            status="open",
        ),
        status=CoverageStatus.PARTIAL,
        warnings=("one synthetic page was unavailable",),
    )
    context = resolve_context(
        run_id="synthetic-run",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )
    pipeline = DeterministicBriefingPipeline()

    first = pipeline.run(context, (calendar, tasks))
    second = pipeline.run(context, (calendar, tasks))

    assert first.rendered == second.rendered
    assert first.rendered.word_count <= 800
    assert "synthetic_tasks partial" in first.rendered.text
    assert "hosted inference" in first.rendered.text
    assert "source importance 5/5" in first.rendered.text
    assert "[synthetic_tasks/task-1]" in first.rendered.text
    names = tuple(section.name for section in first.plan.sections)
    assert names == (
        BriefingSectionName.CHIEF_OF_STAFF_NOTE,
        BriefingSectionName.TODAYS_OUTCOMES,
        BriefingSectionName.UP_NEXT,
        BriefingSectionName.TODAYS_CALENDAR,
        BriefingSectionName.PREPARATION_NEEDED,
        BriefingSectionName.LOOKING_AHEAD,
    )
    all_items = tuple(item for section in first.plan.sections for item in section.items)
    assert len({item.key for item in all_items}) == len(all_items)
    assert all(item.sources for item in all_items)
    outcome = first.plan.sections[1].items[0]
    assert outcome.priority_inputs is not None
    assert outcome.priority_inputs.explicit_commitment


@dataclass(frozen=True, slots=True)
class _FailingConnector:
    source_name: str = "unavailable_source"
    approved_scope: str = SCOPE

    def retrieve(self, request: ConnectorRequest) -> ConnectorResult:
        del request
        raise TimeoutError("synthetic timeout")


def test_connector_failure_is_disclosed_without_aborting_the_briefing() -> None:
    context = resolve_context(
        run_id="failure-run",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(
        context,
        (_FailingConnector(),),
    )

    assert "unavailable_source unavailable" in result.rendered.text
    assert "TimeoutError" in result.rendered.text
    assert result.plan.coverage[0].record_count == 0


def test_empty_static_connector_reports_complete_zero_record_coverage() -> None:
    context = resolve_context(
        run_id="empty-run",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )
    connector = _connector("empty_source")

    result = DeterministicBriefingPipeline().run(context, (connector,))

    assert result.plan.coverage[0].record_count == 0
    assert result.plan.coverage[0].status is CoverageStatus.COMPLETE
    assert "empty_source complete" in result.rendered.text


def test_read_only_connector_surface_exposes_no_mutation_operations() -> None:
    connector = _connector("synthetic_tasks")

    for operation in ("create", "update", "delete", "send", "write"):
        assert not hasattr(connector, operation)


def test_validation_rejects_duplicates_missing_provenance_and_hard_budgets() -> None:
    context = resolve_context(
        run_id="invalid-plan",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )
    coverage = (
        SourceCoverage(
            source="synthetic_tasks",
            approved_scope=SCOPE,
            status=CoverageStatus.COMPLETE,
            retrieved_at=NOW,
            record_count=1,
        ),
    )
    source = SourceLink(
        source="synthetic_tasks",
        source_record_id="task-1",
        display_url=None,
    )
    duplicate = BriefingItem(
        key="duplicate",
        headline="Synthetic task",
        detail="An explicit test item.",
        sources=(source,),
    )
    missing_source = replace(duplicate, sources=())
    plan = BriefingPlan(
        context=context,
        coverage=coverage,
        sections=(
            BriefingSection(
                name=BriefingSectionName.CHIEF_OF_STAFF_NOTE,
                summary="Source coverage: synthetic_tasks complete.",
            ),
            BriefingSection(
                name=BriefingSectionName.TODAYS_OUTCOMES,
                items=(duplicate, duplicate, duplicate, missing_source),
            ),
        ),
    )
    oversized = RenderedBriefing(text="word " * 1001, word_count=1001)

    with pytest.raises(BriefingValidationError) as error:
        validate_briefing(plan, oversized)

    assert "briefing exceeds the 1,000-word maximum" in error.value.errors
    assert "Today's Outcomes exceeds its item budget" in error.value.errors
    assert "duplicate appears more than once" in error.value.errors
    assert "duplicate has no source provenance" in error.value.errors
