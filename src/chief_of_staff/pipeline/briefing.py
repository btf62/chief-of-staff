"""Structured reduced-briefing composition, rendering, and validation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from itertools import pairwise
from zoneinfo import ZoneInfo

from chief_of_staff.connectors import SourceCoverage
from chief_of_staff.domain import (
    ConnectorDomain,
    CoverageStatus,
    RecurrenceDecision,
)
from chief_of_staff.pipeline.context import (
    HistoricalMode,
    InvocationContext,
    WorkdayType,
)
from chief_of_staff.pipeline.normalization import (
    AssociatedSourceFacts,
    NormalizedRecord,
    Provenance,
    RecordKind,
    record_completion_state,
)
from chief_of_staff.pipeline.ranking import (
    PriorityBand,
    RankedCandidate,
    RankingFactorKind,
    SuppressedCandidate,
    rank_candidates,
)

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
MAX_SAFE_SOURCE_TITLE_CHARACTERS = 500
UNTRUSTED_PRIORITY_INSTRUCTION = re.compile(
    r"\b(?:ignore (?:policy|instructions)|"
    r"make (?:this|me) (?:the )?(?:top|highest) priority|"
    r"override (?:the )?(?:ranking|priority))\b",
    flags=re.IGNORECASE,
)


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
    DECLINED_INVITATION = "Declined invitation"
    SCHEDULED_EVENT = "Scheduled event"


class BriefingContentKind(StrEnum):
    """Semantic role of planned content before presentation rendering."""

    AUTHORITATIVE_FACT = "authoritative_source_fact"
    EXPLICIT_DETECTION = "explicit_detection"
    INFERRED_CONCLUSION = "inferred_conclusion"
    RECOMMENDATION = "recommendation"
    PRESENTATION_SYNTHESIS = "presentation_only_synthesis"


class TemporalState(StrEnum):
    """Written and visual state for one selected-day time-bound item."""

    EARLIER_TODAY = "Earlier today"
    IN_PROGRESS = "In progress"
    UPCOMING = "Upcoming"


@dataclass(frozen=True, slots=True)
class SourceLink:
    """Source authority attached to one briefing item."""

    source: str
    source_record_id: str
    display_url: str | None
    connector_instance_id: str | None = None
    account_alias: str | None = None
    domain_classification: ConnectorDomain | None = None


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
    content_kind: BriefingContentKind = BriefingContentKind.AUTHORITATIVE_FACT
    inference_explanation: str | None = None
    uncertainty: str | None = None
    sort_at: datetime | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    all_day: bool = False
    temporal_state: TemporalState | None = None
    priority_band: PriorityBand | None = None
    ranking_factor_kinds: tuple[str, ...] = ()


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
    connector_instance_id: str | None = None


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
class ChiefOfStaffNoteInputs:
    """Supported facts and recommendations available to deterministic synthesis."""

    workday_type: WorkdayType
    fixed_commitment_ids: tuple[str, ...]
    primary_outcome_id: str | None
    focus_window: tuple[datetime, datetime] | None
    tomorrow_sequence_ids: tuple[str, ...]
    workday_diagnostics: tuple[str, ...]
    todoist_ranking_degraded: bool
    unresolved_conflict_record_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SuppressedDuplicate:
    """Presentation-level suppression that preserves every source record."""

    representative_record_id: str
    suppressed_record_id: str
    sources: tuple[SourceLink, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class PlanConflict:
    """Material disagreement retained for presentation and review."""

    record_id: str
    conflicting_fields: tuple[str, ...]
    sources: tuple[SourceLink, ...]
    claims: tuple[ConflictClaim, ...] = ()


@dataclass(frozen=True, slots=True)
class ConflictClaim:
    """One attributed source value participating in a material conflict."""

    field: str
    source: SourceLink
    value: str
    freshness_at: datetime | None


@dataclass(frozen=True, slots=True)
class BriefingPlan:
    """Structured content selected before Markdown rendering."""

    context: InvocationContext
    coverage: tuple[SourceCoverage, ...]
    sections: tuple[BriefingSection, ...]
    ordered_eligible_candidates: tuple[RankedCandidate, ...] = ()
    selected_outcome_ids: tuple[str, ...] = ()
    note_inputs: ChiefOfStaffNoteInputs | None = None
    suppressed_duplicates: tuple[SuppressedDuplicate, ...] = ()
    suppressed_by_correction: tuple[SuppressedCandidate, ...] = ()
    unresolved_conflicts: tuple[PlanConflict, ...] = ()
    coverage_warnings: tuple[str, ...] = ()
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
    *,
    recurrence_decisions: Mapping[str, RecurrenceDecision] | None = None,
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
    conclusion_records = tuple(
        record
        for record in records
        if record.kind
        in {
            RecordKind.WAITING_ITEM,
            RecordKind.COMMITMENT,
            RecordKind.PREPARATION_ITEM,
        }
        and _is_presentable_conclusion(record)
    )
    candidate_task_ids = {record.id for record in task_records}
    focus_window = _recommended_focus_window(todays_calendar_context, context)
    ranking = rank_candidates(
        (*task_records, *conclusion_records),
        briefing_date=today,
        recurrence_decisions=recurrence_decisions,
        available_calendar_window=(
            None
            if focus_window is None
            else (focus_window.starts_at, focus_window.ends_at)
        ),
    )
    ranked_by_id = {candidate.record.id: candidate for candidate in ranking.ordered}
    prioritized_tasks = [
        candidate.record
        for candidate in ranking.ordered
        if candidate.record.kind is RecordKind.TASK
    ]
    ranked_conclusions = tuple(
        candidate.record
        for candidate in ranking.ordered
        if candidate.record.kind
        in {
            RecordKind.WAITING_ITEM,
            RecordKind.COMMITMENT,
            RecordKind.PREPARATION_ITEM,
        }
    )
    suppressed_duplicates = _presentation_duplicate_suppressions(
        prioritized_tasks,
        today,
    )
    prioritized_tasks = _collapse_associated_task_candidates(
        prioritized_tasks,
        today,
    )
    outcome_candidates = tuple(
        record
        for record in prioritized_tasks
        if ranked_by_id[record.id].band
        in {
            PriorityBand.CRITICAL,
            PriorityBand.TODAY,
        }
        and _is_outcome_candidate(record, today)
    )[:MAX_OUTCOMES]
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
                    _outcome_item(
                        record,
                        today,
                        ranked_by_id[record.id],
                    )
                    for record in outcome_candidates
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
    explicit_preparation = tuple(
        record
        for record in ranked_conclusions
        if record.kind is RecordKind.PREPARATION_ITEM and record.preparation is not None
    )
    preparation = (*calendar_preparation, *task_preparation, *explicit_preparation)
    if preparation:
        sections.append(
            BriefingSection(
                name=BriefingSectionName.PREPARATION_NEEDED,
                items=tuple(_preparation_item(record) for record in preparation),
            )
        )

    people_waiting = tuple(
        sorted(
            (
                record
                for record in ranked_conclusions
                if record.kind is RecordKind.WAITING_ITEM
            ),
            key=_email_conclusion_sort_key,
        )
    )[:LIMITED_SECTION_ITEMS]
    if people_waiting:
        sections.append(
            BriefingSection(
                name=BriefingSectionName.PEOPLE_WAITING,
                items=tuple(_email_waiting_item(record) for record in people_waiting),
            )
        )
        used_record_ids.update(record.id for record in people_waiting)

    jira_commitments_at_risk = tuple(
        record
        for record in prioritized_tasks
        if record.id not in used_record_ids
        and record.provenance.source == "jira"
        and record.source_owned_risk
    )
    email_commitments_at_risk = tuple(
        record for record in ranked_conclusions if record.kind is RecordKind.COMMITMENT
    )
    commitments_at_risk = tuple(
        sorted(
            (*email_commitments_at_risk, *jira_commitments_at_risk),
            key=lambda record: (
                record.due_at
                or datetime.max.replace(tzinfo=record.provenance.retrieved_at.tzinfo),
                record.title.casefold(),
            ),
        )
    )[:LIMITED_SECTION_ITEMS]
    if commitments_at_risk:
        sections.append(
            BriefingSection(
                name=BriefingSectionName.COMMITMENTS_AT_RISK,
                items=tuple(
                    _email_commitment_risk_item(record, today)
                    if record.kind is RecordKind.COMMITMENT
                    else _jira_risk_item(record)
                    for record in commitments_at_risk
                ),
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
                and record.kind
                in {
                    RecordKind.CALENDAR_EVENT,
                    RecordKind.TASK,
                    RecordKind.CONTEXT,
                }
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

    conflicts = tuple(
        PlanConflict(
            record_id=record.id,
            conflicting_fields=record.association_conflicts,
            sources=_source_links(record),
            claims=_conflict_claims(record, today),
        )
        for record in records
        if record.association_conflicts
    )
    note_inputs = ChiefOfStaffNoteInputs(
        workday_type=context.workday_type,
        fixed_commitment_ids=tuple(
            record.id
            for record in todays_calendar_context
            if classify_calendar_event(record)
            is CalendarEventClassification.FIXED_COMMITMENT
        ),
        primary_outcome_id=(
            None if not outcome_candidates else outcome_candidates[0].id
        ),
        focus_window=(
            None
            if focus_window is None
            else (focus_window.starts_at, focus_window.ends_at)
        ),
        tomorrow_sequence_ids=tuple(record.id for record in tomorrow_sequence),
        workday_diagnostics=context.workday_diagnostics,
        todoist_ranking_degraded=bool(
            todoist_confidence is not None
            and todoist_confidence.relative_ranking_degraded
        ),
        unresolved_conflict_record_ids=tuple(
            conflict.record_id for conflict in conflicts
        ),
    )
    return BriefingPlan(
        context=context,
        coverage=coverage,
        sections=tuple(
            _with_temporal_states(section, context=context) for section in sections
        ),
        ordered_eligible_candidates=ranking.ordered,
        selected_outcome_ids=tuple(record.id for record in outcome_candidates),
        note_inputs=note_inputs,
        suppressed_duplicates=suppressed_duplicates,
        suppressed_by_correction=ranking.suppressed,
        unresolved_conflicts=conflicts,
        coverage_warnings=_coverage_warnings(coverage),
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
        _generated_at_line(plan.context),
        "",
        f"_Deterministic reduced mode · {workday_label} "
        f"({plan.context.workday_reason})_",
    ]
    historical_disclosure = _historical_disclosure(plan.context)
    if historical_disclosure is not None:
        lines.extend(("", historical_disclosure))
    for section in plan.sections:
        lines.extend(("", f"## {section.name}"))
        if section.summary:
            lines.extend(("", section.summary))
        for item in section.items:
            sources = "; ".join(_render_source(source) for source in item.sources)
            state = (
                "" if item.temporal_state is None else f"{item.temporal_state.value} · "
            )
            lines.extend(
                (
                    "",
                    f"- **{state}{item.headline}** — {item.detail} Source: {sources}",
                )
            )

    text = "\n".join(lines).rstrip() + "\n"
    return RenderedBriefing(text=text, word_count=_word_count(text))


def _with_temporal_states(
    section: BriefingSection,
    *,
    context: InvocationContext,
) -> BriefingSection:
    items: list[BriefingItem] = []
    for item in section.items:
        state = _temporal_state(item, context=context)
        detail = item.detail
        if (
            section.name is BriefingSectionName.RECOMMENDED_FOCUS_BLOCK
            and state is not None
            and item.ends_at is not None
        ):
            if state is TemporalState.IN_PROGRESS:
                remaining = max(
                    0,
                    int(
                        (
                            item.ends_at - context.as_of.astimezone(item.ends_at.tzinfo)
                        ).total_seconds()
                        // 60
                    ),
                )
                timing = (
                    "In progress when generated"
                    f" · approximately {remaining} minutes remained."
                )
            elif state is TemporalState.EARLIER_TODAY:
                timing = (
                    "Earlier opportunity · elapsed before this briefing was generated."
                )
            else:
                timing = "Upcoming when generated."
            detail = f"{timing} {detail}"
        items.append(replace(item, detail=detail, temporal_state=state))
    return replace(section, items=tuple(items))


def _temporal_state(
    item: BriefingItem,
    *,
    context: InvocationContext,
) -> TemporalState | None:
    if item.starts_at is None or item.all_day:
        return None
    starts_at = item.starts_at
    if starts_at.date() != context.briefing_date:
        return None
    effective = context.as_of.astimezone(starts_at.tzinfo)
    if item.ends_at is not None and item.ends_at <= effective:
        return TemporalState.EARLIER_TODAY
    if starts_at <= effective and (item.ends_at is None or effective < item.ends_at):
        return TemporalState.IN_PROGRESS
    return TemporalState.UPCOMING


def _generated_at_line(context: InvocationContext) -> str:
    generated = context.generated_at.astimezone(ZoneInfo(context.timezone))
    clock, period = _natural_clock(generated)
    return f"_Generated {generated:%A, %B %-d} at {clock} {period}_"


def _historical_disclosure(context: InvocationContext) -> str | None:
    generated = context.generated_at.astimezone(ZoneInfo(context.timezone))
    if context.historical_mode is HistoricalMode.RECORDED:
        return "_Recorded briefing · shown exactly as originally generated._"
    if context.historical_mode is HistoricalMode.REPLAY:
        return (
            "_Replay using current product logic and archived normalized facts. "
            "This is not the briefing originally shown._"
        )
    if context.historical_mode is HistoricalMode.RECONSTRUCTED:
        return (
            f"_Reconstructed on {generated:%A, %B %-d} from available source "
            "history. Later source changes and unavailable historical state may "
            "affect accuracy._"
        )
    if context.historical_mode is HistoricalMode.SYNTHETIC:
        return "_Synthetic evaluation scenario · no live personal data._"
    return None


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
    if plan.note_inputs is None:
        errors.append("Chief of Staff Note inputs are missing")
    if rendered.word_count > MAX_WORDS:
        errors.append("briefing exceeds the 1,000-word maximum")
    if len(plan.selected_outcome_ids) > MAX_OUTCOMES:
        errors.append("structured plan selects more than three outcomes")

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
            if item.content_kind is BriefingContentKind.INFERRED_CONCLUSION and (
                not item.inference_explanation or not item.uncertainty
            ):
                errors.append(
                    f"{item.key} is inferred without explanation and uncertainty"
                )
            seen_keys.add(item.key)

    calendar_section = next(
        (
            section
            for section in plan.sections
            if section.name is BriefingSectionName.TODAYS_CALENDAR
        ),
        None,
    )
    if calendar_section is not None:
        calendar_times = [
            item.sort_at for item in calendar_section.items if item.sort_at is not None
        ]
        if calendar_times != sorted(calendar_times):
            errors.append("Calendar items are not chronological")

    if any(len(item.sources) < 2 for item in plan.suppressed_duplicates):
        errors.append("duplicate suppression must preserve every source link")
    for conflict in plan.unresolved_conflicts:
        if len(conflict.sources) < 2:
            errors.append(f"{conflict.record_id} conflict lacks source links")
        claimed_fields = {claim.field for claim in conflict.claims}
        if not set(conflict.conflicting_fields).issubset(claimed_fields):
            errors.append(f"{conflict.record_id} conflict lacks attributed values")

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
        label = _coverage_label(source)
        if label not in coverage_text:
            errors.append(f"coverage for {label} is not disclosed")

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
        detail_parts = [
            f"`{_coverage_label(report)}`: {report.status.value}",
            f"{retrieved} retrieved",
            f"{selected} selected",
        ]
        if report.persisted_count is not None:
            detail_parts.append(f"{report.persisted_count} persisted")
        if report.candidate_count is not None:
            detail_parts.append(_count_phrase(report.candidate_count, "candidate"))
        if report.displayed_count is not None:
            detail_parts.append(f"{report.displayed_count} displayed")
        if report.page_count is not None:
            page_noun = "page" if report.page_count == 1 else "pages"
            detail_parts.append(f"{report.page_count} {page_noun}")
        if report.context_resources:
            context_resources = report.context_resources
            if len(context_resources) > 8:
                context_resources = tuple(
                    resource
                    for resource in context_resources
                    if resource.resource
                    in {
                        "eligible body candidates",
                        "selected body candidates",
                        "omitted body candidates",
                        "usable candidate bodies",
                        "bodies unavailable or unsupported",
                        "explicit detections",
                    }
                )
            resources = ", ".join(
                (
                    f"{resource.resource} {resource.retrieved_count}"
                    + (
                        ""
                        if resource.persisted_count is None
                        else f"/{resource.persisted_count}"
                    )
                )
                for resource in context_resources
            )
            if resources:
                detail_parts.append(f"context retrieved/persisted: {resources}")
        boundary = _coverage_boundary_disclosure(report)
        if boundary is not None:
            detail_parts.append(boundary)
        planning_confidence = confidence_by_source.get(report.source)
        if planning_confidence is not None:
            status = (
                "degraded"
                if planning_confidence.relative_ranking_degraded
                else "not degraded"
            )
            detail_parts.append(
                f"ranking {status}: "
                f"{planning_confidence.overdue_count}/"
                f"{planning_confidence.active_count} overdue, "
                f"{planning_confidence.high_priority_count}/"
                f"{planning_confidence.active_count} P1/P2"
            )
        coverage_parts.append("; ".join(detail_parts))
    if context.workday_diagnostics:
        coverage_parts.append(
            "Workday context: " + " ".join(context.workday_diagnostics)
        )
    return ". ".join(coverage_parts) + "."


def _coverage_warnings(
    coverage: tuple[SourceCoverage, ...],
) -> tuple[str, ...]:
    warnings: list[str] = []
    for report in coverage:
        label = _coverage_label(report)
        if report.status is not CoverageStatus.COMPLETE:
            warnings.append(f"{label}: {report.status.value}")
        if report.error_category is not None:
            warnings.append(f"{label}: {report.error_category}")
        warnings.extend(f"{label}: {warning}" for warning in report.warnings)
    return tuple(warnings)


def _coverage_boundary_disclosure(report: SourceCoverage) -> str | None:
    """Keep partial/failure disclosure plain without reproducing audit detail."""

    if report.status is CoverageStatus.COMPLETE:
        return None
    if report.error_category == "bounded_body_candidate_selection":
        return "partial at the bounded Gmail body-selection cap"
    if report.error_category == "extracted_content_boundary":
        return "partial at the Gmail extracted-content limit"
    if report.error_category == "partial_message_retrieval":
        return "partial because some Gmail content was unavailable or unsupported"
    if report.error_category:
        return f"boundary: {report.error_category}"
    if report.warnings:
        return report.warnings[0]
    return None


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
        if primary_outcome.association_conflicts:
            fields = _natural_join(primary_outcome.association_conflicts)
            parts.append(
                f"Strongest supported outcome: {_display_title(primary_outcome)}. "
                f"The associated sources disagree about {fields}"
                + (
                    ", and one authoritative source reports an immediate deadline."
                    if _has_immediate_conflicting_due_date(
                        primary_outcome,
                        context.briefing_date,
                    )
                    else "."
                )
            )
            parts.append(
                "Verify the source records before relying on a disputed value."
            )
        else:
            parts.append(
                f"Strongest supported outcome: {_display_title(primary_outcome)}, "
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
    response_status = (record.self_response_status or "").casefold()
    if response_status == "declined":
        return CalendarEventClassification.DECLINED_INVITATION
    if record.all_day:
        return CalendarEventClassification.ALL_DAY_CONTEXT

    status = (record.status or "").casefold()
    if response_status == "tentative" or status == "tentative":
        return CalendarEventClassification.TENTATIVE_HOLD
    if response_status == "needsaction":
        return CalendarEventClassification.SCHEDULED_EVENT
    if status == "confirmed":
        return CalendarEventClassification.FIXED_COMMITMENT
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
        parts.append(_fixed_schedule_summary(fixed))
        parts.extend(_schedule_implications(fixed))
    if tentative_count:
        verb = "remains" if tentative_count == 1 else "remain"
        parts.append(
            f"{_count_phrase(tentative_count, 'tentative hold')} {verb} non-fixed."
        )
    if unclassified_count:
        verb = "lacks" if unclassified_count == 1 else "lack"
        parts.append(
            f"{_count_phrase(unclassified_count, 'scheduled event')} {verb} "
            "enough status evidence "
            "to call fixed."
        )
    if all_day_count:
        verb = "is" if all_day_count == 1 else "are"
        parts.append(
            f"{_count_phrase(all_day_count, 'all-day item')} {verb} "
            "treated as context, not full-day "
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

    gap_minutes = _positive_gap_minutes(fixed)
    shape = _fixed_schedule_summary(fixed)

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


def _fixed_schedule_summary(
    fixed_events: tuple[NormalizedRecord, ...],
) -> str:
    """Describe separate fixed blocks without implying continuous occupancy."""

    fixed = tuple(
        sorted(
            (
                record
                for record in fixed_events
                if record.start_at is not None and record.end_at is not None
            ),
            key=lambda record: record.start_at or datetime.max,
        )
    )
    if not fixed:
        return "No timed fixed Calendar commitment requires attention today."

    total_minutes = _scheduled_union_minutes(fixed)
    if len(fixed) == 1:
        record = fixed[0]
        if record.start_at is None or record.end_at is None:
            raise ValueError("fixed Calendar summary requires complete timing")
        return _terminate_sentence(
            f"{_count_phrase(1, 'Calendar commitment')} occupies "
            f"{_duration_phrase(total_minutes)} from "
            f"{_natural_time_span(record.start_at, record.end_at)}"
        )

    first_start = fixed[0].start_at
    last_end = max(record.end_at for record in fixed if record.end_at is not None)
    if first_start is None:
        raise ValueError("fixed Calendar summary requires a start time")
    gaps = _positive_gap_minutes(fixed)
    summary = (
        f"{_count_phrase(len(fixed), 'separate Calendar commitment')} occupy "
        f"{_duration_phrase(total_minutes)} between "
        f"{_natural_clock_text(first_start)} and {_natural_clock_text(last_end)}"
    )
    if len(gaps) == 1:
        summary += (
            f", with {_count_phrase(1, 'gap')} lasting {_duration_phrase(gaps[0])}"
        )
    elif gaps:
        summary += (
            f", with {_count_phrase(len(gaps), 'gap')} totaling "
            f"{_duration_phrase(sum(gaps))}"
        )
    return _terminate_sentence(summary)


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


def _count_phrase(count: int, singular: str, plural: str | None = None) -> str:
    """Format a count with reusable singular and plural grammar."""

    noun = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {noun}"


def _terminate_sentence(value: str) -> str:
    return value if value.endswith(".") else value + "."


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
    return (record.status or "").casefold() != "cancelled" and (
        record.self_response_status or ""
    ).casefold() != "declined"


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


def _is_presentable_conclusion(record: NormalizedRecord) -> bool:
    if record.status == "explicit":
        return True
    return bool(
        record.status == "inferred"
        and record.inference_explanation
        and record.uncertainty == "low"
    )


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
    due_detail = (
        "Associated sources report different due dates; verify them before "
        "scheduling this work."
        if "due date" in record.association_conflicts
        else _source_due_sentence(record, today)
    )
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
    if _contains_untrusted_priority_instruction(record):
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


def _presentation_duplicate_suppressions(
    records: list[NormalizedRecord],
    today: date,
) -> tuple[SuppressedDuplicate, ...]:
    candidates = {record.id: record for record in records}
    decisions: dict[tuple[str, str], SuppressedDuplicate] = {}
    for record in records:
        related = tuple(
            candidates[related_id]
            for related_id in record.related_source_ids
            if related_id in candidates
        )
        if not related:
            continue
        representative = min(
            (record, *related),
            key=lambda candidate: _priority_sort_key(candidate, today),
        )
        for duplicate in (record, *related):
            if duplicate.id == representative.id:
                continue
            key = (representative.id, duplicate.id)
            decisions[key] = SuppressedDuplicate(
                representative_record_id=representative.id,
                suppressed_record_id=duplicate.id,
                sources=tuple(
                    dict.fromkeys(
                        (*_source_links(representative), *_source_links(duplicate))
                    )
                ),
                reason=(
                    "Strong explicit cross-source association supports one visible "
                    "recommendation while retaining both authoritative records."
                ),
            )
    return tuple(decisions[key] for key in sorted(decisions))


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
    sources = sorted(
        {
            (
                record.provenance.source,
                record.provenance.connector_instance_id or "",
            )
            for record in available
        }
    )
    audits: list[TaskCandidateAudit] = []
    for source, instance_id in sources:
        source_records = tuple(
            record
            for record in available
            if record.provenance.source == source
            and (record.provenance.connector_instance_id or "") == instance_id
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
                connector_instance_id=instance_id or None,
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
    if _contains_untrusted_priority_instruction(record):
        return "untrusted source content attempted to direct ranking"
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


def _contains_untrusted_priority_instruction(record: NormalizedRecord) -> bool:
    candidate_text = " ".join(
        value for value in (record.title, record.summary) if value is not None
    )
    return UNTRUSTED_PRIORITY_INSTRUCTION.search(candidate_text) is not None


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
                content_kind=BriefingContentKind.RECOMMENDATION,
                starts_at=focus_window.starts_at,
                ends_at=focus_window.ends_at,
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


def _outcome_item(
    record: NormalizedRecord,
    today: date,
    ranked: RankedCandidate,
) -> BriefingItem:
    inputs = _priority_inputs(record, today)
    deadline = (
        _conflict_detail(record, today)
        if record.association_conflicts
        else _source_due_sentence(record, today)
    )
    ranking_reason = _visible_ranking_reason(ranked)
    return BriefingItem(
        key=f"outcome:{record.id}",
        headline=_display_title(record),
        detail=(
            f"{ranking_reason} {deadline}"
            + (_association_detail(record) if not record.association_conflicts else "")
        ),
        sources=_source_links(record),
        priority_inputs=inputs,
        content_kind=BriefingContentKind.RECOMMENDATION,
        priority_band=ranked.band,
        ranking_factor_kinds=tuple(factor.kind.value for factor in ranked.factors),
    )


def _visible_ranking_reason(candidate: RankedCandidate) -> str:
    conflict_fields = set(candidate.record.association_conflicts)
    factor_kinds = {factor.kind for factor in candidate.factors}
    labels = {
        RankingFactorKind.CALENDAR_OBLIGATION: "it is tied to today's Calendar",
        RankingFactorKind.PREPARATION_DEPENDENCY: (
            "it is required preparation for another commitment"
        ),
        RankingFactorKind.PERSON_OR_TEAM_BLOCKED: ("another person or team is blocked"),
        RankingFactorKind.PRIMARY_STEWARDSHIP: (
            "it falls within Brad's primary stewardship"
        ),
        RankingFactorKind.MINISTRY_OR_RELATIONSHIP_CONSEQUENCE: (
            "it carries a ministry or relationship consequence"
        ),
        RankingFactorKind.SIX_MONTH_GOAL: "it advances an official six-month goal",
        RankingFactorKind.SEASONAL_INITIATIVE: (
            "it advances a current seasonal initiative"
        ),
        RankingFactorKind.BLOCKER_OR_DEPENDENCY: (
            "it has a documented blocker or dependency"
        ),
        RankingFactorKind.DELEGATION: "the source identifies a delegation opportunity",
        RankingFactorKind.SUPPORTED_EFFORT: ("the source supplies an effort estimate"),
        RankingFactorKind.AVAILABLE_CALENDAR_WINDOW: (
            "its supported effort fits the available Calendar window"
        ),
        RankingFactorKind.ENERGY_PATTERN: (
            "its documented energy need fits the morning"
        ),
        RankingFactorKind.OPPORTUNITY_COST: (
            "the source identifies a meaningful opportunity cost"
        ),
    }
    reasons: list[str] = []
    for factor in candidate.factors:
        if factor.kind is RankingFactorKind.HARD_DEADLINE:
            reasons.append(
                "one authoritative source marks its reported deadline as hard"
                if "due date" in conflict_fields
                else "it has a hard deadline"
            )
        elif factor.kind is RankingFactorKind.DUE_DATE:
            if RankingFactorKind.HARD_DEADLINE not in factor_kinds:
                reasons.append(
                    "one authoritative source reports an immediate deadline"
                    if "due date" in conflict_fields
                    else "its deadline makes it time-sensitive"
                )
        elif label := labels.get(factor.kind):
            reasons.append(label)
    reasons = list(dict.fromkeys(reasons))
    if not reasons:
        return "Current source evidence supports attention today."
    return f"This deserves attention today because {_natural_join(tuple(reasons))}."


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


def _email_waiting_item(record: NormalizedRecord) -> BriefingItem:
    detail = record.summary or "A direct request has no later bounded reply."
    if record.status == "inferred":
        detail = (
            f"Inferred with {record.uncertainty} uncertainty: "
            f"{record.inference_explanation} {detail}"
        )
    return _record_item(
        record,
        key_prefix="gmail-waiting",
        detail=detail,
    )


def _email_commitment_risk_item(
    record: NormalizedRecord,
    today: date,
) -> BriefingItem:
    explanation = record.summary or "An explicit sent commitment is at risk."
    if record.status == "inferred":
        explanation = (
            f"Inferred with {record.uncertainty} uncertainty: "
            f"{record.inference_explanation} {explanation}"
        )
    return _record_item(
        record,
        key_prefix="gmail-commitment-risk",
        detail=f"{explanation} It is {_brief_due_phrase(record, today)}.",
    )


def _email_conclusion_sort_key(record: NormalizedRecord) -> tuple[object, ...]:
    return (
        -record.importance,
        -record.provenance.freshness_at.timestamp()
        if record.provenance.freshness_at is not None
        else 0,
        record.title.casefold(),
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
    if record.preparation is not None:
        detail += f" Preparation: {record.preparation}"
    return _record_item(record, key_prefix="ahead", detail=detail)


def _record_item(
    record: NormalizedRecord,
    *,
    key_prefix: str,
    detail: str,
) -> BriefingItem:
    if record.status == "inferred":
        content_kind = BriefingContentKind.INFERRED_CONCLUSION
    elif record.kind in {
        RecordKind.WAITING_ITEM,
        RecordKind.COMMITMENT,
        RecordKind.PREPARATION_ITEM,
    }:
        content_kind = BriefingContentKind.EXPLICIT_DETECTION
    else:
        content_kind = BriefingContentKind.AUTHORITATIVE_FACT
    return BriefingItem(
        key=f"{key_prefix}:{record.id}",
        headline=_display_title(record),
        detail=detail + _association_detail(record),
        sources=_source_links(record),
        content_kind=content_kind,
        inference_explanation=record.inference_explanation,
        uncertainty=record.uncertainty,
        sort_at=record.start_at,
        starts_at=record.start_at,
        ends_at=record.end_at,
        all_day=record.all_day,
    )


def _display_title(record: NormalizedRecord) -> str:
    cleaned = (
        CONTROL_TOKEN.sub("", record.title)
        if record.kind is RecordKind.TASK
        else record.title
    )
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" \t-:;")
    cleaned = safe_source_title(cleaned)
    return cleaned or f"{record.provenance.source} item"


def safe_source_title(value: str) -> str:
    """Present link-like untrusted text without interpreting markup or URLs."""

    bounded = "".join(
        character
        for character in value
        if character in {"\n", "\t"} or ord(character) >= 32
    )
    output: list[str] = []
    index = 0
    while index < len(bounded):
        if bounded[index] != "[":
            output.append(bounded[index])
            index += 1
            continue
        label_end = _balanced_closing(bounded, index, "[", "]")
        if (
            label_end is None
            or label_end + 1 >= len(bounded)
            or bounded[label_end + 1] != "("
        ):
            output.append("[")
            index += 1
            continue
        url_end = _balanced_closing(bounded, label_end + 1, "(", ")")
        if url_end is None:
            output.append("[")
            index += 1
            continue
        label = bounded[index + 1 : label_end]
        output.append(safe_source_title(label))
        index = url_end + 1
    safe = (
        "".join(output)
        .replace("<", "\N{FULLWIDTH LESS-THAN SIGN}")
        .replace(">", "\N{FULLWIDTH GREATER-THAN SIGN}")
    )
    safe = re.sub(r"\s+", " ", safe).strip()
    if len(safe) <= MAX_SAFE_SOURCE_TITLE_CHARACTERS:
        return safe
    return safe[: MAX_SAFE_SOURCE_TITLE_CHARACTERS - 1].rstrip() + "…"


def _balanced_closing(
    value: str,
    start: int,
    opening: str,
    closing: str,
) -> int | None:
    depth = 0
    for index in range(start, len(value)):
        character = value[index]
        if character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


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
    if "due date" in record.association_conflicts:
        return _conflict_detail(record, today)
    if record.due_at is None:
        return "No source deadline is recorded."
    due_date = record.due_at.date()
    if due_date == today:
        if record.all_day:
            return "The due date is today."
        return f"The deadline is today at {record.due_at:%-I:%M %p}."
    if due_date < today:
        if record.all_day:
            return f"The due date was {record.due_at:%A, %B %-d}."
        return f"The deadline was {record.due_at:%A, %B %-d at %-I:%M %p}."
    if record.all_day:
        return f"The due date is {record.due_at:%A, %B %-d}."
    return f"The deadline is {record.due_at:%A, %B %-d at %-I:%M %p}."


def _source_link(record: NormalizedRecord) -> SourceLink:
    return _provenance_link(record.provenance)


def _provenance_link(provenance: Provenance) -> SourceLink:
    return SourceLink(
        source=provenance.source,
        source_record_id=provenance.source_record_id,
        display_url=provenance.display_url,
        connector_instance_id=provenance.connector_instance_id,
        account_alias=provenance.account_alias,
        domain_classification=provenance.domain_classification,
    )


def _source_links(record: NormalizedRecord) -> tuple[SourceLink, ...]:
    links = [_source_link(record)]
    links.extend(_provenance_link(item) for item in record.associated_provenance)
    return tuple(links)


def _association_detail(record: NormalizedRecord) -> str:
    if not record.associated_provenance:
        return ""
    if record.association_conflicts:
        return " " + _conflict_detail(record, None)
    return " Explicitly associated source records support one combined item."


def _conflict_detail(record: NormalizedRecord, today: date | None) -> str:
    """Attribute each conflicting value and recommend safe reconciliation."""

    claims = _conflict_claims(record, today)
    statements: list[str] = []
    for field in record.association_conflicts:
        field_claims = tuple(claim for claim in claims if claim.field == field)
        if len(field_claims) < 2:
            continue
        reports = tuple(
            f"{_source_label(claim.source)} reports {claim.value}"
            for claim in field_claims
        )
        statements.append(_natural_join(reports, conjunction="while") + ".")

    freshness = _supported_freshness_sentence(record)
    if freshness is not None:
        statements.append(freshness)
    statements.append(
        "Each source remains authoritative for its own record; "
        + (
            "verify the conflict before planning the work."
            if today is not None and _has_immediate_conflicting_due_date(record, today)
            else "verify the conflicting values before relying on them."
        )
    )
    return " ".join(statements)


def _conflict_claims(
    record: NormalizedRecord,
    today: date | None,
) -> tuple[ConflictClaim, ...]:
    snapshots = (_record_source_facts(record), *record.associated_source_facts)
    claims: list[ConflictClaim] = []
    for field in record.association_conflicts:
        for snapshot in snapshots:
            value = _conflict_value(snapshot, field, today)
            if value is None:
                continue
            claims.append(
                ConflictClaim(
                    field=field,
                    source=_provenance_link(snapshot.provenance),
                    value=value,
                    freshness_at=snapshot.provenance.freshness_at,
                )
            )
    return tuple(claims)


def _record_source_facts(record: NormalizedRecord) -> AssociatedSourceFacts:
    return AssociatedSourceFacts(
        provenance=record.provenance,
        status=record.status,
        status_category=record.status_category,
        assignee_reference=record.assignee_reference,
        due_at=record.due_at,
        all_day=record.all_day,
        source_priority=record.source_priority,
        provider_priority=record.provider_priority,
        completion_state=record_completion_state(record),
    )


def _conflict_value(
    facts: AssociatedSourceFacts,
    field: str,
    today: date | None,
) -> str | None:
    if field == "due date" and facts.due_at is not None:
        return "the due date as " + _attributed_due_text(
            facts.due_at,
            all_day=facts.all_day,
            today=today,
        )
    if field == "owner" and facts.assignee_reference is not None:
        return f"the owner as {facts.assignee_reference}"
    if field == "status":
        status = facts.status_category or facts.status
        return None if status is None else f"the status as {status}"
    if field == "priority":
        priority = (
            facts.source_priority
            if facts.source_priority is not None
            else facts.provider_priority
        )
        return None if priority is None else f"the priority as {priority}"
    if field == "completion" and facts.completion_state is not None:
        completion = "completed" if facts.completion_state else "not completed"
        return f"the item as {completion}"
    return None


def _attributed_due_text(
    due_at: datetime,
    *,
    all_day: bool,
    today: date | None,
) -> str:
    if today is not None and due_at.date() == today:
        return "today" if all_day else f"today at {due_at:%-I:%M %p}"
    if all_day:
        return f"{due_at:%A, %B %-d}"
    return f"{due_at:%A, %B %-d at %-I:%M %p}"


def _has_immediate_conflicting_due_date(
    record: NormalizedRecord,
    today: date,
) -> bool:
    if "due date" not in record.association_conflicts:
        return False
    due_dates = tuple(
        facts.due_at.date()
        for facts in (_record_source_facts(record), *record.associated_source_facts)
        if facts.due_at is not None
    )
    return any(due_date <= today for due_date in due_dates)


def _supported_freshness_sentence(record: NormalizedRecord) -> str | None:
    snapshots = (_record_source_facts(record), *record.associated_source_facts)
    if len(snapshots) < 2 or any(
        facts.provenance.freshness_at is None for facts in snapshots
    ):
        return None
    newest_at = max(
        facts.provenance.freshness_at
        for facts in snapshots
        if facts.provenance.freshness_at is not None
    )
    newest = tuple(
        facts for facts in snapshots if facts.provenance.freshness_at == newest_at
    )
    if len(newest) != 1 or all(
        facts.provenance.freshness_at == newest_at for facts in snapshots
    ):
        return None
    return (
        f"{_source_label(_provenance_link(newest[0].provenance))} provides "
        "the newer source fact."
    )


def _source_label(source: SourceLink) -> str:
    return source.account_alias or source.source.replace("_", " ").capitalize()


def _natural_join(
    values: tuple[str, ...],
    *,
    conjunction: str = "and",
) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        if conjunction == "while":
            return f"{values[0]}, while {values[1]}"
        return f"{values[0]} {conjunction} {values[1]}"
    return f"{', '.join(values[:-1])}, {conjunction} {values[-1]}"


def _render_source(source: SourceLink) -> str:
    display_source = source.account_alias or source.source
    label = f"{display_source}/{source.source_record_id}"
    return label if source.display_url is None else f"[{label}]({source.display_url})"


def _coverage_label(report: SourceCoverage) -> str:
    return report.account_alias or report.source


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))
