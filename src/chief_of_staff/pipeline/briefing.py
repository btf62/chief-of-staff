"""Structured reduced-briefing composition, rendering, and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from itertools import pairwise
from zoneinfo import ZoneInfo

from chief_of_staff.connectors import SourceCoverage
from chief_of_staff.pipeline.context import InvocationContext, WorkdayType
from chief_of_staff.pipeline.normalization import NormalizedRecord, RecordKind

MAX_WORDS = 1000
PREFERRED_WORDS = 800
MAX_NOTE_WORDS = 150
MAX_OUTCOMES = 3
LIMITED_SECTION_ITEMS = 3
EARLY_MORNING_START = time(9)
MAX_SEQUENCE_GAP = timedelta(minutes=60)
TIME_RANGE_SEPARATOR = "\N{EN DASH}"
TODOIST_OVERDUE_SATURATION_THRESHOLD = 0.25
TODOIST_PRIORITY_SATURATION_THRESHOLD = 0.25
RECENT_TASK_UPDATE_WINDOW = timedelta(days=1)
UP_NEXT_MAX_HORIZON = timedelta(days=14)
FOCUS_WINDOW_START = time(8)
FOCUS_WINDOW_END = time(17)
FOCUS_BLOCK_DURATION = timedelta(minutes=90)
FOCUS_TRANSITION_MARGIN = timedelta(minutes=15)
CONTROL_TOKEN = re.compile(r"(?<!\S)@[A-Za-z0-9_-]+")


class BriefingSectionName(StrEnum):
    """Canonical Daily Briefing v1 section names in required order."""

    CHIEF_OF_STAFF_NOTE = "Chief of Staff Note"
    TODAYS_OUTCOMES = "Today's Outcomes"
    UP_NEXT = "Up Next"
    TODAYS_CALENDAR = "Today's Calendar"
    PREPARATION_NEEDED = "Preparation Needed"
    PEOPLE_WAITING = "People Waiting on Brad"
    COMMITMENTS_AT_RISK = "Commitments at Risk"
    IMPORTANT_TASKS = "Important Tasks"
    RECOMMENDED_FOCUS_BLOCK = "Recommended Focus Block"
    LOOKING_AHEAD = "Looking Ahead"
    SOURCE_COVERAGE = "Source Coverage"


CANONICAL_ORDER = tuple(BriefingSectionName)


class CalendarEventClassification(StrEnum):
    """Evidence-bounded Calendar presentation classifications."""

    FIXED_COMMITMENT = "Fixed commitment"
    TENTATIVE_HOLD = "Tentative hold"
    ALL_DAY_CONTEXT = "All-day context"
    STATUS_SIGNAL = "Status signal"
    SCHEDULED_EVENT = "Scheduled event"


@dataclass(frozen=True, slots=True)
class SourceLink:
    """Source authority attached to one briefing item."""

    source: str
    source_record_id: str
    display_url: str | None


@dataclass(frozen=True, slots=True)
class PriorityInputs:
    """Transparent deterministic inputs; no hidden composite score."""

    overdue: bool
    due_today: bool
    calendar_bound_today: bool
    explicit_commitment: bool
    preparation_required: bool
    source_importance: int
    source: str
    provider_priority: int | None
    recently_updated: bool
    explicit_priority_link: bool

    def explanation(self, *, include_source_priority: bool = True) -> str:
        """Describe the facts that caused deterministic prioritization."""

        reasons: list[str] = []
        if self.overdue:
            reasons.append("overdue")
        if self.due_today:
            reasons.append("due today")
        if self.calendar_bound_today:
            reasons.append("calendar-bound today")
        if self.explicit_commitment:
            reasons.append("explicit commitment")
        if self.preparation_required:
            reasons.append("preparation required")
        if self.explicit_priority_link:
            reasons.append("linked to an approved active priority")
        if self.recently_updated:
            reasons.append("recently updated in the source")
        priority_is_material = not (
            self.due_today
            or self.calendar_bound_today
            or self.explicit_commitment
            or self.preparation_required
            or self.explicit_priority_link
            or (self.overdue and self.recently_updated)
        )
        if (
            include_source_priority
            and priority_is_material
            and self.source == "todoist"
            and self.provider_priority in {3, 4}
        ):
            reasons.append(
                "Todoist P1" if self.provider_priority == 4 else "Todoist P2"
            )
        elif (
            include_source_priority
            and priority_is_material
            and self.source_importance >= 4
        ):
            reasons.append("high priority in the source")
        return ", ".join(reasons) or "no priority signal"


@dataclass(frozen=True, slots=True)
class BriefingItem:
    """One factual or explicitly labeled recommended presentation item."""

    key: str
    headline: str
    detail: str
    sources: tuple[SourceLink, ...]
    priority_inputs: PriorityInputs | None = None


@dataclass(frozen=True, slots=True)
class BriefingSection:
    """One non-empty canonical section."""

    name: BriefingSectionName
    summary: str | None = None
    items: tuple[BriefingItem, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskCandidateAudit:
    """Deterministic task funnel between selection and presentation."""

    source: str
    available_count: int
    candidate_count: int
    excluded_reasons: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class TaskPlanningConfidence:
    """Transparent source aggregates used to qualify relative task ordering."""

    source: str
    active_count: int
    overdue_count: int
    high_priority_count: int
    overdue_high_priority_overlap_count: int
    overdue_threshold: float
    high_priority_threshold: float

    @property
    def overdue_ratio(self) -> float:
        return 0 if self.active_count == 0 else self.overdue_count / self.active_count

    @property
    def high_priority_ratio(self) -> float:
        return (
            0
            if self.active_count == 0
            else self.high_priority_count / self.active_count
        )

    @property
    def relative_ranking_degraded(self) -> bool:
        return (
            self.overdue_ratio > self.overdue_threshold
            or self.high_priority_ratio > self.high_priority_threshold
        )


@dataclass(frozen=True, slots=True)
class FocusWindow:
    """One Calendar-derived proposal with explicit transition margin."""

    starts_at: datetime
    ends_at: datetime
    supporting_events: tuple[NormalizedRecord, ...]


@dataclass(frozen=True, slots=True)
class BriefingPlan:
    """Structured content selected before Markdown rendering."""

    context: InvocationContext
    coverage: tuple[SourceCoverage, ...]
    sections: tuple[BriefingSection, ...]
    task_candidate_audits: tuple[TaskCandidateAudit, ...] = ()
    task_planning_confidences: tuple[TaskPlanningConfidence, ...] = ()
    generation_mode: str = "deterministic_reduced"


@dataclass(frozen=True, slots=True)
class RenderedBriefing:
    """Rendered presentation and its enforceable word count."""

    text: str
    word_count: int


class BriefingValidationError(ValueError):
    """Raised when a plan or rendered briefing violates a product budget."""

    def __init__(self, errors: tuple[str, ...]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def build_reduced_plan(
    context: InvocationContext,
    records: tuple[NormalizedRecord, ...],
    coverage: tuple[SourceCoverage, ...],
) -> BriefingPlan:
    """Compose a factual reduced-mode plan without hosted inference."""

    today = context.briefing_date
    used_record_ids: set[str] = set()
    todays_calendar_context = tuple(
        sorted(
            (
                record
                for record in records
                if record.kind is RecordKind.CALENDAR_EVENT
                and _is_active_calendar_event(record)
                and record.start_at is not None
                and record.start_at.date() == today
            ),
            key=lambda record: record.start_at or datetime.max,
        )
    )
    todays_calendar = tuple(
        record
        for record in todays_calendar_context
        if _is_displayable_calendar_event(record)
    )
    future_calendar_context = tuple(
        sorted(
            (
                record
                for record in records
                if record.kind is RecordKind.CALENDAR_EVENT
                and _is_active_calendar_event(record)
                and record.start_at is not None
                and record.start_at.date() > today
            ),
            key=_future_sort_key,
        )
    )
    tomorrow_sequence = _tomorrow_morning_calendar_sequence(
        future_calendar_context,
        today,
    )
    available_task_records = tuple(
        record
        for record in records
        if record.kind is RecordKind.TASK and record.status != "completed"
    )
    planning_confidences = _task_planning_confidences(
        available_task_records,
        coverage,
        today,
    )
    confidence_by_source = {
        confidence.source: confidence for confidence in planning_confidences
    }
    task_records = tuple(
        record
        for record in available_task_records
        if _task_is_daily_candidate(
            record,
            context,
            confidence_by_source.get(record.provenance.source),
        )
    )
    candidate_task_ids = {record.id for record in task_records}
    prioritized_tasks = sorted(
        task_records,
        key=lambda record: _priority_sort_key(record, today),
    )
    prioritized_tasks = _collapse_associated_task_candidates(
        prioritized_tasks,
        today,
    )
    outcome_candidates = tuple(
        record for record in prioritized_tasks if _is_outcome_candidate(record, today)
    )[:MAX_OUTCOMES]
    focus_window = _recommended_focus_window(todays_calendar_context, context)
    todoist_confidence = confidence_by_source.get("todoist")
    sections: list[BriefingSection] = [
        BriefingSection(
            name=BriefingSectionName.CHIEF_OF_STAFF_NOTE,
            summary=_chief_note(
                context,
                todays_calendar_context,
                tomorrow_sequence,
                primary_outcome=(outcome_candidates[0] if outcome_candidates else None),
                focus_window=focus_window,
                todoist_confidence=todoist_confidence,
            ),
        )
    ]
    if outcome_candidates:
        sections.append(
            BriefingSection(
                name=BriefingSectionName.TODAYS_OUTCOMES,
                items=tuple(
                    _outcome_item(record, today) for record in outcome_candidates
                ),
            )
        )
        used_record_ids.update(record.id for record in outcome_candidates)

    up_next = tuple(
        record
        for record in prioritized_tasks
        if record.id not in used_record_ids and _is_up_next_candidate(record, today)
    )[:LIMITED_SECTION_ITEMS]
    if up_next:
        sections.append(
            BriefingSection(
                name=BriefingSectionName.UP_NEXT,
                items=tuple(
                    _record_item(
                        record,
                        key_prefix="up-next",
                        detail=_up_next_detail(record, today),
                    )
                    for record in up_next
                ),
            )
        )
        used_record_ids.update(record.id for record in up_next)

    if todays_calendar:
        sections.append(
            BriefingSection(
                name=BriefingSectionName.TODAYS_CALENDAR,
                items=tuple(_calendar_item(record) for record in todays_calendar),
            )
        )

    calendar_preparation = tuple(
        record for record in todays_calendar if record.preparation is not None
    )
    task_preparation = tuple(
        record
        for record in prioritized_tasks
        if record.preparation is not None and record.calendar_dependency
    )
    preparation = (*calendar_preparation, *task_preparation)
    if preparation:
        sections.append(
            BriefingSection(
                name=BriefingSectionName.PREPARATION_NEEDED,
                items=tuple(_preparation_item(record) for record in preparation),
            )
        )

    commitments_at_risk = tuple(
        record
        for record in prioritized_tasks
        if record.id not in used_record_ids
        and record.provenance.source == "jira"
        and record.source_owned_risk
    )[:LIMITED_SECTION_ITEMS]
    if commitments_at_risk:
        sections.append(
            BriefingSection(
                name=BriefingSectionName.COMMITMENTS_AT_RISK,
                items=tuple(_jira_risk_item(record) for record in commitments_at_risk),
            )
        )
        used_record_ids.update(record.id for record in commitments_at_risk)

    important_tasks = tuple(
        record
        for record in prioritized_tasks
        if record.id not in used_record_ids
        and _is_important_task_candidate(record, today)
    )[:LIMITED_SECTION_ITEMS]
    if important_tasks:
        sections.append(
            BriefingSection(
                name=BriefingSectionName.IMPORTANT_TASKS,
                items=tuple(
                    _record_item(
                        record,
                        key_prefix="important",
                        detail=_priority_inputs(record, today).explanation(),
                    )
                    for record in important_tasks
                ),
            )
        )
        used_record_ids.update(record.id for record in important_tasks)

    focus_section = _recommended_focus_section(
        context,
        focus_window,
        primary_outcome=(outcome_candidates[0] if outcome_candidates else None),
        todoist_confidence=todoist_confidence,
    )
    if focus_section is not None:
        sections.append(focus_section)

    future_records = tuple(
        sorted(
            (
                record
                for record in records
                if record.id not in used_record_ids
                and (
                    record.kind is not RecordKind.TASK
                    or (
                        record.id in candidate_task_ids
                        and _task_needs_looking_ahead(record, today)
                    )
                )
                and (
                    record.kind is not RecordKind.CALENDAR_EVENT
                    or _is_displayable_calendar_event(record)
                )
                and (
                    (record.start_at is not None and record.start_at.date() > today)
                    or (record.due_at is not None and record.due_at.date() > today)
                )
            ),
            key=_future_sort_key,
        )
    )
    sequence_record_ids = {record.id for record in tomorrow_sequence}
    looking_ahead_items: list[BriefingItem] = []
    if tomorrow_sequence:
        looking_ahead_items.append(_calendar_sequence_item(tomorrow_sequence))
    for record in future_records:
        if record.id in sequence_record_ids:
            continue
        looking_ahead_items.append(_looking_ahead_item(record))
        if len(looking_ahead_items) == LIMITED_SECTION_ITEMS:
            break
    if looking_ahead_items:
        sections.append(
            BriefingSection(
                name=BriefingSectionName.LOOKING_AHEAD,
                items=tuple(looking_ahead_items),
            )
        )

    sections.append(
        BriefingSection(
            name=BriefingSectionName.SOURCE_COVERAGE,
            summary=_coverage_summary(
                context,
                coverage,
                planning_confidences,
            ),
        )
    )

    return BriefingPlan(
        context=context,
        coverage=coverage,
        sections=tuple(sections),
        task_candidate_audits=_task_candidate_audits(
            available_task_records,
            task_records,
            context,
            confidence_by_source,
        ),
        task_planning_confidences=planning_confidences,
    )


def render_briefing(plan: BriefingPlan) -> RenderedBriefing:
    """Render a structured plan as concise Markdown."""

    workday_label = plan.context.workday_type.value
    lines = [
        f"# Daily Briefing — {plan.context.briefing_date.isoformat()}",
        "",
        f"_Deterministic reduced mode · {workday_label} "
        f"({plan.context.workday_reason})_",
    ]
    for section in plan.sections:
        lines.extend(("", f"## {section.name}"))
        if section.summary:
            lines.extend(("", section.summary))
        for item in section.items:
            sources = "; ".join(_render_source(source) for source in item.sources)
            lines.extend(
                (
                    "",
                    f"- **{item.headline}** — {item.detail} Source: {sources}",
                )
            )

    text = "\n".join(lines).rstrip() + "\n"
    return RenderedBriefing(text=text, word_count=_word_count(text))


def validate_briefing(
    plan: BriefingPlan,
    rendered: RenderedBriefing,
) -> None:
    """Enforce canonical ordering, provenance, duplication, and budgets."""

    errors: list[str] = []
    names = tuple(section.name for section in plan.sections)
    order = tuple(CANONICAL_ORDER.index(name) for name in names)
    if order != tuple(sorted(set(order))):
        errors.append("sections must be unique and in canonical order")
    if not names or names[0] is not BriefingSectionName.CHIEF_OF_STAFF_NOTE:
        errors.append("Chief of Staff Note must be the first section")
    if not names or names[-1] is not BriefingSectionName.SOURCE_COVERAGE:
        errors.append("Source Coverage must be the final section")

    note = plan.sections[0] if plan.sections else None
    if note is not None and _word_count(note.summary or "") > MAX_NOTE_WORDS:
        errors.append("Chief of Staff Note exceeds 150 words")
    if note is not None and "source coverage" in (note.summary or "").casefold():
        errors.append("Chief of Staff Note must not contain source coverage metadata")
    if rendered.word_count > MAX_WORDS:
        errors.append("briefing exceeds the 1,000-word maximum")

    seen_keys: set[str] = set()
    for section in plan.sections:
        if not section.summary and not section.items:
            errors.append(f"{section.name} is empty")
        limit = (
            MAX_OUTCOMES
            if section.name is BriefingSectionName.TODAYS_OUTCOMES
            else (
                LIMITED_SECTION_ITEMS
                if section.name
                in {
                    BriefingSectionName.UP_NEXT,
                    BriefingSectionName.PEOPLE_WAITING,
                    BriefingSectionName.COMMITMENTS_AT_RISK,
                    BriefingSectionName.IMPORTANT_TASKS,
                }
                else None
            )
        )
        if limit is not None and len(section.items) > limit:
            errors.append(f"{section.name} exceeds its item budget")
        for item in section.items:
            if not item.sources:
                errors.append(f"{item.key} has no source provenance")
            if item.key in seen_keys:
                errors.append(f"{item.key} appears more than once")
            seen_keys.add(item.key)

    coverage_sections = tuple(
        section
        for section in plan.sections
        if section.name is BriefingSectionName.SOURCE_COVERAGE
    )
    coverage_text = (
        coverage_sections[0].summary
        if len(coverage_sections) == 1 and coverage_sections[0].summary
        else ""
    )
    if len(coverage_sections) != 1 or not coverage_text:
        errors.append("source coverage disclosure is missing")
    for source in plan.coverage:
        if source.source not in coverage_text:
            errors.append(f"coverage for {source.source} is not disclosed")

    if errors:
        raise BriefingValidationError(tuple(errors))


def _chief_note(
    context: InvocationContext,
    todays_calendar_context: tuple[NormalizedRecord, ...],
    tomorrow_sequence: tuple[NormalizedRecord, ...],
    *,
    primary_outcome: NormalizedRecord | None,
    focus_window: FocusWindow | None,
    todoist_confidence: TaskPlanningConfidence | None,
) -> str:
    if context.workday_type is WorkdayType.MINISTRY_WORKDAY:
        return _ministry_workday_note(todays_calendar_context)

    if context.is_workday:
        return _normal_workday_note(
            context,
            todays_calendar_context,
            primary_outcome=primary_outcome,
            focus_window=focus_window,
            todoist_confidence=todoist_confidence,
        )

    parts = [
        "Today is a configured non-workday; protect it from ordinary work demands.",
    ]
    fixed_today = tuple(
        record
        for record in todays_calendar_context
        if classify_calendar_event(record)
        is CalendarEventClassification.FIXED_COMMITMENT
    )
    if fixed_today:
        parts.append(_schedule_summary(fixed_today))
    if context.workday_diagnostics:
        parts.append(
            "The fixed schedule is substantial enough to conflict with that "
            "configuration; review the discrepancy without letting Calendar "
            "silently redefine the day."
        )
    if tomorrow_sequence:
        parts.append(_tomorrow_sequence_note(tomorrow_sequence))
    else:
        parts.append(
            "Only a fixed commitment or preparation that truly cannot wait "
            "should interrupt today."
        )
    return " ".join(parts)


def _coverage_summary(
    context: InvocationContext,
    coverage: tuple[SourceCoverage, ...],
    planning_confidences: tuple[TaskPlanningConfidence, ...],
) -> str:
    if not coverage:
        return "No approved source coverage was supplied."

    confidence_by_source = {
        confidence.source: confidence for confidence in planning_confidences
    }
    coverage_parts: list[str] = []
    for report in coverage:
        retrieved = (
            report.record_count
            if report.retrieved_count is None
            else report.retrieved_count
        )
        selected = (
            report.record_count
            if report.selected_count is None
            else report.selected_count
        )
        persisted = (
            "persistence not reported"
            if report.persisted_count is None
            else f"{report.persisted_count} persisted"
        )
        candidates = (
            "daily candidates not reported"
            if report.candidate_count is None
            else f"{report.candidate_count} daily candidates"
        )
        displayed = (
            "display not reported"
            if report.displayed_count is None
            else f"{report.displayed_count} displayed"
        )
        pagination = (
            None
            if report.page_count is None
            else (
                f"{report.page_count} pages (pagination occurred)"
                if report.page_count > 1
                else ("1 page (no pagination)" if report.page_count == 1 else "0 pages")
            )
        )
        detail = (
            f"`{report.source}`: {report.status.value}; "
            f"{retrieved} retrieved; {selected} selected; "
            f"{persisted}; {candidates}; {displayed}"
        )
        if pagination is not None:
            detail += f"; {pagination}"
        if report.context_resources:
            resources = ", ".join(
                (
                    f"{resource.resource}: {resource.retrieved_count} retrieved, "
                    + (
                        "persistence not reported"
                        if resource.persisted_count is None
                        else f"{resource.persisted_count} persisted"
                    )
                )
                for resource in report.context_resources
            )
            detail += f"; context ({resources})"
        if report.warnings:
            detail += f"; {'; '.join(report.warnings)}"
        if report.error_category:
            detail += f"; {report.error_category}"
        planning_confidence = confidence_by_source.get(report.source)
        if planning_confidence is not None:
            status = (
                "degraded"
                if planning_confidence.relative_ranking_degraded
                else "not degraded"
            )
            detail += (
                f"; relative-ranking confidence {status} "
                f"({planning_confidence.active_count} active, "
                f"{planning_confidence.overdue_count} overdue "
                f"[{planning_confidence.overdue_ratio:.1%}], "
                f"{planning_confidence.high_priority_count} P1/P2 "
                f"[{planning_confidence.high_priority_ratio:.1%}], "
                f"{planning_confidence.overdue_high_priority_overlap_count} "
                "both overdue and P1/P2)"
            )
        coverage_parts.append(detail)
    if context.workday_diagnostics:
        coverage_parts.append(
            "Workday context: " + " ".join(context.workday_diagnostics)
        )
    return ". ".join(coverage_parts) + "."


def _normal_workday_note(
    context: InvocationContext,
    todays_calendar_context: tuple[NormalizedRecord, ...],
    *,
    primary_outcome: NormalizedRecord | None,
    focus_window: FocusWindow | None,
    todoist_confidence: TaskPlanningConfidence | None,
) -> str:
    day_label = (
        "flexible half-workday"
        if context.workday_type is WorkdayType.FLEXIBLE_HALF_WORKDAY
        else "workday"
    )
    parts = [
        f"Today is a {day_label}.",
        _calendar_shape_summary(todays_calendar_context),
    ]
    if primary_outcome is not None:
        parts.append(
            f"The strongest supported outcome is {_display_title(primary_outcome)}, "
            f"{_brief_due_phrase(primary_outcome, context.briefing_date)}."
        )
    else:
        parts.append("No task has enough current evidence to become a primary outcome.")
    if focus_window is not None and primary_outcome is not None:
        parts.append(
            f"Protect {_natural_time_span(focus_window.starts_at, focus_window.ends_at)} "
            "as the clearest focus window after Calendar transition margin."
        )
    elif (
        focus_window is not None
        and todoist_confidence is not None
        and todoist_confidence.relative_ranking_degraded
    ):
        parts.append(
            f"Calendar leaves {_natural_time_span(focus_window.starts_at, focus_window.ends_at)} "
            "as the clearest focus window, but no task has enough current evidence "
            "to assign as its objective."
        )
    if todoist_confidence is not None and todoist_confidence.relative_ranking_degraded:
        parts.append(_todoist_confidence_disclosure(todoist_confidence))
    return " ".join(parts)


def _ministry_workday_note(
    todays_calendar_context: tuple[NormalizedRecord, ...],
) -> str:
    fixed = tuple(
        sorted(
            (
                record
                for record in todays_calendar_context
                if classify_calendar_event(record)
                is CalendarEventClassification.FIXED_COMMITMENT
                and record.start_at is not None
            ),
            key=lambda record: record.start_at or datetime.max,
        )
    )
    if not fixed:
        return (
            "Today is a scheduled ministry workday. Protect the remainder of the "
            "day from unrelated ordinary project work."
        )

    starts = tuple(record.start_at for record in fixed if record.start_at is not None)
    ends = tuple(record.end_at for record in fixed if record.end_at is not None)
    label = (
        "Online Campus ministry workday"
        if _calendar_sequence_label(fixed) == "Online Campus sequence"
        else "ministry workday"
    )
    noun = "commitment" if len(fixed) == 1 else "commitments"
    span = _natural_time_span(min(starts), max(ends) if ends else None)
    parts = [f"Today is a scheduled {label} with {len(fixed)} fixed {noun} from {span}"]
    minimum_gap = _minimum_positive_transition(fixed)
    if minimum_gap is not None and minimum_gap <= timedelta(minutes=15):
        minutes = int(minimum_gap.total_seconds() // 60)
        parts.append(
            f"The shortest transition is {minutes} "
            f"{'minute' if minutes == 1 else 'minutes'}, so the sequence is tight."
        )
    first_start = min(starts)
    parts.append(f"Complete necessary preparation before {first_start:%-I:%M %p}.")
    parts.append("Protect the remainder from unrelated ordinary project work.")
    return " ".join(parts)


def _minimum_positive_transition(
    fixed_events: tuple[NormalizedRecord, ...],
) -> timedelta | None:
    gaps = tuple(
        current.start_at - previous.end_at
        for previous, current in pairwise(fixed_events)
        if previous.end_at is not None
        and current.start_at is not None
        and current.start_at >= previous.end_at
    )
    return min(gaps) if gaps else None


def classify_calendar_event(
    record: NormalizedRecord,
) -> CalendarEventClassification:
    """Classify a Calendar fact without title-based inference."""

    if record.kind is not RecordKind.CALENDAR_EVENT:
        raise ValueError("calendar classification requires a calendar event")
    if (record.event_type or "").casefold() in {
        "workinglocation",
        "outofoffice",
    }:
        return CalendarEventClassification.STATUS_SIGNAL
    if record.all_day:
        return CalendarEventClassification.ALL_DAY_CONTEXT

    status = (record.status or "").casefold()
    if status == "confirmed":
        return CalendarEventClassification.FIXED_COMMITMENT
    if status == "tentative":
        return CalendarEventClassification.TENTATIVE_HOLD
    return CalendarEventClassification.SCHEDULED_EVENT


def _schedule_summary(todays_calendar: tuple[NormalizedRecord, ...]) -> str:
    visible_calendar = tuple(
        record for record in todays_calendar if _is_displayable_calendar_event(record)
    )
    if not visible_calendar:
        return "No visible Calendar commitment requires attention today."

    fixed = tuple(
        record
        for record in visible_calendar
        if classify_calendar_event(record)
        is CalendarEventClassification.FIXED_COMMITMENT
    )
    tentative_count = sum(
        classify_calendar_event(record) is CalendarEventClassification.TENTATIVE_HOLD
        for record in visible_calendar
    )
    all_day_count = sum(
        classify_calendar_event(record) is CalendarEventClassification.ALL_DAY_CONTEXT
        for record in visible_calendar
    )
    material_status = tuple(
        record
        for record in visible_calendar
        if classify_calendar_event(record) is CalendarEventClassification.STATUS_SIGNAL
    )
    unclassified_count = sum(
        classify_calendar_event(record) is CalendarEventClassification.SCHEDULED_EVENT
        for record in visible_calendar
    )

    parts: list[str] = []
    if fixed:
        first_start = min(
            record.start_at for record in fixed if record.start_at is not None
        )
        fixed_ends = tuple(
            record.end_at for record in fixed if record.end_at is not None
        )
        time_span = (
            f" from {first_start:%-I:%M %p} to {max(fixed_ends):%-I:%M %p}"
            if fixed_ends
            else ""
        )
        noun = "commitment" if len(fixed) == 1 else "commitments"
        parts.append(f"Calendar shows {len(fixed)} fixed {noun}{time_span}.")
        parts.extend(_schedule_implications(fixed))
    if tentative_count:
        noun = "hold remains" if tentative_count == 1 else "holds remain"
        parts.append(f"{tentative_count} tentative {noun} non-fixed.")
    if unclassified_count:
        noun = "event lacks" if unclassified_count == 1 else "events lack"
        parts.append(
            f"{unclassified_count} scheduled {noun} enough status evidence "
            "to call fixed."
        )
    if all_day_count:
        noun = "item is" if all_day_count == 1 else "items are"
        parts.append(
            f"{all_day_count} all-day {noun} treated as context, not full-day "
            "occupancy."
        )
    if material_status:
        parts.append(
            "An explicit Calendar status affects availability today."
            if len(material_status) == 1
            else "Explicit Calendar status changes affect availability today."
        )
    return " ".join(parts)


def _calendar_shape_summary(
    todays_calendar: tuple[NormalizedRecord, ...],
) -> str:
    fixed = tuple(
        sorted(
            (
                record
                for record in todays_calendar
                if classify_calendar_event(record)
                is CalendarEventClassification.FIXED_COMMITMENT
                and record.start_at is not None
                and record.end_at is not None
            ),
            key=lambda record: record.start_at or datetime.max,
        )
    )
    if not fixed:
        material_status = any(
            classify_calendar_event(record) is CalendarEventClassification.STATUS_SIGNAL
            and _is_material_status_signal(record)
            for record in todays_calendar
        )
        if material_status:
            return "An explicit Calendar status affects availability today."
        return "No fixed Calendar commitment shapes the day."

    spans = tuple(
        _natural_time_span(record.start_at, record.end_at)
        for record in fixed
        if record.start_at is not None
    )
    total_minutes = _scheduled_union_minutes(fixed)
    gap_minutes = _positive_gap_minutes(fixed)
    if len(spans) == 1:
        shape = f"The Calendar anchors the day from {spans[0]}"
    elif len(spans) == 2:
        shape = (
            f"The Calendar anchors the day with commitments from {spans[0]} "
            f"and {spans[1]}"
        )
    else:
        shape = f"The Calendar anchors the day across {spans[0]} through {spans[-1]}"
    shape += f"—{_duration_phrase(total_minutes)} scheduled"
    if len(gap_minutes) == 1:
        shape += f", separated by {_gap_phrase(gap_minutes[0])}"
    elif gap_minutes:
        shape += (
            f", with {len(gap_minutes)} gaps totaling "
            f"{_duration_phrase(sum(gap_minutes))}"
        )
    shape += "."

    first_start = fixed[0].start_at
    last_end = max(record.end_at for record in fixed if record.end_at is not None)
    open_parts: list[str] = []
    if first_start is not None:
        open_parts.append(f"before {_natural_clock_text(first_start)}")
    open_parts.append(f"after {_natural_clock_text(last_end)}")
    open_time = "Open Calendar time remains " + " and ".join(open_parts)
    if len(gap_minutes) == 1 and gap_minutes[0] <= 60:
        open_time += (
            f" Treat {_gap_phrase(gap_minutes[0])} as transition and margin "
            "rather than a deep-work block."
        )
    implications = " ".join(_schedule_implications(fixed))
    return " ".join(part for part in (shape, implications, open_time) if part)


def _scheduled_union_minutes(
    events: tuple[NormalizedRecord, ...],
) -> int:
    intervals = tuple(
        sorted(
            (
                (record.start_at, record.end_at)
                for record in events
                if record.start_at is not None and record.end_at is not None
            ),
            key=lambda interval: interval[0],
        )
    )
    if not intervals:
        return 0
    total = timedelta()
    current_start, current_end = intervals[0]
    for start_at, end_at in intervals[1:]:
        if start_at <= current_end:
            current_end = max(current_end, end_at)
            continue
        total += current_end - current_start
        current_start, current_end = start_at, end_at
    total += current_end - current_start
    return int(total.total_seconds() // 60)


def _positive_gap_minutes(
    events: tuple[NormalizedRecord, ...],
) -> tuple[int, ...]:
    return tuple(
        int((current.start_at - previous.end_at).total_seconds() // 60)
        for previous, current in pairwise(events)
        if previous.end_at is not None
        and current.start_at is not None
        and current.start_at > previous.end_at
    )


def _duration_phrase(minutes: int) -> str:
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} {'hour' if hours == 1 else 'hours'}"
    if minutes > 60:
        hours, remainder = divmod(minutes, 60)
        return f"{hours} {'hour' if hours == 1 else 'hours'} {remainder} minutes"
    return f"{minutes} {'minute' if minutes == 1 else 'minutes'}"


def _gap_phrase(minutes: int) -> str:
    if minutes == 60:
        return "a one-hour gap"
    return f"a {minutes}-minute gap"


def _natural_clock_text(value: datetime) -> str:
    clock, period = _natural_clock(value)
    return f"{clock} {period}"


def _schedule_implications(
    fixed_events: tuple[NormalizedRecord, ...],
) -> tuple[str, ...]:
    timed = tuple(
        sorted(
            (
                event
                for event in fixed_events
                if event.start_at is not None and event.end_at is not None
            ),
            key=lambda event: event.start_at or datetime.max,
        )
    )
    overlaps = 0
    back_to_back = 0
    tight_transitions = 0
    previous_end: datetime | None = None
    for event in timed:
        if event.start_at is None or event.end_at is None:
            continue
        if previous_end is not None:
            if event.start_at < previous_end:
                overlaps += 1
            elif event.start_at == previous_end:
                back_to_back += 1
            elif (event.start_at - previous_end).total_seconds() <= 15 * 60:
                tight_transitions += 1
        previous_end = (
            event.end_at
            if previous_end is None or event.end_at > previous_end
            else previous_end
        )

    implications: list[str] = []
    if overlaps:
        noun = "overlap requires" if overlaps == 1 else "overlaps require"
        implications.append(f"{overlaps} schedule {noun} attention.")
    if back_to_back:
        noun = "transition leaves" if back_to_back == 1 else "transitions leave"
        implications.append(f"{back_to_back} back-to-back {noun} no calendar margin.")
    if tight_transitions:
        noun = "transition has" if tight_transitions == 1 else "transitions have"
        implications.append(f"{tight_transitions} tight {noun} 15 minutes or less.")
    return tuple(implications)


def _is_active_calendar_event(record: NormalizedRecord) -> bool:
    return (record.status or "").casefold() != "cancelled"


def _is_displayable_calendar_event(record: NormalizedRecord) -> bool:
    if not _is_active_calendar_event(record):
        return False
    if classify_calendar_event(record) is not CalendarEventClassification.STATUS_SIGNAL:
        return True
    return _is_material_status_signal(record)


def _is_material_status_signal(record: NormalizedRecord) -> bool:
    """Require explicit provider or preparation evidence before display."""

    event_type = (record.event_type or "").casefold()
    return event_type == "outofoffice" or record.preparation is not None


def _is_outcome_candidate(record: NormalizedRecord, today: date) -> bool:
    return record.explicit_commitment or (
        record.due_at is not None and record.due_at.date() == today
    )


def _is_up_next_candidate(record: NormalizedRecord, today: date) -> bool:
    if record.due_at is None or record.due_at.date() <= today:
        return False
    due_date = record.due_at.date()
    if due_date <= today + UP_NEXT_MAX_HORIZON:
        return True
    return record.preparation is not None or record.calendar_dependency


def _up_next_detail(record: NormalizedRecord, today: date) -> str:
    if record.due_at is None:
        raise ValueError("Up Next requires a source due date")
    due_detail = _source_due_sentence(record, today)
    if record.due_at.date() > today + UP_NEXT_MAX_HORIZON:
        return f"Preparation is explicitly required now. {due_detail}"
    return due_detail


def _is_important_task_candidate(record: NormalizedRecord, today: date) -> bool:
    due_date = None if record.due_at is None else record.due_at.date()
    if record.provenance.source == "jira" and due_date is not None and due_date > today:
        return False
    return (
        due_date is None
        or due_date <= today
        or record.explicit_commitment
        or record.preparation is not None
        or record.calendar_dependency
        or record.explicit_priority_link
    )


def _task_needs_looking_ahead(record: NormalizedRecord, today: date) -> bool:
    return bool(
        record.due_at is not None
        and record.due_at.date() > today
        and (record.preparation is not None or record.calendar_dependency)
    )


def _task_is_daily_candidate(
    record: NormalizedRecord,
    context: InvocationContext,
    planning_confidence: TaskPlanningConfidence | None,
) -> bool:
    if not context.is_workday:
        return False
    due_date = None if record.due_at is None else record.due_at.date()
    if context.workday_type is WorkdayType.MINISTRY_WORKDAY:
        return (
            record.explicit_commitment
            or record.preparation is not None
            or due_date == context.briefing_date
            or record.calendar_dependency
            or record.explicit_priority_link
        )
    if record.provenance.source == "todoist":
        return _todoist_task_is_daily_candidate(
            record,
            context.briefing_date,
            planning_confidence,
        )
    if record.provenance.source == "jira":
        return _jira_task_is_daily_candidate(record, context.briefing_date)
    return (
        record.explicit_commitment
        or record.preparation is not None
        or record.importance >= 4
        or (
            due_date is not None
            and due_date <= context.briefing_date + timedelta(days=7)
        )
    )


def _jira_task_is_daily_candidate(
    record: NormalizedRecord,
    today: date,
) -> bool:
    """Require current evidence beyond assignment, age, or Jira priority."""

    due_date = None if record.due_at is None else record.due_at.date()
    if (
        record.explicit_commitment
        or record.preparation is not None
        or record.calendar_dependency
        or record.explicit_priority_link
        or record.source_owned_risk
    ):
        return True
    if due_date is not None and today <= due_date <= today + timedelta(days=7):
        return True
    return bool(
        due_date is not None
        and due_date < today
        and _is_recently_updated(record, today)
    )


def _collapse_associated_task_candidates(
    records: list[NormalizedRecord],
    today: date,
) -> list[NormalizedRecord]:
    """Present one recommendation per explicit task association."""

    candidates = {record.id: record for record in records}
    suppressed: set[str] = set()
    for record in records:
        group = tuple(
            candidate
            for candidate_id in record.related_source_ids
            if (candidate := candidates.get(candidate_id)) is not None
        )
        if not group:
            continue
        representative = min(
            (record, *group),
            key=lambda candidate: _priority_sort_key(candidate, today),
        )
        suppressed.update(
            candidate.id
            for candidate in (record, *group)
            if candidate.id != representative.id
        )
    return [record for record in records if record.id not in suppressed]


def _todoist_task_is_daily_candidate(
    record: NormalizedRecord,
    today: date,
    planning_confidence: TaskPlanningConfidence | None,
) -> bool:
    due_date = None if record.due_at is None else record.due_at.date()
    if (
        record.explicit_commitment
        or record.preparation is not None
        or record.calendar_dependency
        or record.explicit_priority_link
    ):
        return True
    if due_date is not None and today <= due_date <= today + timedelta(days=7):
        return True

    high_priority = record.provider_priority in {3, 4}
    recently_updated = _is_recently_updated(record, today)
    if due_date is not None and due_date < today:
        return recently_updated
    if high_priority and recently_updated:
        return True
    return bool(
        high_priority
        and planning_confidence is not None
        and not planning_confidence.relative_ranking_degraded
    )


def _is_recently_updated(record: NormalizedRecord, today: date) -> bool:
    freshness_at = record.provenance.freshness_at
    if freshness_at is None:
        return False
    age = today - freshness_at.date()
    return timedelta() <= age <= RECENT_TASK_UPDATE_WINDOW


def _task_planning_confidences(
    available: tuple[NormalizedRecord, ...],
    coverage: tuple[SourceCoverage, ...],
    today: date,
) -> tuple[TaskPlanningConfidence, ...]:
    reports = {report.source: report for report in coverage}
    source_records = tuple(
        record for record in available if record.provenance.source == "todoist"
    )
    if not source_records and "todoist" not in reports:
        return ()
    report = reports.get("todoist")
    if (
        report is not None
        and report.selected_count is not None
        and report.selected_count != len(source_records)
    ):
        return ()
    reported_active = (
        len(source_records)
        if report is None or report.retrieved_count is None
        else report.retrieved_count
    )
    overdue_count = sum(
        record.due_at is not None and record.due_at.date() < today
        for record in source_records
    )
    high_priority_count = sum(
        record.provider_priority in {3, 4} for record in source_records
    )
    overlap_count = sum(
        record.due_at is not None
        and record.due_at.date() < today
        and record.provider_priority in {3, 4}
        for record in source_records
    )
    return (
        TaskPlanningConfidence(
            source="todoist",
            active_count=max(
                reported_active,
                overdue_count,
                high_priority_count,
            ),
            overdue_count=overdue_count,
            high_priority_count=high_priority_count,
            overdue_high_priority_overlap_count=overlap_count,
            overdue_threshold=TODOIST_OVERDUE_SATURATION_THRESHOLD,
            high_priority_threshold=TODOIST_PRIORITY_SATURATION_THRESHOLD,
        ),
    )


def _task_candidate_audits(
    available: tuple[NormalizedRecord, ...],
    candidates: tuple[NormalizedRecord, ...],
    context: InvocationContext,
    confidence_by_source: dict[str, TaskPlanningConfidence],
) -> tuple[TaskCandidateAudit, ...]:
    candidate_ids = {record.id for record in candidates}
    sources = sorted({record.provenance.source for record in available})
    audits: list[TaskCandidateAudit] = []
    for source in sources:
        source_records = tuple(
            record for record in available if record.provenance.source == source
        )
        reasons: dict[str, int] = {}
        for record in source_records:
            if record.id in candidate_ids:
                continue
            reason = _task_candidate_exclusion_reason(
                record,
                context,
                confidence_by_source.get(source),
            )
            reasons[reason] = reasons.get(reason, 0) + 1
        audits.append(
            TaskCandidateAudit(
                source=source,
                available_count=len(source_records),
                candidate_count=sum(
                    record.id in candidate_ids for record in source_records
                ),
                excluded_reasons=tuple(sorted(reasons.items())),
            )
        )
    return tuple(audits)


def _task_candidate_exclusion_reason(
    record: NormalizedRecord,
    context: InvocationContext,
    planning_confidence: TaskPlanningConfidence | None,
) -> str:
    if not context.is_workday:
        return "configured non-workday"
    if context.workday_type is WorkdayType.MINISTRY_WORKDAY:
        return "unrelated to ministry workday"
    due_date = None if record.due_at is None else record.due_at.date()
    if record.provenance.source == "todoist":
        if due_date is not None and due_date < context.briefing_date:
            return "overdue without another current signal"
        if (
            record.provider_priority in {3, 4}
            and planning_confidence is not None
            and planning_confidence.relative_ranking_degraded
        ):
            return "Todoist P1/P2 without current evidence under degraded ranking"
        return "outside seven-day daily horizon without current evidence"
    if record.provenance.source == "jira":
        if due_date is not None and due_date < context.briefing_date:
            return "overdue Jira issue without another current signal"
        return "Jira assignment or priority without current briefing evidence"
    return "outside seven-day daily horizon without another priority signal"


def _recommended_focus_window(
    todays_calendar_context: tuple[NormalizedRecord, ...],
    context: InvocationContext,
) -> FocusWindow | None:
    if context.workday_type not in {
        WorkdayType.FULL_WORKDAY,
        WorkdayType.FLEXIBLE_HALF_WORKDAY,
    }:
        return None
    occupied = tuple(
        sorted(
            (
                record
                for record in todays_calendar_context
                if _is_active_calendar_event(record)
                and record.start_at is not None
                and record.end_at is not None
                and not record.all_day
                and classify_calendar_event(record)
                is not CalendarEventClassification.STATUS_SIGNAL
            ),
            key=lambda record: record.start_at or datetime.max,
        )
    )
    if not occupied:
        return None

    zone = ZoneInfo(context.timezone)
    planning_start = datetime.combine(
        context.briefing_date,
        FOCUS_WINDOW_START,
        tzinfo=zone,
    )
    planning_end = datetime.combine(
        context.briefing_date,
        FOCUS_WINDOW_END,
        tzinfo=zone,
    )
    cursor = planning_start
    previous: NormalizedRecord | None = None
    for event in occupied:
        if event.start_at is None or event.end_at is None:
            continue
        gap_end = min(planning_end, event.start_at - FOCUS_TRANSITION_MARGIN)
        if gap_end - cursor >= FOCUS_BLOCK_DURATION:
            supporting = tuple(
                record for record in (previous, event) if record is not None
            )
            return FocusWindow(
                starts_at=cursor,
                ends_at=cursor + FOCUS_BLOCK_DURATION,
                supporting_events=supporting,
            )
        cursor = max(cursor, event.end_at + FOCUS_TRANSITION_MARGIN)
        previous = event
    if planning_end - cursor < FOCUS_BLOCK_DURATION:
        return None
    return FocusWindow(
        starts_at=cursor,
        ends_at=cursor + FOCUS_BLOCK_DURATION,
        supporting_events=(() if previous is None else (previous,)),
    )


def _recommended_focus_section(
    context: InvocationContext,
    focus_window: FocusWindow | None,
    *,
    primary_outcome: NormalizedRecord | None,
    todoist_confidence: TaskPlanningConfidence | None,
) -> BriefingSection | None:
    if focus_window is None or context.workday_type not in {
        WorkdayType.FULL_WORKDAY,
        WorkdayType.FLEXIBLE_HALF_WORKDAY,
    }:
        return None
    span = _natural_time_span(focus_window.starts_at, focus_window.ends_at)
    sources = tuple(
        dict.fromkeys(
            (
                *(() if primary_outcome is None else _source_links(primary_outcome)),
                *(_source_link(event) for event in focus_window.supporting_events),
            )
        )
    )
    if primary_outcome is not None:
        detail = _focus_objective_detail(
            primary_outcome,
            focus_window,
            context.briefing_date,
        )
    elif (
        todoist_confidence is not None and todoist_confidence.relative_ranking_degraded
    ):
        detail = (
            "Calendar supports this uninterrupted window after transition margin, "
            "but no Todoist task has enough current evidence to assign as its "
            "objective."
        )
    else:
        return None
    if not sources:
        return None
    return BriefingSection(
        name=BriefingSectionName.RECOMMENDED_FOCUS_BLOCK,
        items=(
            BriefingItem(
                key=f"focus:{context.briefing_date.isoformat()}",
                headline=f"{span} available focus window",
                detail=detail,
                sources=sources,
            ),
        ),
    )


def _focus_objective_detail(
    objective: NormalizedRecord,
    focus_window: FocusWindow,
    today: date,
) -> str:
    """Describe a supported objective without inventing its required effort."""

    title = _display_title(objective)
    available_minutes = int(
        (focus_window.ends_at - focus_window.starts_at).total_seconds() // 60
    )
    estimate = objective.effort_minutes
    if estimate is None:
        assignment = (
            f"Begin with {title}. No source effort estimate is available, so the "
            "remainder of the window is intentionally unassigned."
        )
    elif estimate < available_minutes:
        objective_end = focus_window.starts_at + timedelta(minutes=estimate)
        remaining_minutes = available_minutes - estimate
        assignment = (
            f"Use {_natural_time_span(focus_window.starts_at, objective_end)} "
            f"({_duration_phrase(estimate)}) for {title}; keep the remaining "
            f"{_duration_phrase(remaining_minutes)} intentionally unassigned."
        )
    elif estimate == available_minutes:
        assignment = (
            f"Use the available {_duration_phrase(estimate)} for {title}; the "
            "source estimate supports the full window."
        )
    else:
        assignment = (
            f"Use the available {_duration_phrase(available_minutes)} to begin "
            f"{title}; its source estimate is {_duration_phrase(estimate)}, so "
            "do not imply the work will be completed in this window."
        )
    return (
        f"{assignment} {_source_due_sentence(objective, today)} "
        "The proposal preserves Calendar transition margin."
    )


def _todoist_confidence_disclosure(
    confidence: TaskPlanningConfidence,
) -> str:
    saturated: list[str] = []
    if confidence.overdue_ratio > confidence.overdue_threshold:
        saturated.append("overdue")
    if confidence.high_priority_ratio > confidence.high_priority_threshold:
        saturated.append("high-priority")
    saturation = " and ".join(saturated) or "relative"
    return (
        f"Todoist's {saturation} backlog signals are saturated, so relative "
        "ordering is being treated cautiously and current dates or explicit "
        "links take precedence."
    )


def _priority_inputs(record: NormalizedRecord, today: date) -> PriorityInputs:
    due_date = None if record.due_at is None else record.due_at.date()
    return PriorityInputs(
        overdue=due_date is not None and due_date < today,
        due_today=due_date == today,
        calendar_bound_today=record.calendar_dependency
        or (record.start_at is not None and record.start_at.date() == today),
        explicit_commitment=record.explicit_commitment,
        preparation_required=record.preparation is not None,
        source_importance=record.importance,
        source=record.provenance.source,
        provider_priority=record.provider_priority,
        recently_updated=_is_recently_updated(record, today),
        explicit_priority_link=record.explicit_priority_link,
    )


def _priority_sort_key(record: NormalizedRecord, today: date) -> tuple[object, ...]:
    inputs = _priority_inputs(record, today)
    due_at = record.due_at or datetime.max.replace(
        tzinfo=record.provenance.retrieved_at.tzinfo
    )
    return (
        not inputs.due_today,
        not inputs.explicit_commitment,
        not inputs.calendar_bound_today,
        not inputs.preparation_required,
        not inputs.explicit_priority_link,
        not inputs.recently_updated,
        not inputs.overdue,
        -inputs.source_importance,
        due_at,
        record.title.casefold(),
    )


def _future_sort_key(record: NormalizedRecord) -> tuple[datetime, str]:
    future_at = record.start_at or record.due_at
    if future_at is None:
        future_at = datetime.max.replace(tzinfo=record.provenance.retrieved_at.tzinfo)
    return future_at, record.title.casefold()


def _tomorrow_morning_calendar_sequence(
    future_records: tuple[NormalizedRecord, ...],
    today: date,
) -> tuple[NormalizedRecord, ...]:
    tomorrow = today + timedelta(days=1)
    candidates = tuple(
        record
        for record in future_records
        if record.kind is RecordKind.CALENDAR_EVENT
        and classify_calendar_event(record)
        is CalendarEventClassification.FIXED_COMMITMENT
        and record.start_at is not None
        and record.start_at.date() == tomorrow
        and record.start_at.hour < 12
    )
    if len(candidates) < 2:
        return ()

    first_start = candidates[0].start_at
    if first_start is None:
        return ()
    starts_early = first_start.timetz().replace(tzinfo=None) < EARLY_MORNING_START
    tightly_sequenced = all(
        previous.end_at is not None
        and current.start_at is not None
        and current.start_at - previous.end_at <= MAX_SEQUENCE_GAP
        for previous, current in pairwise(candidates)
    )
    return candidates if starts_early or tightly_sequenced else ()


def _calendar_sequence_item(
    records: tuple[NormalizedRecord, ...],
) -> BriefingItem:
    starts = tuple(record.start_at for record in records if record.start_at is not None)
    ends = tuple(record.end_at for record in records if record.end_at is not None)
    if not starts:
        raise ValueError("calendar sequence requires start times")

    starts_early = min(starts).timetz().replace(tzinfo=None) < EARLY_MORNING_START
    sequence_label = _calendar_sequence_label(records)
    headline = (
        f"Tomorrow's early {sequence_label}"
        if starts_early
        else f"Tomorrow's tightly sequenced {sequence_label}"
    )
    span = _natural_time_span(min(starts), max(ends) if ends else None)
    titles = "; ".join(record.title for record in records)
    return BriefingItem(
        key="ahead-sequence:" + "|".join(record.id for record in records),
        headline=headline,
        detail=f"From {span}, in order: {titles}.",
        sources=tuple(_source_link(record) for record in records),
    )


def _tomorrow_sequence_note(
    records: tuple[NormalizedRecord, ...],
) -> str:
    starts = tuple(record.start_at for record in records if record.start_at is not None)
    ends = tuple(record.end_at for record in records if record.end_at is not None)
    if not starts:
        raise ValueError("calendar sequence requires start times")

    starts_early = min(starts).timetz().replace(tzinfo=None) < EARLY_MORNING_START
    sequence_label = _calendar_sequence_label(records)
    span = _natural_time_span(min(starts), max(ends) if ends else None)
    if starts_early:
        schedule_phrase = f"Tomorrow begins with an early {sequence_label} from {span}"
    else:
        schedule_phrase = (
            f"Tomorrow contains a tightly sequenced {sequence_label} from {span}"
        )
    return (
        f"{schedule_phrase}, so only preparation that must be completed before "
        "then should interrupt today."
    )


def _calendar_sequence_label(records: tuple[NormalizedRecord, ...]) -> str:
    online_campus = all(
        re.search(r"\bonl\b", record.title, flags=re.IGNORECASE) is not None
        for record in records
    )
    return "Online Campus sequence" if online_campus else "morning schedule"


def _natural_time_span(start: datetime, end: datetime | None) -> str:
    start_clock, start_period = _natural_clock(start)
    if end is None:
        return f"{start_clock} {start_period}"

    end_clock, end_period = _natural_clock(end)
    if start_period == end_period:
        return f"{start_clock}{TIME_RANGE_SEPARATOR}{end_clock} {end_period}"
    return f"{start_clock} {start_period}{TIME_RANGE_SEPARATOR}{end_clock} {end_period}"


def _natural_clock(value: datetime) -> tuple[str, str]:
    return (
        value.strftime("%-I:%M"),
        "a.m." if value.hour < 12 else "p.m.",
    )


def _outcome_item(record: NormalizedRecord, today: date) -> BriefingItem:
    inputs = _priority_inputs(record, today)
    deadline = _source_due_sentence(record, today)
    return BriefingItem(
        key=f"outcome:{record.id}",
        headline=_display_title(record),
        detail=f"{inputs.explanation()}. {deadline}{_association_detail(record)}",
        sources=_source_links(record),
        priority_inputs=inputs,
    )


def _calendar_item(record: NormalizedRecord) -> BriefingItem:
    if record.start_at is None:
        raise ValueError("calendar item requires a start time")
    if record.all_day:
        time_range = "All day"
    else:
        time_range = record.start_at.strftime("%-I:%M %p")
        if record.end_at is not None:
            time_range += f"-{record.end_at:%-I:%M %p}"
    classification = classify_calendar_event(record).value
    if record.all_day and (record.status or "").casefold() == "tentative":
        classification += " (tentative)"
    return _record_item(
        record,
        key_prefix="calendar",
        detail=f"{classification} · {time_range}",
    )


def _preparation_item(record: NormalizedRecord) -> BriefingItem:
    if record.preparation is None:
        raise ValueError("preparation item requires explicit source preparation")
    return _record_item(
        record,
        key_prefix="preparation",
        detail=record.preparation,
    )


def _jira_risk_item(record: NormalizedRecord) -> BriefingItem:
    dependencies = (
        "Dependency: " + ", ".join(record.dependency_references) + ". "
        if record.dependency_references
        else ""
    )
    return _record_item(
        record,
        key_prefix="jira-risk",
        detail=(
            f"{dependencies}Jira reports this work as blocked or endangered. "
            "This is Jira-owned work status, not a human-promise claim."
        ),
    )


def _looking_ahead_item(record: NormalizedRecord) -> BriefingItem:
    when = record.start_at or record.due_at
    detail = "Approaching work."
    if (
        record.kind is RecordKind.CALENDAR_EVENT
        and classify_calendar_event(record) is CalendarEventClassification.STATUS_SIGNAL
    ):
        detail = (
            "Upcoming Calendar status signal."
            if when is None
            else f"{when:%A, %B %-d} · Status signal."
        )
        return _record_item(record, key_prefix="ahead", detail=detail)
    if when is not None:
        detail = (
            f"{when:%A, %B %-d} (all day)."
            if record.all_day
            else f"{when:%A, %B %-d at %-I:%M %p}."
        )
    return _record_item(record, key_prefix="ahead", detail=detail)


def _record_item(
    record: NormalizedRecord,
    *,
    key_prefix: str,
    detail: str,
) -> BriefingItem:
    return BriefingItem(
        key=f"{key_prefix}:{record.id}",
        headline=_display_title(record),
        detail=detail + _association_detail(record),
        sources=_source_links(record),
    )


def _display_title(record: NormalizedRecord) -> str:
    if record.kind is not RecordKind.TASK:
        return record.title
    cleaned = CONTROL_TOKEN.sub("", record.title)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" \t-:;")
    return cleaned or f"{record.provenance.source} task"


def _brief_due_phrase(record: NormalizedRecord, today: date) -> str:
    if record.due_at is None:
        return "supported by explicit current evidence"
    due_date = record.due_at.date()
    if due_date == today:
        return "due today"
    if due_date < today:
        return f"overdue since {record.due_at:%A, %B %-d}"
    if record.all_day:
        return f"due {record.due_at:%A, %B %-d}"
    return f"due {record.due_at:%A, %B %-d at %-I:%M %p}"


def _source_due_sentence(record: NormalizedRecord, today: date) -> str:
    if record.due_at is None:
        return "No source deadline is recorded."
    due_date = record.due_at.date()
    if due_date == today:
        if record.all_day:
            return "The source due date is today."
        return f"The source deadline is today at {record.due_at:%-I:%M %p}."
    if due_date < today:
        if record.all_day:
            return f"The source due date was {record.due_at:%A, %B %-d}."
        return f"The source deadline was {record.due_at:%A, %B %-d at %-I:%M %p}."
    if record.all_day:
        return f"The source due date is {record.due_at:%A, %B %-d}."
    return f"The source deadline is {record.due_at:%A, %B %-d at %-I:%M %p}."


def _source_link(record: NormalizedRecord) -> SourceLink:
    return SourceLink(
        source=record.provenance.source,
        source_record_id=record.provenance.source_record_id,
        display_url=record.provenance.display_url,
    )


def _source_links(record: NormalizedRecord) -> tuple[SourceLink, ...]:
    links = [_source_link(record)]
    links.extend(
        SourceLink(
            source=provenance.source,
            source_record_id=provenance.source_record_id,
            display_url=provenance.display_url,
        )
        for provenance in record.associated_provenance
    )
    return tuple(links)


def _association_detail(record: NormalizedRecord) -> str:
    if not record.associated_provenance:
        return ""
    if record.association_conflicts:
        return (
            " Explicitly associated source records disagree on "
            + ", ".join(record.association_conflicts)
            + "; both remain authoritative."
        )
    return " Explicitly associated source records support one combined item."


def _render_source(source: SourceLink) -> str:
    label = f"{source.source}/{source.source_record_id}"
    return label if source.display_url is None else f"[{label}]({source.display_url})"


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))
