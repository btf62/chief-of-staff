"""Machine-checkable invariants for historical briefing comparisons."""

from __future__ import annotations

from datetime import date

from chief_of_staff.pipeline.briefing import BriefingSectionName
from chief_of_staff.pipeline.context import HistoricalMode
from chief_of_staff.pipeline.runner import PipelineResult

CalendarSignature = tuple[tuple[str, str, str, str, str], ...]
FocusSignature = tuple[str, str, str, str]


def historical_invariants_match(
    recorded: PipelineResult,
    replay: PipelineResult,
    *,
    timezone: str,
    recorded_briefing_date: date,
    recorded_run_id: str,
    replay_originating_run_id: str | None,
    persisted_replay_originating_run_id: str | None,
    recorded_mode: str | None,
    replay_mode: str | None,
) -> bool:
    """Return whether replay preserves temporal display and recorded lineage."""

    recorded_calendar = calendar_signature(recorded)
    replay_calendar = calendar_signature(replay)
    recorded_focus = focus_signature(recorded)
    replay_focus = focus_signature(replay)
    dates_match = (
        recorded.plan.context.briefing_date
        == replay.plan.context.briefing_date
        == recorded_briefing_date
    )
    source_ids_match = tuple(item[0] for item in recorded_calendar) == tuple(
        item[0] for item in replay_calendar
    )
    lineage_matches = (
        replay_originating_run_id == recorded_run_id
        and persisted_replay_originating_run_id == recorded_run_id
        and replay_mode == HistoricalMode.REPLAY.value
        and recorded_mode == HistoricalMode.RECORDED.value
    )
    projected_to_recorded_zone = (
        all(item[4] == timezone for item in replay_calendar)
        and replay_focus[3] == timezone
    )
    return all(
        (
            dates_match,
            source_ids_match,
            lineage_matches,
            recorded_calendar == replay_calendar,
            recorded_focus == replay_focus,
            projected_to_recorded_zone,
        )
    )


def calendar_signature(result: PipelineResult) -> CalendarSignature:
    """Return source identity and local display values for Calendar items."""

    items = next(
        (
            section.items
            for section in result.plan.sections
            if section.name is BriefingSectionName.TODAYS_CALENDAR
        ),
        (),
    )
    signature: list[tuple[str, str, str, str, str]] = []
    for item in items:
        if item.starts_at is None or item.ends_at is None:
            continue
        source_ids = tuple(
            source.source_record_id
            for source in item.sources
            if source.source == "google_calendar"
        )
        if len(source_ids) != 1:
            raise RuntimeError("historical Calendar item lacked one source identity")
        zone = getattr(item.starts_at.tzinfo, "key", str(item.starts_at.tzinfo))
        signature.append(
            (
                source_ids[0],
                item.starts_at.strftime("%Y-%m-%d %-I:%M %p"),
                item.ends_at.strftime("%Y-%m-%d %-I:%M %p"),
                item.detail,
                zone,
            )
        )
    return tuple(signature)


def focus_signature(result: PipelineResult) -> FocusSignature:
    """Return local focus-window display values for one briefing."""

    items = next(
        (
            section.items
            for section in result.plan.sections
            if section.name is BriefingSectionName.RECOMMENDED_FOCUS_BLOCK
        ),
        (),
    )
    if len(items) != 1 or items[0].starts_at is None or items[0].ends_at is None:
        raise RuntimeError("historical comparison requires one focus window")
    item = items[0]
    starts_at = item.starts_at
    ends_at = item.ends_at
    if starts_at is None or ends_at is None:
        raise RuntimeError("historical comparison focus timestamps disappeared")
    zone = getattr(starts_at.tzinfo, "key", str(starts_at.tzinfo))
    return (
        starts_at.strftime("%Y-%m-%d %-I:%M %p"),
        ends_at.strftime("%Y-%m-%d %-I:%M %p"),
        item.headline,
        zone,
    )
