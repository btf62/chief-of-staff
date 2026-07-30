"""Explainable deterministic ranking for briefing candidates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import StrEnum

from chief_of_staff.domain import DispositionKind, RecurrenceAction, RecurrenceDecision
from chief_of_staff.pipeline.normalization import NormalizedRecord

APPROACHING_HORIZON = timedelta(days=7)
FRESHNESS_HORIZON = timedelta(days=2)


class PriorityBand(StrEnum):
    """Qualitative priority bands, ordered for deterministic presentation."""

    CRITICAL = "critical"
    TODAY = "today"
    APPROACHING = "approaching"
    STRATEGIC = "strategic"
    BACKGROUND = "background"


PRIORITY_BAND_ORDER = {
    PriorityBand.CRITICAL: 0,
    PriorityBand.TODAY: 1,
    PriorityBand.APPROACHING: 2,
    PriorityBand.STRATEGIC: 3,
    PriorityBand.BACKGROUND: 4,
}


class RankingFactorKind(StrEnum):
    """Inspectable factors accepted by ranking_and_briefing_composition_v1."""

    HARD_DEADLINE = "hard_deadline"
    DUE_DATE = "due_date"
    CALENDAR_OBLIGATION = "calendar_obligation"
    PREPARATION_DEPENDENCY = "preparation_dependency"
    PERSON_OR_TEAM_BLOCKED = "person_or_team_blocked"
    PRIMARY_STEWARDSHIP = "primary_stewardship"
    MINISTRY_OR_RELATIONSHIP_CONSEQUENCE = "ministry_or_relationship_consequence"
    SIX_MONTH_GOAL = "six_month_goal"
    SEASONAL_INITIATIVE = "seasonal_initiative"
    SOURCE_PRIORITY = "source_priority"
    AGE = "age"
    FRESHNESS = "freshness"
    BLOCKER_OR_DEPENDENCY = "blocker_or_dependency"
    DELEGATION = "delegation_opportunity"
    SUPPORTED_EFFORT = "supported_effort"
    AVAILABLE_CALENDAR_WINDOW = "available_calendar_window"
    ENERGY_PATTERN = "documented_energy_pattern"
    OPPORTUNITY_COST = "opportunity_cost"
    CORRECTION_OR_DISPOSITION = "correction_or_disposition"


@dataclass(frozen=True, slots=True)
class FactorSource:
    """Source fact supporting one applied factor."""

    source: str
    source_record_id: str
    display_url: str | None
    fact_name: str
    fact_value: str


@dataclass(frozen=True, slots=True)
class RankingFactor:
    """One inspectable factor and the fact that supports it."""

    kind: RankingFactorKind
    rationale: str
    sources: tuple[FactorSource, ...]

    def __post_init__(self) -> None:
        if not self.rationale.strip() or not self.sources:
            raise ValueError("ranking factors require rationale and source evidence")


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    """One corrected candidate with a qualitative band and factor rationale."""

    record: NormalizedRecord
    band: PriorityBand
    factors: tuple[RankingFactor, ...]
    rationale: str
    tie_breaker: str
    qualitative_comparison_would_help: bool = False


@dataclass(frozen=True, slots=True)
class SuppressedCandidate:
    """One candidate removed before visible ranking."""

    record_id: str
    reason: str
    disposition: DispositionKind | None = None


@dataclass(frozen=True, slots=True)
class RankingResult:
    """Ordered visible candidates plus inspectable suppression decisions."""

    ordered: tuple[RankedCandidate, ...]
    suppressed: tuple[SuppressedCandidate, ...]


def rank_candidates(
    records: tuple[NormalizedRecord, ...],
    *,
    briefing_date: date,
    recurrence_decisions: Mapping[str, RecurrenceDecision] | None = None,
    available_calendar_window: tuple[datetime, datetime] | None = None,
) -> RankingResult:
    """Apply corrections first, then rank with transparent qualitative bands."""

    decisions = recurrence_decisions or {}
    ranked: list[RankedCandidate] = []
    suppressed: list[SuppressedCandidate] = []
    for original in records:
        decision = decisions.get(original.id)
        if decision is not None and decision.action is RecurrenceAction.SUPPRESS:
            suppressed.append(
                SuppressedCandidate(
                    record_id=original.id,
                    reason="accepted local disposition suppresses unchanged evidence",
                    disposition=decision.disposition,
                )
            )
            continue

        record = original
        if (
            decision is not None
            and decision.action is RecurrenceAction.REPLACE
            and decision.replacement_text
        ):
            record = replace(record, title=decision.replacement_text)
        factors = _factors(
            record,
            briefing_date=briefing_date,
            decision=decision,
            available_calendar_window=available_calendar_window,
        )
        band = _priority_band(record, factors, briefing_date)
        ranked.append(
            RankedCandidate(
                record=record,
                band=band,
                factors=factors,
                rationale=_factor_rationale(band, factors),
                tie_breaker=_tie_breaker(record),
            )
        )

    ranked.sort(key=lambda candidate: _sort_key(candidate, briefing_date))
    ranked = _mark_qualitative_ties(ranked)
    return RankingResult(
        ordered=tuple(ranked),
        suppressed=tuple(sorted(suppressed, key=lambda item: item.record_id)),
    )


def _factors(
    record: NormalizedRecord,
    *,
    briefing_date: date,
    decision: RecurrenceDecision | None,
    available_calendar_window: tuple[datetime, datetime] | None,
) -> tuple[RankingFactor, ...]:
    factors: list[RankingFactor] = []
    due_at = record.due_at
    due_date = None if due_at is None else due_at.date()
    if record.hard_deadline and due_at is not None:
        factors.append(
            _factor(
                record,
                RankingFactorKind.HARD_DEADLINE,
                "The source marks this due date as a hard deadline.",
                "hard_deadline",
                due_at.isoformat(),
            )
        )
    if due_at is not None:
        due_date = due_at.date()
        if due_date < briefing_date:
            due_rationale = "The source due date is overdue."
        elif due_date == briefing_date:
            due_rationale = "The source due date is today."
        elif due_date <= briefing_date + APPROACHING_HORIZON:
            due_rationale = "The source due date is approaching within seven days."
        else:
            due_rationale = "The source provides a future due date."
        factors.append(
            _factor(
                record,
                RankingFactorKind.DUE_DATE,
                due_rationale,
                "due_at",
                due_at.isoformat(),
            )
        )
    if record.calendar_dependency or (
        record.start_at is not None and record.start_at.date() == briefing_date
    ):
        factors.append(
            _factor(
                record,
                RankingFactorKind.CALENDAR_OBLIGATION,
                "Authoritative Calendar timing or a source link binds this work.",
                "calendar_dependency",
                str(record.calendar_dependency),
            )
        )
    if record.preparation is not None:
        factors.append(
            _factor(
                record,
                RankingFactorKind.PREPARATION_DEPENDENCY,
                "The source identifies preparation that must precede another item.",
                "preparation",
                record.preparation,
            )
        )
    if record.dependent_references:
        factors.append(
            _factor(
                record,
                RankingFactorKind.PERSON_OR_TEAM_BLOCKED,
                "The source identifies dependent people or work.",
                "dependent_references",
                ", ".join(record.dependent_references),
            )
        )
    if record.primary_stewardship:
        factors.append(
            _factor(
                record,
                RankingFactorKind.PRIMARY_STEWARDSHIP,
                "Approved context links this work to a primary stewardship area.",
                "primary_stewardship",
                "true",
            )
        )
    if record.relationship_consequence:
        factors.append(
            _factor(
                record,
                RankingFactorKind.MINISTRY_OR_RELATIONSHIP_CONSEQUENCE,
                "Approved evidence identifies a ministry or relationship consequence.",
                "relationship_consequence",
                "true",
            )
        )
    if record.six_month_goal:
        factors.append(
            _factor(
                record,
                RankingFactorKind.SIX_MONTH_GOAL,
                "Approved context links this work to an official six-month goal.",
                "six_month_goal",
                "true",
            )
        )
    if record.seasonal_initiative:
        factors.append(
            _factor(
                record,
                RankingFactorKind.SEASONAL_INITIATIVE,
                "Approved context links this work to a current seasonal initiative.",
                "seasonal_initiative",
                "true",
            )
        )
    if record.source_priority is not None or record.provider_priority is not None:
        value = (
            record.source_priority or f"provider priority {record.provider_priority}"
        )
        factors.append(
            _factor(
                record,
                RankingFactorKind.SOURCE_PRIORITY,
                "The authoritative source supplies a priority signal; it is not final judgment.",
                "source_priority",
                value,
            )
        )
    if record.source_created_at is not None:
        age_days = max(0, (briefing_date - record.source_created_at.date()).days)
        factors.append(
            _factor(
                record,
                RankingFactorKind.AGE,
                "The source creation time makes candidate age inspectable.",
                "source_created_at",
                f"{age_days} days",
            )
        )
    freshness = record.provenance.freshness_at or record.provenance.retrieved_at
    factors.append(
        _factor(
            record,
            RankingFactorKind.FRESHNESS,
            "Source freshness is retained for confidence and deterministic ties.",
            "freshness_at",
            freshness.isoformat(),
        )
    )
    if (
        record.blocked
        or record.dependency_references
        or record.dependency_relationships
    ):
        dependency_value = ", ".join(
            (
                *record.dependency_relationships,
                *record.dependency_references,
            )
        )
        factors.append(
            _factor(
                record,
                RankingFactorKind.BLOCKER_OR_DEPENDENCY,
                "The source identifies a blocker or dependency state.",
                "dependency",
                dependency_value or "blocked",
            )
        )
    if record.delegation_opportunity:
        factors.append(
            _factor(
                record,
                RankingFactorKind.DELEGATION,
                "Approved evidence identifies a delegation opportunity.",
                "delegation_opportunity",
                "true",
            )
        )
    if record.effort_minutes is not None:
        factors.append(
            _factor(
                record,
                RankingFactorKind.SUPPORTED_EFFORT,
                "The source supplies an effort estimate; none is inferred.",
                "effort_minutes",
                str(record.effort_minutes),
            )
        )
    if available_calendar_window is not None:
        start, end = available_calendar_window
        available_minutes = int((end - start).total_seconds() // 60)
        if (
            record.effort_minutes is not None
            and record.effort_minutes <= available_minutes
        ):
            factors.append(
                _factor(
                    record,
                    RankingFactorKind.AVAILABLE_CALENDAR_WINDOW,
                    "The supported effort fits an available Calendar window.",
                    "available_calendar_window",
                    f"{start.isoformat()} to {end.isoformat()}",
                )
            )
        if record.energy_requirement == "high" and start.hour < 12:
            factors.append(
                _factor(
                    record,
                    RankingFactorKind.ENERGY_PATTERN,
                    "A source-supported high-energy task aligns with the documented morning pattern.",
                    "energy_requirement",
                    record.energy_requirement,
                )
            )
    if record.opportunity_cost is not None:
        factors.append(
            _factor(
                record,
                RankingFactorKind.OPPORTUNITY_COST,
                "Approved evidence states what competes for the same attention.",
                "opportunity_cost",
                record.opportunity_cost,
            )
        )
    if decision is not None and (
        decision.disposition is not None or decision.action is RecurrenceAction.REPLACE
    ):
        disposition = (
            "corrected" if decision.disposition is None else decision.disposition.value
        )
        factors.append(
            _factor(
                record,
                RankingFactorKind.CORRECTION_OR_DISPOSITION,
                "Accepted local state was applied before ranking.",
                "local_disposition",
                disposition,
            )
        )
    return tuple(factors)


def _factor(
    record: NormalizedRecord,
    kind: RankingFactorKind,
    rationale: str,
    fact_name: str,
    fact_value: str,
) -> RankingFactor:
    return RankingFactor(
        kind=kind,
        rationale=rationale,
        sources=(
            FactorSource(
                source=record.provenance.source,
                source_record_id=record.provenance.source_record_id,
                display_url=record.provenance.display_url,
                fact_name=fact_name,
                fact_value=fact_value,
            ),
        ),
    )


def _priority_band(
    record: NormalizedRecord,
    factors: tuple[RankingFactor, ...],
    briefing_date: date,
) -> PriorityBand:
    kinds = {factor.kind for factor in factors}
    due_date = None if record.due_at is None else record.due_at.date()
    current_consequence = bool(
        kinds
        & {
            RankingFactorKind.CALENDAR_OBLIGATION,
            RankingFactorKind.PREPARATION_DEPENDENCY,
            RankingFactorKind.PERSON_OR_TEAM_BLOCKED,
            RankingFactorKind.MINISTRY_OR_RELATIONSHIP_CONSEQUENCE,
            RankingFactorKind.BLOCKER_OR_DEPENDENCY,
        }
    )
    durable_importance = bool(
        kinds
        & {
            RankingFactorKind.PRIMARY_STEWARDSHIP,
            RankingFactorKind.SIX_MONTH_GOAL,
            RankingFactorKind.SEASONAL_INITIATIVE,
        }
    )

    if (
        RankingFactorKind.HARD_DEADLINE in kinds
        and due_date is not None
        and due_date <= briefing_date
    ):
        return PriorityBand.CRITICAL
    if due_date == briefing_date and current_consequence:
        return PriorityBand.CRITICAL
    if (
        due_date == briefing_date
        or (
            record.explicit_commitment and (current_consequence or due_date is not None)
        )
        or (
            RankingFactorKind.CALENDAR_OBLIGATION in kinds
            and RankingFactorKind.PREPARATION_DEPENDENCY in kinds
        )
        or RankingFactorKind.PERSON_OR_TEAM_BLOCKED in kinds
    ):
        return PriorityBand.TODAY
    if (
        due_date is not None
        and briefing_date < due_date <= briefing_date + APPROACHING_HORIZON
    ) or (current_consequence and record.explicit_commitment):
        return PriorityBand.APPROACHING
    if durable_importance and (current_consequence or record.explicit_priority_link):
        return PriorityBand.STRATEGIC
    return PriorityBand.BACKGROUND


def _factor_rationale(
    band: PriorityBand,
    factors: tuple[RankingFactor, ...],
) -> str:
    material = tuple(
        factor.rationale
        for factor in factors
        if factor.kind
        not in {
            RankingFactorKind.AGE,
            RankingFactorKind.FRESHNESS,
            RankingFactorKind.SOURCE_PRIORITY,
        }
    )
    if material:
        return f"{band.value.capitalize()} band: {' '.join(material)}"
    return (
        f"{band.value.capitalize()} band: no supported current consequence "
        "raises this candidate above background."
    )


def _tie_breaker(record: NormalizedRecord) -> str:
    return (
        "Deterministic fallback: earliest source due date, then freshest source "
        f"fact, source name, and stable record ID ({record.id})."
    )


def _sort_key(
    candidate: RankedCandidate,
    briefing_date: date,
) -> tuple[object, ...]:
    record = candidate.record
    due_at = record.due_at or datetime.max.replace(
        tzinfo=record.provenance.retrieved_at.tzinfo
    )
    freshness = record.provenance.freshness_at or record.provenance.retrieved_at
    factor_kinds = {factor.kind for factor in candidate.factors}
    consequence_count = sum(
        kind
        in {
            RankingFactorKind.HARD_DEADLINE,
            RankingFactorKind.CALENDAR_OBLIGATION,
            RankingFactorKind.PREPARATION_DEPENDENCY,
            RankingFactorKind.PERSON_OR_TEAM_BLOCKED,
            RankingFactorKind.MINISTRY_OR_RELATIONSHIP_CONSEQUENCE,
            RankingFactorKind.BLOCKER_OR_DEPENDENCY,
            RankingFactorKind.PRIMARY_STEWARDSHIP,
            RankingFactorKind.SIX_MONTH_GOAL,
            RankingFactorKind.SEASONAL_INITIATIVE,
        }
        for kind in factor_kinds
    )
    return (
        PRIORITY_BAND_ORDER[candidate.band],
        -consequence_count,
        due_at,
        -freshness.timestamp(),
        record.provenance.source,
        record.provenance.source_record_id,
        record.id,
    )


def _mark_qualitative_ties(
    ranked: list[RankedCandidate],
) -> list[RankedCandidate]:
    if len(ranked) < 2:
        return ranked
    signatures = [_qualitative_signature(candidate) for candidate in ranked]
    return [
        replace(
            candidate,
            qualitative_comparison_would_help=(
                (index > 0 and signatures[index - 1] == signatures[index])
                or (
                    index + 1 < len(ranked)
                    and signatures[index + 1] == signatures[index]
                )
            ),
        )
        for index, candidate in enumerate(ranked)
    ]


def _qualitative_signature(candidate: RankedCandidate) -> tuple[object, ...]:
    return (
        candidate.band,
        tuple(
            sorted(
                factor.kind
                for factor in candidate.factors
                if factor.kind
                not in {
                    RankingFactorKind.AGE,
                    RankingFactorKind.FRESHNESS,
                    RankingFactorKind.SOURCE_PRIORITY,
                }
            )
        ),
    )
