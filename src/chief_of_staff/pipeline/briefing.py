"""Structured reduced-briefing composition, rendering, and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from chief_of_staff.connectors import SourceCoverage
from chief_of_staff.pipeline.context import InvocationContext
from chief_of_staff.pipeline.normalization import NormalizedRecord, RecordKind

MAX_WORDS = 1000
PREFERRED_WORDS = 800
MAX_NOTE_WORDS = 150
MAX_OUTCOMES = 3
LIMITED_SECTION_ITEMS = 3


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
class BriefingPlan:
    """Structured content selected before Markdown rendering."""

    context: InvocationContext
    coverage: tuple[SourceCoverage, ...]
    sections: tuple[BriefingSection, ...]
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
    todays_calendar = tuple(
        sorted(
            (
                record
                for record in records
                if record.kind is RecordKind.CALENDAR_EVENT
                and _is_displayable_calendar_event(record)
                and record.start_at is not None
                and record.start_at.date() == today
            ),
            key=lambda record: record.start_at or datetime.max,
        )
    )
    sections: list[BriefingSection] = [
        BriefingSection(
            name=BriefingSectionName.CHIEF_OF_STAFF_NOTE,
            summary=_chief_note(context, todays_calendar),
        )
    ]

    task_records = tuple(
        record
        for record in records
        if context.is_workday
        and record.kind is RecordKind.TASK
        and record.status != "completed"
    )
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

    looking_ahead = tuple(
        sorted(
            (
                record
                for record in records
                if record.id not in used_record_ids
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
    )[:LIMITED_SECTION_ITEMS]
    if looking_ahead:
        sections.append(
            BriefingSection(
                name=BriefingSectionName.LOOKING_AHEAD,
                items=tuple(_looking_ahead_item(record) for record in looking_ahead),
            )
        )

    sections.append(
        BriefingSection(
            name=BriefingSectionName.SOURCE_COVERAGE,
            summary=_coverage_summary(coverage),
        )
    )

    return BriefingPlan(
        context=context,
        coverage=coverage,
        sections=tuple(sections),
    )


def render_briefing(plan: BriefingPlan) -> RenderedBriefing:
    """Render a structured plan as concise Markdown."""

    workday_label = "workday" if plan.context.is_workday else "non-workday"
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
    todays_calendar: tuple[NormalizedRecord, ...],
) -> str:
    day_posture = (
        "Today is a workday."
        if context.is_workday
        else (
            "Today is a non-workday; protect it from ordinary work demands. "
            "Only fixed schedule facts, explicit preparation, and concise "
            "looking-ahead context are shown."
        )
    )
    schedule = _schedule_summary(todays_calendar)
    return f"{day_posture} {schedule}"


def _coverage_summary(coverage: tuple[SourceCoverage, ...]) -> str:
    if not coverage:
        return "No approved source coverage was supplied."

    coverage_parts: list[str] = []
    for report in coverage:
        record_label = "record" if report.record_count == 1 else "records"
        detail = (
            f"`{report.source}`: {report.status.value}; "
            f"{report.record_count} {record_label}"
        )
        if report.warnings:
            detail += f"; {'; '.join(report.warnings)}"
        if report.error_category:
            detail += f"; {report.error_category}"
        coverage_parts.append(detail)
    return ". ".join(coverage_parts) + "."


def classify_calendar_event(
    record: NormalizedRecord,
) -> CalendarEventClassification:
    """Classify a Calendar fact without title-based inference."""

    if record.kind is not RecordKind.CALENDAR_EVENT:
        raise ValueError("calendar classification requires a calendar event")
    if record.all_day:
        return CalendarEventClassification.ALL_DAY_CONTEXT

    status = (record.status or "").casefold()
    if status == "confirmed":
        return CalendarEventClassification.FIXED_COMMITMENT
    if status == "tentative":
        return CalendarEventClassification.TENTATIVE_HOLD
    return CalendarEventClassification.SCHEDULED_EVENT


def _schedule_summary(todays_calendar: tuple[NormalizedRecord, ...]) -> str:
    if not todays_calendar:
        return "No scheduled Calendar items were retrieved for today."

    fixed = tuple(
        record
        for record in todays_calendar
        if classify_calendar_event(record)
        is CalendarEventClassification.FIXED_COMMITMENT
    )
    tentative_count = sum(
        classify_calendar_event(record) is CalendarEventClassification.TENTATIVE_HOLD
        for record in todays_calendar
    )
    all_day_count = sum(
        classify_calendar_event(record) is CalendarEventClassification.ALL_DAY_CONTEXT
        for record in todays_calendar
    )
    unclassified_count = sum(
        classify_calendar_event(record) is CalendarEventClassification.SCHEDULED_EVENT
        for record in todays_calendar
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
        parts.append(
            f"Retrieved Calendar facts show {len(fixed)} fixed {noun}{time_span}."
        )
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


def _is_displayable_calendar_event(record: NormalizedRecord) -> bool:
    return (record.status or "").casefold() != "cancelled"


def _is_outcome_candidate(record: NormalizedRecord, today: date) -> bool:
    return (
        record.explicit_commitment
        or record.importance >= 4
        or (record.due_at is not None and record.due_at.date() <= today)
    )


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
        not inputs.overdue,
        not inputs.due_today,
        not inputs.explicit_commitment,
        -inputs.source_importance,
        due_at,
        record.title.casefold(),
    )


def _future_sort_key(record: NormalizedRecord) -> tuple[datetime, str]:
    future_at = record.start_at or record.due_at
    if future_at is None:
        future_at = datetime.max.replace(tzinfo=record.provenance.retrieved_at.tzinfo)
    return future_at, record.title.casefold()


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
