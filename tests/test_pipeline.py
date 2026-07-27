"""Synthetic tests for the deterministic reduced-briefing pipeline."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime

import pytest

from chief_of_staff.connectors import (
    ConnectorRequest,
    ConnectorResult,
    ContextResourceCoverage,
    SourceCoverage,
    SourceItem,
    StaticConnector,
)
from chief_of_staff.connectors.contracts import FactValue
from chief_of_staff.domain import CoverageStatus
from chief_of_staff.pipeline import (
    BriefingItem,
    BriefingPlan,
    BriefingSection,
    BriefingSectionName,
    BriefingValidationError,
    CalendarEventClassification,
    DeterministicBriefingPipeline,
    RenderedBriefing,
    SourceLink,
    WorkdayType,
    classify_calendar_event,
    deduplicate_records,
    normalize_item,
    resolve_context,
    validate_briefing,
)

BRIEFING_DATE = date(2026, 7, 27)
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
SCOPE = "repository-owned synthetic fixtures"
TIME_RANGE_SEPARATOR = "\N{EN DASH}"


def _item(
    item_id: str,
    *,
    source_record_id: str | None = None,
    item_type: str = "task",
    title: str = "Prepare the planning outline",
    retrieved_at: datetime = NOW,
    freshness_at: datetime | None = None,
    **facts: FactValue,
) -> SourceItem:
    item_facts: dict[str, FactValue] = {
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
        freshness_at=retrieved_at if freshness_at is None else freshness_at,
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


def test_context_resolves_weekly_workday_types_and_explicit_overrides() -> None:
    full_workday = resolve_context(
        run_id="full-workday",
        briefing_date=date(2026, 7, 27),
        timezone="America/New_York",
    )
    friday = resolve_context(
        run_id="friday",
        briefing_date=date(2026, 7, 31),
        timezone="America/New_York",
    )
    saturday = resolve_context(
        run_id="saturday",
        briefing_date=date(2026, 8, 1),
        timezone="America/New_York",
    )
    sunday = resolve_context(
        run_id="sunday",
        briefing_date=date(2026, 7, 26),
        timezone="America/New_York",
    )
    override = resolve_context(
        run_id="override",
        briefing_date=date(2026, 7, 26),
        timezone="America/New_York",
        workday_override=True,
    )

    assert full_workday.workday_type is WorkdayType.FULL_WORKDAY
    assert not friday.is_workday
    assert friday.workday_type is WorkdayType.NON_WORKDAY
    assert saturday.workday_type is WorkdayType.FLEXIBLE_HALF_WORKDAY
    assert sunday.workday_type is WorkdayType.MINISTRY_WORKDAY
    assert override.is_workday
    assert override.workday_reason == "explicit current instruction"
    assert full_workday.retrieval_window.starts_at.utcoffset() is not None


def test_workday_override_precedence_and_friday_saturday_switches() -> None:
    friday = date(2026, 7, 31)
    saturday = date(2026, 8, 1)
    friday_switched = resolve_context(
        run_id="friday-switch",
        briefing_date=friday,
        timezone="America/New_York",
        date_overrides={friday: WorkdayType.FULL_WORKDAY},
    )
    saturday_switched = resolve_context(
        run_id="saturday-switch",
        briefing_date=saturday,
        timezone="America/New_York",
        date_overrides={saturday: WorkdayType.NON_WORKDAY},
    )
    explicit_wins = resolve_context(
        run_id="explicit-wins",
        briefing_date=friday,
        timezone="America/New_York",
        workday_type_override=WorkdayType.NON_WORKDAY,
        date_overrides={friday: WorkdayType.FULL_WORKDAY},
        operating_overrides={friday: WorkdayType.MINISTRY_WORKDAY},
    )

    assert friday_switched.workday_type is WorkdayType.FULL_WORKDAY
    assert friday_switched.workday_reason == "explicit date configuration"
    assert saturday_switched.workday_type is WorkdayType.NON_WORKDAY
    assert explicit_wins.workday_type is WorkdayType.NON_WORKDAY
    assert explicit_wins.workday_reason == "explicit current instruction"

    date_configuration_wins = resolve_context(
        run_id="date-wins",
        briefing_date=friday,
        timezone="America/New_York",
        date_overrides={friday: WorkdayType.FULL_WORKDAY},
        operating_overrides={friday: WorkdayType.NON_WORKDAY},
    )
    assert date_configuration_wins.workday_type is WorkdayType.FULL_WORKDAY


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
            effort_minutes=45,
        ),
        timezone="America/New_York",
    )

    assert normalized.id == "synthetic_tasks:task-1"
    assert normalized.due_at is not None
    assert normalized.due_at.utcoffset() is not None
    assert normalized.explicit_commitment
    assert normalized.effort_minutes == 45

    naive = replace(_item("naive"), retrieved_at=datetime(2026, 7, 27, 12, 0))
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_item("synthetic_tasks", naive, timezone="America/New_York")

    for invalid_effort in (0, -5):
        with pytest.raises(
            ValueError, match="effort_minutes must be greater than zero"
        ):
            normalize_item(
                "synthetic_tasks",
                _item("invalid-effort", effort_minutes=invalid_effort),
                timezone="America/New_York",
            )


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
    assert "`synthetic_tasks`: partial" in first.rendered.text
    assert "source importance" not in first.rendered.text
    assert "[synthetic_tasks/task-1]" in first.rendered.text
    names = tuple(section.name for section in first.plan.sections)
    assert names == (
        BriefingSectionName.CHIEF_OF_STAFF_NOTE,
        BriefingSectionName.TODAYS_OUTCOMES,
        BriefingSectionName.UP_NEXT,
        BriefingSectionName.TODAYS_CALENDAR,
        BriefingSectionName.PREPARATION_NEEDED,
        BriefingSectionName.RECOMMENDED_FOCUS_BLOCK,
        BriefingSectionName.LOOKING_AHEAD,
        BriefingSectionName.SOURCE_COVERAGE,
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


@dataclass(frozen=True, slots=True)
class _DetailedCoverageConnector:
    source_name: str = "todoist"
    approved_scope: str = SCOPE

    def retrieve(self, request: ConnectorRequest) -> ConnectorResult:
        item = _item(
            "task-1",
            title="Material selected task",
            status="open",
            due_at=f"{request.briefing_date.isoformat()}T12:00:00-04:00",
        )
        return ConnectorResult(
            items=(item,),
            coverage=SourceCoverage(
                source=self.source_name,
                approved_scope=self.approved_scope,
                status=CoverageStatus.COMPLETE,
                retrieved_at=NOW,
                record_count=1,
                retrieved_count=12,
                selected_count=1,
                persisted_count=1,
                context_resources=(
                    ContextResourceCoverage("projects", 5, 1),
                    ContextResourceCoverage("sections", 2, 1),
                    ContextResourceCoverage("labels", 7, 3),
                ),
            ),
        )


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

    assert "`unavailable_source`: unavailable" in result.rendered.text
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
    assert "`empty_source`: complete" in result.rendered.text


def test_source_coverage_distinguishes_funnel_and_context_resource_counts() -> None:
    context = resolve_context(
        run_id="detailed-coverage",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(
        context,
        (_DetailedCoverageConnector(),),
    )

    coverage = result.plan.sections[-1].summary or ""
    assert (
        "`todoist`: complete; 12 retrieved; 1 selected; 1 persisted; "
        "1 daily candidates; 1 displayed" in coverage
    )
    assert "projects: 5 retrieved, 1 persisted" in coverage
    assert "sections: 2 retrieved, 1 persisted" in coverage
    assert "labels: 7 retrieved, 3 persisted" in coverage


def test_governing_context_informs_the_run_without_becoming_display_content() -> None:
    governing_title = "Accepted governing document"
    governing_summary = "This text governs behavior but is not a daily item."
    repository = _connector(
        "synthetic_repository",
        _item(
            "context-1",
            item_type="context",
            title=governing_title,
            summary=governing_summary,
        ),
    )
    context = resolve_context(
        run_id="governing-context",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (repository,))

    assert any(
        record.kind.value == "context" for record in result.deduplication.records
    )
    assert governing_title not in result.rendered.text
    assert governing_summary not in result.rendered.text
    assert result.plan.sections[0].items == ()
    assert result.plan.sections[-1].name is BriefingSectionName.SOURCE_COVERAGE
    assert "synthetic_repository" in (result.plan.sections[-1].summary or "")


def test_non_workday_briefing_protects_time_off_and_keeps_fixed_context() -> None:
    calendar = _connector(
        "synthetic_calendar",
        _item(
            "event-today",
            item_type="calendar_event",
            title="Scheduled Ministry Commitment",
            status="confirmed",
            start_at="2026-07-27T09:00:00-04:00",
            end_at="2026-07-27T10:00:00-04:00",
            preparation="Bring the approved outline.",
        ),
    )
    tasks = _connector(
        "synthetic_tasks",
        _item(
            "task-today",
            title="Ordinary work due today",
            due_at="2026-07-27T16:00:00-04:00",
            importance=5,
            explicit_commitment=True,
            status="open",
        ),
        _item(
            "task-future",
            title="Prepare for the next workday",
            due_at="2026-07-28T16:00:00-04:00",
            importance=3,
            status="open",
        ),
    )
    context = resolve_context(
        run_id="non-workday",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
        workday_override=False,
    )

    result = DeterministicBriefingPipeline().run(context, (calendar, tasks))

    names = tuple(section.name for section in result.plan.sections)
    assert BriefingSectionName.TODAYS_OUTCOMES not in names
    assert BriefingSectionName.UP_NEXT not in names
    assert BriefingSectionName.IMPORTANT_TASKS not in names
    assert names == (
        BriefingSectionName.CHIEF_OF_STAFF_NOTE,
        BriefingSectionName.TODAYS_CALENDAR,
        BriefingSectionName.PREPARATION_NEEDED,
        BriefingSectionName.SOURCE_COVERAGE,
    )
    assert "non-workday; protect it" in result.rendered.text
    assert "Scheduled Ministry Commitment" in result.rendered.text
    assert "Bring the approved outline" in result.rendered.text
    assert "Ordinary work due today" not in result.rendered.text
    assert "Prepare for the next workday" not in result.rendered.text


def test_calendar_events_receive_evidence_bounded_classifications() -> None:
    calendar = _connector(
        "synthetic_calendar",
        _item(
            "confirmed",
            item_type="calendar_event",
            title="Confirmed Event",
            status="confirmed",
            start_at="2026-07-27T09:00:00-04:00",
            end_at="2026-07-27T10:00:00-04:00",
        ),
        _item(
            "tentative",
            item_type="calendar_event",
            title="Tentative Event",
            status="tentative",
            start_at="2026-07-27T10:30:00-04:00",
            end_at="2026-07-27T11:00:00-04:00",
        ),
        _item(
            "all-day",
            item_type="calendar_event",
            title="All-Day Context",
            status="confirmed",
            all_day=True,
            start_at="2026-07-27T00:00:00-04:00",
            end_at="2026-07-28T00:00:00-04:00",
        ),
        _item(
            "unknown",
            item_type="calendar_event",
            title="Unknown-Status Event",
            start_at="2026-07-27T12:00:00-04:00",
            end_at="2026-07-27T12:30:00-04:00",
        ),
        _item(
            "status-signal",
            item_type="calendar_event",
            title="Home",
            status="confirmed",
            event_type="workingLocation",
            all_day=True,
            start_at="2026-07-27T00:00:00-04:00",
            end_at="2026-07-28T00:00:00-04:00",
        ),
        _item(
            "cancelled",
            item_type="calendar_event",
            title="Cancelled Event",
            status="cancelled",
            start_at="2026-07-27T13:00:00-04:00",
            end_at="2026-07-27T14:00:00-04:00",
        ),
    )
    context = resolve_context(
        run_id="calendar-classification",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (calendar,))

    assert "Confirmed Event** — Fixed commitment" in result.rendered.text
    assert "Tentative Event** — Tentative hold" in result.rendered.text
    assert "All-Day Context** — All-day context" in result.rendered.text
    assert "Unknown-Status Event** — Scheduled event" in result.rendered.text
    home = next(
        record for record in result.deduplication.records if record.title == "Home"
    )
    assert classify_calendar_event(home) is CalendarEventClassification.STATUS_SIGNAL
    assert "Home" not in result.rendered.text
    assert "Cancelled Event" not in result.rendered.text


def test_material_out_of_office_status_signal_remains_visible() -> None:
    calendar = _connector(
        "synthetic_calendar",
        _item(
            "out-of-office",
            item_type="calendar_event",
            title="Out of office",
            status="confirmed",
            event_type="outOfOffice",
            all_day=True,
            start_at="2026-07-27T00:00:00-04:00",
            end_at="2026-07-28T00:00:00-04:00",
        ),
    )
    context = resolve_context(
        run_id="material-status",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (calendar,))

    assert "Out of office** — Status signal · All day" in result.rendered.text
    assert "Calendar status affects availability today" in result.rendered.text
    assert BriefingSectionName.TODAYS_CALENDAR in tuple(
        section.name for section in result.plan.sections
    )


def test_calendar_status_never_redefines_workday_and_schedule_conflict_is_disclosed() -> (
    None
):
    briefing_date = date(2026, 7, 31)
    status_only = _connector(
        "status_calendar",
        _item(
            "office",
            item_type="calendar_event",
            title="Office",
            status="confirmed",
            event_type="workingLocation",
            all_day=True,
            start_at="2026-07-31T00:00:00-04:00",
            end_at="2026-08-01T00:00:00-04:00",
        ),
        _item(
            "all-day-context",
            item_type="calendar_event",
            title="All-day context",
            status="confirmed",
            all_day=True,
            start_at="2026-07-31T00:00:00-04:00",
            end_at="2026-08-01T00:00:00-04:00",
        ),
    )
    fixed_work = _connector(
        "work_calendar",
        _item(
            "first",
            item_type="calendar_event",
            title="First fixed commitment",
            status="confirmed",
            start_at="2026-07-31T09:00:00-04:00",
            end_at="2026-07-31T10:00:00-04:00",
        ),
        _item(
            "second",
            item_type="calendar_event",
            title="Second fixed commitment",
            status="confirmed",
            start_at="2026-07-31T10:30:00-04:00",
            end_at="2026-07-31T11:30:00-04:00",
        ),
    )
    context = resolve_context(
        run_id="workday-conflict",
        briefing_date=briefing_date,
        timezone="America/New_York",
    )

    status_result = DeterministicBriefingPipeline().run(context, (status_only,))
    conflict_result = DeterministicBriefingPipeline().run(context, (fixed_work,))

    assert status_result.plan.context.workday_type is WorkdayType.NON_WORKDAY
    assert status_result.plan.context.workday_diagnostics == ()
    assert conflict_result.plan.context.workday_type is WorkdayType.NON_WORKDAY
    assert conflict_result.plan.context.workday_diagnostics
    assert "conflict with that configuration" in conflict_result.rendered.text
    assert "Workday context:" in conflict_result.rendered.text


def test_obvious_schedule_implications_are_synthesized_deterministically() -> None:
    calendar = _connector(
        "synthetic_calendar",
        _item(
            "event-1",
            item_type="calendar_event",
            title="First",
            status="confirmed",
            start_at="2026-07-27T09:00:00-04:00",
            end_at="2026-07-27T10:00:00-04:00",
        ),
        _item(
            "event-2",
            item_type="calendar_event",
            title="Second",
            status="confirmed",
            start_at="2026-07-27T10:00:00-04:00",
            end_at="2026-07-27T10:30:00-04:00",
        ),
        _item(
            "event-3",
            item_type="calendar_event",
            title="Third",
            status="confirmed",
            start_at="2026-07-27T10:20:00-04:00",
            end_at="2026-07-27T11:00:00-04:00",
        ),
        _item(
            "event-4",
            item_type="calendar_event",
            title="Fourth",
            status="confirmed",
            start_at="2026-07-27T11:10:00-04:00",
            end_at="2026-07-27T12:00:00-04:00",
        ),
    )
    context = resolve_context(
        run_id="schedule-implications",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )
    pipeline = DeterministicBriefingPipeline()

    first = pipeline.run(context, (calendar,))
    second = pipeline.run(context, (calendar,))
    note = first.plan.sections[0].summary or ""

    assert first.rendered == second.rendered
    assert "Calendar anchors the day across" in note
    assert "2 hours 50 minutes scheduled" in note
    assert "1 schedule overlap requires attention" in note
    assert "1 back-to-back transition leaves no calendar margin" in note
    assert "1 tight transition has 15 minutes or less" in note


def test_tomorrows_early_online_campus_events_form_one_sequence() -> None:
    calendar = _connector(
        "synthetic_calendar",
        _item(
            "working-location",
            item_type="calendar_event",
            title="Office",
            status="confirmed",
            event_type="workingLocation",
            all_day=True,
            start_at="2026-07-28T00:00:00-04:00",
            end_at="2026-07-29T00:00:00-04:00",
        ),
        _item(
            "run-through",
            item_type="calendar_event",
            title="ONL Service Run-Through",
            status="confirmed",
            start_at="2026-07-28T08:00:00-04:00",
            end_at="2026-07-28T08:30:00-04:00",
        ),
        _item(
            "first-service",
            item_type="calendar_event",
            title="9:00AM ONL Service",
            status="confirmed",
            start_at="2026-07-28T09:00:00-04:00",
            end_at="2026-07-28T10:00:00-04:00",
        ),
        _item(
            "second-service",
            item_type="calendar_event",
            title="11:00AM ONL Service",
            status="confirmed",
            start_at="2026-07-28T11:00:00-04:00",
            end_at="2026-07-28T12:00:00-04:00",
        ),
    )
    context = resolve_context(
        run_id="tomorrow-sequence",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
        workday_override=False,
    )

    result = DeterministicBriefingPipeline().run(context, (calendar,))

    looking_ahead = next(
        section
        for section in result.plan.sections
        if section.name is BriefingSectionName.LOOKING_AHEAD
    )
    sequence = looking_ahead.items[0]
    assert sequence.headline == "Tomorrow's early Online Campus sequence"
    assert f"From 8:00{TIME_RANGE_SEPARATOR}12:00 p.m." not in sequence.detail
    assert f"From 8:00 a.m.{TIME_RANGE_SEPARATOR}12:00 p.m." in sequence.detail
    assert len(sequence.sources) == 3
    assert len(looking_ahead.items) == 1
    note = result.plan.sections[0].summary or ""
    assert (
        "Today is a configured non-workday; protect it from ordinary work demands."
        in note
    )
    assert (
        "Tomorrow begins with an early Online Campus sequence from 8:00 a.m."
        f"{TIME_RANGE_SEPARATOR}12:00 p.m."
    ) in note
    assert (
        "only preparation that must be completed before then should interrupt today"
        in note
    )
    assert "Calendar status signal" not in note
    assert "1 Calendar" not in note
    assert "Office" not in result.rendered.text


def test_non_workday_note_describes_tightly_sequenced_next_morning() -> None:
    calendar = _connector(
        "synthetic_calendar",
        _item(
            "first",
            item_type="calendar_event",
            title="First confirmed event",
            status="confirmed",
            start_at="2026-07-28T09:30:00-04:00",
            end_at="2026-07-28T10:00:00-04:00",
        ),
        _item(
            "second",
            item_type="calendar_event",
            title="Second confirmed event",
            status="confirmed",
            start_at="2026-07-28T10:15:00-04:00",
            end_at="2026-07-28T11:00:00-04:00",
        ),
    )
    context = resolve_context(
        run_id="tight-tomorrow-sequence",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
        workday_override=False,
    )

    result = DeterministicBriefingPipeline().run(context, (calendar,))

    note = result.plan.sections[0].summary or ""
    assert (
        "Tomorrow contains a tightly sequenced morning schedule from "
        f"9:30{TIME_RANGE_SEPARATOR}11:00 a.m."
    ) in note
    looking_ahead = next(
        section
        for section in result.plan.sections
        if section.name is BriefingSectionName.LOOKING_AHEAD
    )
    assert (
        looking_ahead.items[0].headline
        == "Tomorrow's tightly sequenced morning schedule"
    )


def test_july_25_non_workday_suppresses_routine_status_signals() -> None:
    briefing_date = date(2026, 7, 25)
    repository = _connector(
        "synthetic_repository",
        _item(
            "governing-context",
            item_type="context",
            title="Accepted project context",
        ),
    )
    calendar = _connector(
        "synthetic_calendar",
        _item(
            "home",
            item_type="calendar_event",
            title="Home",
            status="confirmed",
            event_type="workingLocation",
            all_day=True,
            start_at="2026-07-25T00:00:00-04:00",
            end_at="2026-07-26T00:00:00-04:00",
        ),
        _item(
            "office",
            item_type="calendar_event",
            title="Office",
            status="confirmed",
            event_type="workingLocation",
            all_day=True,
            start_at="2026-07-26T00:00:00-04:00",
            end_at="2026-07-27T00:00:00-04:00",
        ),
        _item(
            "run-through",
            item_type="calendar_event",
            title="ONL Run-Through",
            status="confirmed",
            start_at="2026-07-26T08:00:00-04:00",
            end_at="2026-07-26T08:30:00-04:00",
        ),
        _item(
            "first-service",
            item_type="calendar_event",
            title="ONL First Service",
            status="confirmed",
            start_at="2026-07-26T09:00:00-04:00",
            end_at="2026-07-26T10:00:00-04:00",
        ),
        _item(
            "second-service",
            item_type="calendar_event",
            title="ONL Second Service",
            status="confirmed",
            start_at="2026-07-26T10:30:00-04:00",
            end_at="2026-07-26T11:30:00-04:00",
        ),
    )
    context = resolve_context(
        run_id="july-25-redacted",
        briefing_date=briefing_date,
        timezone="America/New_York",
        workday_type_override=WorkdayType.NON_WORKDAY,
    )

    result = DeterministicBriefingPipeline().run(
        context,
        (repository, calendar),
    )

    names = tuple(section.name for section in result.plan.sections)
    assert names == (
        BriefingSectionName.CHIEF_OF_STAFF_NOTE,
        BriefingSectionName.LOOKING_AHEAD,
        BriefingSectionName.SOURCE_COVERAGE,
    )
    assert "Today is a configured non-workday" in result.rendered.text
    assert f"8:00{TIME_RANGE_SEPARATOR}11:30 a.m." in result.rendered.text
    assert "Home" not in result.rendered.text
    assert "Office" not in result.rendered.text
    assert "Accepted project context" not in result.rendered.text
    assert "Calendar status signal" not in result.rendered.text
    assert (
        "`synthetic_repository`: complete; 1 retrieved; 1 selected; "
        "persistence not reported; 0 daily candidates; 0 displayed"
    ) in result.rendered.text
    assert (
        "`synthetic_calendar`: complete; 5 retrieved; 5 selected; "
        "persistence not reported; 0 daily candidates; 3 displayed"
    ) in result.rendered.text
    assert result.rendered.word_count <= 800
    visible_items = tuple(
        item for section in result.plan.sections for item in section.items
    )
    assert visible_items
    assert all(item.sources for item in visible_items)
    assert len(visible_items[0].sources) == 3

    routine_statuses = tuple(
        record
        for record in result.deduplication.records
        if record.title in {"Home", "Office"}
    )
    assert len(routine_statuses) == 2
    assert all(
        classify_calendar_event(record) is CalendarEventClassification.STATUS_SIGNAL
        for record in routine_statuses
    )


def test_july_26_ministry_workday_is_synthesized_and_protected() -> None:
    briefing_date = date(2026, 7, 26)
    calendar = _connector(
        "synthetic_calendar",
        _item(
            "run-through",
            item_type="calendar_event",
            title="ONL Run-Through",
            status="confirmed",
            start_at="2026-07-26T08:00:00-04:00",
            end_at="2026-07-26T08:30:00-04:00",
        ),
        _item(
            "first-service",
            item_type="calendar_event",
            title="ONL First Service",
            status="confirmed",
            start_at="2026-07-26T08:40:00-04:00",
            end_at="2026-07-26T10:00:00-04:00",
        ),
        _item(
            "second-service",
            item_type="calendar_event",
            title="ONL Second Service",
            status="confirmed",
            start_at="2026-07-26T10:10:00-04:00",
            end_at="2026-07-26T11:30:00-04:00",
        ),
    )
    todoist = _connector(
        "todoist",
        _item(
            "ordinary-overdue",
            title="Unrelated overdue project task",
            status="open",
            importance=5,
            due_at="2026-07-24T00:00:00-04:00",
        ),
        _item(
            "must-happen-today",
            title="Necessary Sunday preparation",
            status="open",
            importance=4,
            due_at="2026-07-26T00:00:00-04:00",
        ),
    )
    context = resolve_context(
        run_id="july-26-redacted",
        briefing_date=briefing_date,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (calendar, todoist))
    note = result.plan.sections[0].summary or ""

    assert result.plan.context.workday_type is WorkdayType.MINISTRY_WORKDAY
    assert "scheduled Online Campus ministry workday" in note
    assert f"8:00{TIME_RANGE_SEPARATOR}11:30 a.m." in note
    assert "shortest transition is 10 minutes" in note
    assert "Complete necessary preparation before 8:00 AM" in note
    assert "Protect the remainder from unrelated ordinary project work" in note
    assert "Necessary Sunday preparation" in result.rendered.text
    assert "Unrelated overdue project task" not in result.rendered.text
    assert result.rendered.word_count <= 800


def test_coverage_metadata_is_separate_from_the_chief_of_staff_note() -> None:
    connector = _connector(
        "synthetic_tasks",
        status=CoverageStatus.PARTIAL,
        warnings=("one bounded page was unavailable",),
    )
    context = resolve_context(
        run_id="coverage-placement",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (connector,))

    note = result.plan.sections[0].summary or ""
    coverage = result.plan.sections[-1]
    assert "coverage" not in note.casefold()
    assert "synthetic_tasks" not in note
    assert coverage.name is BriefingSectionName.SOURCE_COVERAGE
    assert "`synthetic_tasks`: partial" in (coverage.summary or "")
    assert "one bounded page was unavailable" in (coverage.summary or "")


def test_todoist_facts_remain_source_signals_without_people_waiting_or_duplicates() -> (
    None
):
    todoist = _connector(
        "todoist",
        _item(
            "task-1",
            title="Synthetic priority task",
            importance=5,
            provider_priority=4,
            explicit_commitment=False,
            status="open",
            due_at="2026-07-27T00:00:00-04:00",
            all_day=True,
        ),
        _item(
            "task-2",
            title="Synthetic approaching task",
            importance=1,
            provider_priority=1,
            explicit_commitment=False,
            status="open",
            due_at="2026-07-30T00:00:00-04:00",
            all_day=True,
        ),
    )
    context = resolve_context(
        run_id="todoist-briefing",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (todoist,))

    names = {section.name for section in result.plan.sections}
    assert BriefingSectionName.PEOPLE_WAITING not in names
    assert BriefingSectionName.COMMITMENTS_AT_RISK not in names
    visible_items = tuple(
        item for section in result.plan.sections for item in section.items
    )
    visible_keys = tuple(item.key for item in visible_items)
    assert len(visible_keys) == len(set(visible_keys))
    assert all(
        source.source == "todoist" for item in visible_items for source in item.sources
    )
    assert "source importance" not in result.rendered.text
    assert "People Waiting on Brad" not in result.rendered.text
    assert result.rendered.word_count <= 800


def test_workday_task_funnel_separates_selection_candidates_and_display() -> None:
    todoist = _connector(
        "todoist",
        *(
            _item(
                f"today-{index}",
                title=f"Synthetic due-today task {index}",
                importance=1,
                status="open",
                due_at="2026-07-27T00:00:00-04:00",
                all_day=True,
            )
            for index in range(8)
        ),
        _item(
            "background",
            title="Synthetic background task",
            importance=1,
            status="open",
            due_at="2026-08-06T00:00:00-04:00",
            all_day=True,
        ),
    )
    context = resolve_context(
        run_id="todoist-funnel",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (todoist,))

    assert len(result.plan.task_candidate_audits) == 1
    audit = result.plan.task_candidate_audits[0]
    assert audit.source == "todoist"
    assert audit.available_count == 9
    assert audit.candidate_count == 8
    assert audit.excluded_reasons == (
        ("outside seven-day daily horizon without current evidence", 1),
    )
    coverage = result.plan.coverage[0]
    assert coverage.selected_count == 9
    assert coverage.candidate_count == 8
    assert coverage.displayed_count == 6
    assert "People Waiting on Brad" not in result.rendered.text


def test_due_today_precedes_overdue_backlog_in_deterministic_order() -> None:
    todoist = _connector(
        "todoist",
        _item(
            "overdue-high",
            title="Synthetic overdue backlog",
            importance=5,
            status="open",
            due_at="2026-07-20T00:00:00-04:00",
            all_day=True,
        ),
        _item(
            "due-today",
            title="Synthetic current-day task",
            importance=1,
            status="open",
            due_at="2026-07-27T00:00:00-04:00",
            all_day=True,
        ),
    )
    context = resolve_context(
        run_id="todoist-current-before-backlog",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (todoist,))

    outcomes = next(
        section
        for section in result.plan.sections
        if section.name is BriefingSectionName.TODAYS_OUTCOMES
    )
    assert len(outcomes.items) == 1
    assert outcomes.items[0].headline == "Synthetic current-day task"
    important = next(
        section
        for section in result.plan.sections
        if section.name is BriefingSectionName.IMPORTANT_TASKS
    )
    assert important.items[0].headline == "Synthetic overdue backlog"


def test_todoist_planning_confidence_uses_transparent_saturation_facts() -> None:
    stale = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    todoist = _connector(
        "todoist",
        _item(
            "overdue-p1",
            provider_priority=4,
            due_at="2026-07-10T00:00:00-04:00",
            all_day=True,
            freshness_at=stale,
        ),
        _item(
            "overdue-p2",
            provider_priority=3,
            due_at="2026-07-11T00:00:00-04:00",
            all_day=True,
            freshness_at=stale,
        ),
        _item(
            "overdue-normal",
            provider_priority=1,
            due_at="2026-07-12T00:00:00-04:00",
            all_day=True,
            freshness_at=stale,
        ),
        _item(
            "undated-p1",
            provider_priority=4,
            freshness_at=stale,
        ),
        _item(
            "due-today",
            provider_priority=1,
            due_at="2026-07-27T00:00:00-04:00",
            all_day=True,
        ),
        *(
            _item(f"background-{index}", provider_priority=1, freshness_at=stale)
            for index in range(3)
        ),
    )
    context = resolve_context(
        run_id="todoist-confidence",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (todoist,))

    confidence = result.plan.task_planning_confidences[0]
    assert confidence.active_count == 8
    assert confidence.overdue_count == 3
    assert confidence.high_priority_count == 3
    assert confidence.overdue_high_priority_overlap_count == 2
    assert confidence.overdue_ratio == pytest.approx(0.375)
    assert confidence.high_priority_ratio == pytest.approx(0.375)
    assert confidence.relative_ranking_degraded
    assert result.plan.task_candidate_audits[0].candidate_count == 1
    assert "relative-ranking confidence degraded" in result.rendered.text
    assert "3 overdue [37.5%]" in result.rendered.text
    assert "3 P1/P2 [37.5%]" in result.rendered.text
    assert "relative ordering is being treated cautiously" in result.rendered.text


def test_degraded_todoist_excludes_stale_overdue_and_priority_only_tasks() -> None:
    stale = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    todoist = _connector(
        "todoist",
        _item(
            "overdue-only",
            provider_priority=1,
            due_at="2026-07-10T00:00:00-04:00",
            all_day=True,
            freshness_at=stale,
        ),
        _item(
            "priority-only",
            provider_priority=4,
            freshness_at=stale,
        ),
    )
    context = resolve_context(
        run_id="todoist-degraded-exclusions",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (todoist,))

    audit = result.plan.task_candidate_audits[0]
    assert audit.candidate_count == 0
    assert audit.excluded_reasons == (
        ("Todoist P1/P2 without current evidence under degraded ranking", 1),
        ("overdue without another current signal", 1),
    )
    assert "overdue-only" not in result.rendered.text
    assert "priority-only" not in result.rendered.text


def test_recent_priority_is_a_strong_multi_signal_candidate() -> None:
    todoist = _connector(
        "todoist",
        _item(
            "recent-p1",
            title="Review the current launch decision",
            provider_priority=4,
            status="open",
        ),
    )
    context = resolve_context(
        run_id="todoist-current-multi-signal",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (todoist,))

    assert result.plan.task_planning_confidences[0].relative_ranking_degraded
    assert result.plan.task_candidate_audits[0].candidate_count == 1
    assert "Review the current launch decision" in result.rendered.text
    assert "recently updated in the source" in result.rendered.text
    assert "Todoist P1" in result.rendered.text


def test_explicit_current_links_survive_degraded_todoist_confidence() -> None:
    stale = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    todoist = _connector(
        "todoist",
        _item(
            "stale-overdue",
            provider_priority=1,
            due_at="2026-07-10T00:00:00-04:00",
            all_day=True,
            freshness_at=stale,
        ),
        _item(
            "calendar-dependent",
            title="Prepare the Calendar-bound decision",
            provider_priority=1,
            calendar_dependency=True,
            freshness_at=stale,
        ),
        _item(
            "active-priority",
            title="Advance the approved active priority",
            provider_priority=1,
            explicit_priority_link=True,
            freshness_at=stale,
        ),
    )
    context = resolve_context(
        run_id="todoist-explicit-current-links",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (todoist,))

    assert result.plan.task_planning_confidences[0].relative_ranking_degraded
    assert result.plan.task_candidate_audits[0].candidate_count == 2
    assert "Prepare the Calendar-bound decision" in result.rendered.text
    assert "Advance the approved active priority" in result.rendered.text
    assert "stale-overdue" not in result.rendered.text


def test_up_next_excludes_distant_work_without_current_preparation() -> None:
    todoist = _connector(
        "todoist",
        _item(
            "distant",
            title="Handle a distant obligation",
            provider_priority=4,
            due_at="2026-09-01T00:00:00-04:00",
            all_day=True,
        ),
        _item(
            "distant-preparation",
            title="Prepare the distant obligation",
            provider_priority=4,
            due_at="2026-09-01T00:00:00-04:00",
            all_day=True,
            preparation="Preparation must begin now.",
        ),
    )
    context = resolve_context(
        run_id="todoist-up-next-horizon",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (todoist,))

    audit = result.plan.task_candidate_audits[0]
    assert audit.candidate_count == 2
    up_next = next(
        section
        for section in result.plan.sections
        if section.name is BriefingSectionName.UP_NEXT
    )
    assert tuple(item.headline for item in up_next.items) == (
        "Prepare the distant obligation",
    )
    assert "Preparation is explicitly required now" in up_next.items[0].detail
    assert "Handle a distant obligation" not in result.rendered.text


def test_task_rendering_cleans_control_tokens_and_all_day_due_time() -> None:
    raw_title = "Draft the launch plan @high_impact"
    todoist = _connector(
        "todoist",
        _item(
            "clean-title",
            title=raw_title,
            provider_priority=4,
            due_at="2026-07-27T00:00:00-04:00",
            all_day=True,
        ),
    )
    context = resolve_context(
        run_id="todoist-clean-rendering",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (todoist,))

    source_record = result.deduplication.records[0]
    assert source_record.title == raw_title
    assert "Draft the launch plan" in result.rendered.text
    assert "@high_impact" not in result.rendered.text
    assert "Complete Draft" not in result.rendered.text
    assert "source due date is today" in result.rendered.text
    assert "12:00 AM" not in result.rendered.text
    assert "source importance" not in result.rendered.text


def test_july_27_calendar_shape_and_focus_window_are_accurate() -> None:
    calendar = _connector(
        "google_calendar",
        _item(
            "morning",
            item_type="calendar_event",
            title="Morning commitment",
            status="confirmed",
            start_at="2026-07-27T09:00:00-04:00",
            end_at="2026-07-27T12:00:00-04:00",
        ),
        _item(
            "afternoon",
            item_type="calendar_event",
            title="Afternoon commitment",
            status="confirmed",
            start_at="2026-07-27T13:00:00-04:00",
            end_at="2026-07-27T15:00:00-04:00",
        ),
    )
    todoist = _connector(
        "todoist",
        _item(
            "supported-outcome",
            title="Finish the current deliverable",
            provider_priority=1,
            due_at="2026-07-27T00:00:00-04:00",
            all_day=True,
        ),
    )
    context = resolve_context(
        run_id="july-27-product-quality",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (calendar, todoist))
    note = result.plan.sections[0].summary or ""

    assert f"9:00 a.m.{TIME_RANGE_SEPARATOR}12:00 p.m." in note
    assert f"1:00{TIME_RANGE_SEPARATOR}3:00 p.m." in note
    assert "5 hours scheduled" in note
    assert "a one-hour gap" in note
    assert "Open Calendar time remains before 9:00 a.m. and after 3:00 p.m." in note
    assert "transition and margin rather than a deep-work block" in note
    assert "one continuous" not in note
    focus = next(
        section
        for section in result.plan.sections
        if section.name is BriefingSectionName.RECOMMENDED_FOCUS_BLOCK
    )
    assert (
        f"3:15{TIME_RANGE_SEPARATOR}4:45 p.m. available focus window"
        == focus.items[0].headline
    )
    assert "Finish the current deliverable" in focus.items[0].detail
    assert "No source effort estimate is available" in focus.items[0].detail
    assert (
        "remainder of the window is intentionally unassigned" in focus.items[0].detail
    )
    assert "90-minute window for" not in focus.items[0].detail
    assert "p.m.." not in result.rendered.text
    assert result.plan.coverage[1].displayed_count == 1


def test_focus_assignment_uses_supported_estimate_and_preserves_remainder() -> None:
    calendar = _connector(
        "google_calendar",
        _item(
            "afternoon",
            item_type="calendar_event",
            status="confirmed",
            start_at="2026-07-27T13:00:00-04:00",
            end_at="2026-07-27T15:00:00-04:00",
        ),
    )
    todoist = _connector(
        "todoist",
        _item(
            "estimated-outcome",
            title="Prepare the supported outline",
            due_at="2026-07-27T00:00:00-04:00",
            all_day=True,
            effort_minutes=45,
        ),
    )
    context = resolve_context(
        run_id="focus-supported-estimate",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (calendar, todoist))
    focus = next(
        section
        for section in result.plan.sections
        if section.name is BriefingSectionName.RECOMMENDED_FOCUS_BLOCK
    )
    detail = focus.items[0].detail

    assert f"8:00{TIME_RANGE_SEPARATOR}8:45 a.m. (45 minutes)" in detail
    assert "remaining 45 minutes intentionally unassigned" in detail
    assert "Prepare the supported outline" in detail
    assert "90-minute" not in detail


def test_focus_block_is_withheld_without_transition_safe_time() -> None:
    calendar = _connector(
        "google_calendar",
        _item(
            "morning",
            item_type="calendar_event",
            status="confirmed",
            start_at="2026-07-27T08:00:00-04:00",
            end_at="2026-07-27T10:00:00-04:00",
        ),
        _item(
            "midday",
            item_type="calendar_event",
            status="confirmed",
            start_at="2026-07-27T10:15:00-04:00",
            end_at="2026-07-27T12:00:00-04:00",
        ),
        _item(
            "afternoon",
            item_type="calendar_event",
            status="confirmed",
            start_at="2026-07-27T12:15:00-04:00",
            end_at="2026-07-27T17:00:00-04:00",
        ),
    )
    todoist = _connector(
        "todoist",
        _item(
            "supported-outcome",
            provider_priority=1,
            due_at="2026-07-27T00:00:00-04:00",
            all_day=True,
        ),
    )
    context = resolve_context(
        run_id="focus-transition-safety",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (calendar, todoist))

    assert BriefingSectionName.RECOMMENDED_FOCUS_BLOCK not in {
        section.name for section in result.plan.sections
    }


def test_degraded_backlog_does_not_fill_visible_task_sections() -> None:
    stale = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    todoist = _connector(
        "todoist",
        *(
            _item(
                f"stale-{index}",
                title=f"Stale backlog item {index}",
                provider_priority=4,
                due_at=f"2026-07-{10 + index:02d}T00:00:00-04:00",
                all_day=True,
                freshness_at=stale,
            )
            for index in range(4)
        ),
    )
    context = resolve_context(
        run_id="todoist-no-arbitrary-fill",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (todoist,))

    names = {section.name for section in result.plan.sections}
    assert BriefingSectionName.TODAYS_OUTCOMES not in names
    assert BriefingSectionName.UP_NEXT not in names
    assert BriefingSectionName.IMPORTANT_TASKS not in names
    assert BriefingSectionName.COMMITMENTS_AT_RISK not in names
    assert result.plan.task_candidate_audits[0].candidate_count == 0
    assert result.plan.coverage[0].displayed_count == 0
    assert "No task has enough current evidence" in result.rendered.text


def test_non_workday_suppresses_todoist_tasks_but_keeps_coverage() -> None:
    todoist = _connector(
        "todoist",
        _item(
            "task-1",
            title="Synthetic ordinary work",
            importance=5,
            provider_priority=1,
            explicit_commitment=False,
            status="open",
            due_at="2026-07-26T00:00:00-04:00",
            all_day=True,
        ),
    )
    context = resolve_context(
        run_id="todoist-non-workday",
        briefing_date=date(2026, 7, 26),
        timezone="America/New_York",
        workday_type_override=WorkdayType.NON_WORKDAY,
    )

    result = DeterministicBriefingPipeline().run(context, (todoist,))

    assert "Synthetic ordinary work" not in result.rendered.text
    assert (
        "`todoist`: complete; 1 retrieved; 1 selected; "
        "persistence not reported; 0 daily candidates; 0 displayed"
    ) in result.rendered.text
    assert tuple(section.name for section in result.plan.sections) == (
        BriefingSectionName.CHIEF_OF_STAFF_NOTE,
        BriefingSectionName.SOURCE_COVERAGE,
    )


def test_repository_calendar_and_todoist_failures_are_independently_disclosed() -> None:
    repository = _connector("repository", status=CoverageStatus.COMPLETE)
    calendar = _connector(
        "google_calendar",
        status=CoverageStatus.PARTIAL,
        warnings=("one calendar page failed",),
    )
    todoist = _connector("todoist", status=CoverageStatus.UNAVAILABLE)
    context = resolve_context(
        run_id="independent-coverage",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(
        context,
        (repository, calendar, todoist),
    )

    coverage = result.plan.sections[-1].summary or ""
    assert "`repository`: complete" in coverage
    assert "`google_calendar`: partial" in coverage
    assert "one calendar page failed" in coverage
    assert "`todoist`: unavailable" in coverage


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
                summary="Today is a workday.",
            ),
            BriefingSection(
                name=BriefingSectionName.TODAYS_OUTCOMES,
                items=(duplicate, duplicate, duplicate, missing_source),
            ),
            BriefingSection(
                name=BriefingSectionName.SOURCE_COVERAGE,
                summary="`synthetic_tasks`: complete; 1 record.",
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


def test_validation_rejects_coverage_metadata_inside_the_note() -> None:
    context = resolve_context(
        run_id="coverage-in-note",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )
    plan = BriefingPlan(
        context=context,
        coverage=(),
        sections=(
            BriefingSection(
                name=BriefingSectionName.CHIEF_OF_STAFF_NOTE,
                summary="Source coverage: metadata does not belong here.",
            ),
            BriefingSection(
                name=BriefingSectionName.SOURCE_COVERAGE,
                summary="No approved source coverage was supplied.",
            ),
        ),
    )
    rendered = RenderedBriefing(text="short", word_count=1)

    with pytest.raises(BriefingValidationError) as error:
        validate_briefing(plan, rendered)

    assert (
        "Chief of Staff Note must not contain source coverage metadata"
        in error.value.errors
    )
