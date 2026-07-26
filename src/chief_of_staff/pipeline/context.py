"""Workday and invocation context resolution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from chief_of_staff.connectors import RetrievalWindow


class WorkdayType(StrEnum):
    """Configured operating shape for one day."""

    FULL_WORKDAY = "full workday"
    NON_WORKDAY = "non-workday"
    FLEXIBLE_HALF_WORKDAY = "flexible half-workday"
    MINISTRY_WORKDAY = "ministry workday"


DEFAULT_WEEKLY_WORKDAYS: Mapping[int, WorkdayType] = {
    0: WorkdayType.FULL_WORKDAY,
    1: WorkdayType.FULL_WORKDAY,
    2: WorkdayType.FULL_WORKDAY,
    3: WorkdayType.FULL_WORKDAY,
    4: WorkdayType.NON_WORKDAY,
    5: WorkdayType.FLEXIBLE_HALF_WORKDAY,
    6: WorkdayType.MINISTRY_WORKDAY,
}


@dataclass(frozen=True, slots=True)
class InvocationContext:
    """Explicit date, timezone, workday, and invocation inputs for one run."""

    run_id: str
    briefing_date: date
    timezone: str
    invocation_mode: str
    is_workday: bool
    workday_type: WorkdayType
    workday_reason: str
    workday_diagnostics: tuple[str, ...]
    retrieval_window: RetrievalWindow


def resolve_context(
    *,
    run_id: str,
    briefing_date: date,
    timezone: str,
    invocation_mode: str = "on_demand",
    workday_override: bool | None = None,
    workday_type_override: WorkdayType | None = None,
    date_overrides: Mapping[date, WorkdayType] | None = None,
    operating_overrides: Mapping[date, WorkdayType] | None = None,
    weekly_workdays: Mapping[int, WorkdayType] = DEFAULT_WEEKLY_WORKDAYS,
    lookahead_days: int = 7,
) -> InvocationContext:
    """Resolve deterministic workday and bounded retrieval context."""

    if not run_id.strip():
        raise ValueError("run_id must not be empty")
    if lookahead_days < 1:
        raise ValueError("lookahead_days must be positive")
    if set(weekly_workdays) != set(range(7)):
        raise ValueError("weekly_workdays must define weekday numbers 0 through 6")
    if workday_override is not None and workday_type_override is not None:
        raise ValueError("only one explicit workday override may be supplied")

    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        raise ValueError("timezone must be a recognized IANA name") from None

    if workday_type_override is not None:
        workday_type = workday_type_override
        workday_reason = "explicit current instruction"
    elif workday_override is not None:
        workday_type = (
            WorkdayType.FULL_WORKDAY if workday_override else WorkdayType.NON_WORKDAY
        )
        workday_reason = "explicit current instruction"
    elif date_overrides is not None and briefing_date in date_overrides:
        workday_type = date_overrides[briefing_date]
        workday_reason = "explicit date configuration"
    elif operating_overrides is not None and briefing_date in operating_overrides:
        workday_type = operating_overrides[briefing_date]
        workday_reason = "explicit leave or workday override"
    else:
        workday_type = weekly_workdays[briefing_date.weekday()]
        workday_reason = f"recurring weekly {workday_type.value}"

    starts_at = datetime.combine(briefing_date, time.min, tzinfo=zone)
    ends_at = starts_at + timedelta(days=lookahead_days + 1)
    return InvocationContext(
        run_id=run_id,
        briefing_date=briefing_date,
        timezone=timezone,
        invocation_mode=invocation_mode,
        is_workday=workday_type is not WorkdayType.NON_WORKDAY,
        workday_type=workday_type,
        workday_reason=workday_reason,
        workday_diagnostics=(),
        retrieval_window=RetrievalWindow(starts_at=starts_at, ends_at=ends_at),
    )


def reconcile_calendar_workday_context(
    context: InvocationContext,
    *,
    fixed_commitment_count: int,
    scheduled_minutes: int,
) -> InvocationContext:
    """Surface schedule conflicts without letting Calendar redefine a workday."""

    if fixed_commitment_count < 0 or scheduled_minutes < 0:
        raise ValueError("Calendar workday evidence counts must not be negative")
    if context.workday_type is not WorkdayType.NON_WORKDAY:
        return context
    if fixed_commitment_count < 2 and scheduled_minutes < 120:
        return context

    diagnostic = (
        "Configured non-workday conflicts with substantial fixed Calendar work; "
        "the explicit or recurring workday configuration remains authoritative."
    )
    return replace(
        context,
        workday_diagnostics=(*context.workday_diagnostics, diagnostic),
    )
