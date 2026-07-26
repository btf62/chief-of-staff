"""Workday and invocation context resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from chief_of_staff.connectors import RetrievalWindow

DEFAULT_WORKDAYS = frozenset({0, 1, 2, 3, 4})


@dataclass(frozen=True, slots=True)
class InvocationContext:
    """Explicit date, timezone, workday, and invocation inputs for one run."""

    run_id: str
    briefing_date: date
    timezone: str
    invocation_mode: str
    is_workday: bool
    workday_reason: str
    retrieval_window: RetrievalWindow


def resolve_context(
    *,
    run_id: str,
    briefing_date: date,
    timezone: str,
    invocation_mode: str = "on_demand",
    workday_override: bool | None = None,
    workdays: frozenset[int] = DEFAULT_WORKDAYS,
    lookahead_days: int = 7,
) -> InvocationContext:
    """Resolve deterministic workday and bounded retrieval context."""

    if not run_id.strip():
        raise ValueError("run_id must not be empty")
    if lookahead_days < 1:
        raise ValueError("lookahead_days must be positive")
    if not workdays.issubset(range(7)):
        raise ValueError("workdays must contain weekday numbers from 0 to 6")

    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        raise ValueError("timezone must be a recognized IANA name") from None

    if workday_override is None:
        is_workday = briefing_date.weekday() in workdays
        workday_reason = "configured weekday" if is_workday else "configured day off"
    else:
        is_workday = workday_override
        workday_reason = "explicit invocation override"

    starts_at = datetime.combine(briefing_date, time.min, tzinfo=zone)
    ends_at = starts_at + timedelta(days=lookahead_days + 1)
    return InvocationContext(
        run_id=run_id,
        briefing_date=briefing_date,
        timezone=timezone,
        invocation_mode=invocation_mode,
        is_workday=is_workday,
        workday_reason=workday_reason,
        retrieval_window=RetrievalWindow(starts_at=starts_at, ends_at=ends_at),
    )
