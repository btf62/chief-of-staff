"""Structured reduced-briefing composition, rendering, and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from itertools import pairwise

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

    def explanation(self) -> str:
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
        if self.source_importance:
            reasons.append(f"source importance {self.source_importance}/5")
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
class BriefingPlan:
    """Structured content selected before Markdown rendering."""

    context: InvocationContext
    coverage: tuple[SourceCoverage, ...]
    sections: tuple[BriefingSection, ...]
    task_candidate_audits: tuple[TaskCandidateAudit, ...] = ()
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
    sections: list[BriefingSection] = [
        BriefingSection(
            name=BriefingSectionName.CHIEF_OF_STAFF_NOTE,
            summary=_chief_note(
                context,
                todays_calendar_context,
                tomorrow_sequence,
            ),
        )
    ]

    available_task_records = tuple(
        record
        for record in records
        if record.kind is RecordKind.TASK and record.status != "completed"
    )
    task_records = tuple(
        record
        for record in available_task_records
        if _task_is_daily_candidate(record, context)
    )
    candidate_task_ids = {record.id for record in task_records}
    prioritized_tasks = sorted(
        task_records,
        key=lambda record: _priority_sort_key(record, today),
    )
    outcome_candidates = tuple(
        record for record in prioritized_tasks if _is_outcome_candidate(record, today)
    )[:MAX_OUTCOMES]
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
        if record.id not in used_record_ids
        and record.due_at is not None
        and record.due_at.date() > today
    )[:LIMITED_SECTION_ITEMS]
    if up_next:
        sections.append(
            BriefingSection(
                name=BriefingSectionName.UP_NEXT,
                items=tuple(
                    _record_item(
                        record,
                        key_prefix="up-next",
                        detail=f"Due {record.due_at:%A, %B %-d}.",
                    )
                    for record in up_next
                    if record.due_at is not None
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

    preparation = tuple(
        record for record in todays_calendar if record.preparation is not None
    )
    if preparation:
        sections.append(
            BriefingSection(
                name=BriefingSectionName.PREPARATION_NEEDED,
                items=tuple(_preparation_item(record) for record in preparation),
            )
        )

    important_tasks = tuple(
        record
        for record in prioritized_tasks
        if record.id not in used_record_ids
        and (
            record.due_at is None
            or record.due_at.date() <= today
            or record.importance >= 4
        )
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

    future_records = tuple(
        sorted(
            (
                record
                for record in records
                if record.id not in used_record_ids
                and (
                    record.kind is not RecordKind.TASK
                    or record.id in candidate_task_ids
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
            summary=_coverage_summary(context, coverage),
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
        ),
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
) -> str:
    if context.workday_type is WorkdayType.MINISTRY_WORKDAY:
        return _ministry_workday_note(todays_calendar_context)

    if context.is_workday:
        day_label = (
            "flexible half-workday"
            if context.workday_type is WorkdayType.FLEXIBLE_HALF_WORKDAY
            else "workday"
        )
        return f"Today is a {day_label}. {_schedule_summary(todays_calendar_context)}"

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
) -> str:
    if not coverage:
        return "No approved source coverage was supplied."

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
        detail = (
            f"`{report.source}`: {report.status.value}; "
            f"{retrieved} retrieved; {selected} selected; "
            f"{persisted}; {candidates}; {displayed}"
        )
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
        coverage_parts.append(detail)
    if context.workday_diagnostics:
        coverage_parts.append(
            "Workday context: " + " ".join(context.workday_diagnostics)
        )
    return ". ".join(coverage_parts) + "."


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


def _task_is_daily_candidate(
    record: NormalizedRecord,
    context: InvocationContext,
) -> bool:
    if not context.is_workday:
        return False
    due_date = None if record.due_at is None else record.due_at.date()
    if context.workday_type is WorkdayType.MINISTRY_WORKDAY:
        return (
            record.explicit_commitment
            or record.preparation is not None
            or due_date == context.briefing_date
        )
    return (
        record.explicit_commitment
        or record.preparation is not None
        or record.importance >= 4
        or (
            due_date is not None
            and due_date <= context.briefing_date + timedelta(days=7)
        )
    )


def _task_candidate_audits(
    available: tuple[NormalizedRecord, ...],
    candidates: tuple[NormalizedRecord, ...],
    context: InvocationContext,
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
            reason = _task_candidate_exclusion_reason(record, context)
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
) -> str:
    if not context.is_workday:
        return "configured non-workday"
    if context.workday_type is WorkdayType.MINISTRY_WORKDAY:
        return "unrelated to ministry workday"
    return "outside seven-day daily horizon without another priority signal"


def _priority_inputs(record: NormalizedRecord, today: date) -> PriorityInputs:
    due_date = None if record.due_at is None else record.due_at.date()
    return PriorityInputs(
        overdue=due_date is not None and due_date < today,
        due_today=due_date == today,
        calendar_bound_today=(
            record.start_at is not None and record.start_at.date() == today
        ),
        explicit_commitment=record.explicit_commitment,
        preparation_required=record.preparation is not None,
        source_importance=record.importance,
    )


def _priority_sort_key(record: NormalizedRecord, today: date) -> tuple[object, ...]:
    inputs = _priority_inputs(record, today)
    due_at = record.due_at or datetime.max.replace(
        tzinfo=record.provenance.retrieved_at.tzinfo
    )
    return (
        not inputs.due_today,
        not inputs.explicit_commitment,
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
    deadline = (
        "No source deadline."
        if record.due_at is None
        else f"Source deadline: {record.due_at:%A, %B %-d at %-I:%M %p}."
    )
    return BriefingItem(
        key=f"outcome:{record.id}",
        headline=f"Complete {record.title}",
        detail=f"{inputs.explanation()}. {deadline}",
        sources=(_source_link(record),),
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
        headline=record.title,
        detail=detail,
        sources=(_source_link(record),),
    )


def _source_link(record: NormalizedRecord) -> SourceLink:
    return SourceLink(
        source=record.provenance.source,
        source_record_id=record.provenance.source_record_id,
        display_url=record.provenance.display_url,
    )


def _render_source(source: SourceLink) -> str:
    label = f"{source.source}/{source.source_record_id}"
    return label if source.display_url is None else f"[{label}]({source.display_url})"


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))
