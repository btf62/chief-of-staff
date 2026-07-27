"""Generate a redacted July 25 non-workday briefing without live access."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from chief_of_staff.connectors import SourceItem, StaticConnector
from chief_of_staff.connectors.contracts import FactValue
from chief_of_staff.domain import CoverageStatus
from chief_of_staff.pipeline import DeterministicBriefingPipeline, resolve_context

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPOSITORY_ROOT / ".local/briefings/2026-07-25-safe.md"
BRIEFING_DATE = date(2026, 7, 25)
RETRIEVED_AT = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
APPROVED_SCOPE = "repository-owned redacted July 25 scenario"


def _item(
    item_id: str,
    *,
    item_type: str,
    title: str,
    **facts: FactValue,
) -> SourceItem:
    item_facts: dict[str, FactValue] = {
        "title": title,
        **facts,
    }
    return SourceItem(
        id=item_id,
        source_record_id=item_id,
        item_type=item_type,
        facts=item_facts,
        retrieved_at=RETRIEVED_AT,
        freshness_at=RETRIEVED_AT,
        display_url=f"https://example.invalid/source/{item_id}",
    )


def main() -> None:
    """Write one private ignored briefing from redacted synthetic facts."""

    repository = StaticConnector(
        source_name="repository_context",
        approved_scope=APPROVED_SCOPE,
        items=(
            _item(
                "governing-context",
                item_type="context",
                title="Accepted project context",
            ),
        ),
        status=CoverageStatus.COMPLETE,
    )
    calendar = StaticConnector(
        source_name="google_calendar",
        approved_scope=APPROVED_SCOPE,
        items=(
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
        ),
        status=CoverageStatus.COMPLETE,
    )
    context = resolve_context(
        run_id="july-25-safe-equivalent",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )
    result = DeterministicBriefingPipeline().run(
        context,
        (repository, calendar),
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(result.rendered.text, encoding="utf-8")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
