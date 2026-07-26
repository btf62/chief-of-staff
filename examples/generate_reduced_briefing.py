"""Generate the Milestone 3 reduced briefing from repository-owned fixtures."""

from datetime import UTC, date, datetime

from chief_of_staff.connectors import SourceItem, StaticConnector
from chief_of_staff.domain import CoverageStatus
from chief_of_staff.pipeline import DeterministicBriefingPipeline, resolve_context

BRIEFING_DATE = date(2026, 7, 27)
RETRIEVED_AT = datetime(2026, 7, 27, 11, 0, tzinfo=UTC)


def connectors() -> tuple[StaticConnector, ...]:
    """Return a representative safe synthetic source set."""

    calendar = StaticConnector(
        source_name="synthetic_calendar",
        approved_scope="repository-owned calendar fixtures",
        status=CoverageStatus.COMPLETE,
        items=(
            SourceItem(
                id="calendar-today",
                source_record_id="event-1",
                item_type="calendar_event",
                facts={
                    "title": "Planning Session",
                    "start_at": "2026-07-27T09:00:00-04:00",
                    "end_at": "2026-07-27T10:00:00-04:00",
                    "preparation": "Review the synthetic planning outline.",
                },
                display_url="https://example.invalid/calendar/event-1",
                retrieved_at=RETRIEVED_AT,
                freshness_at=RETRIEVED_AT,
            ),
            SourceItem(
                id="calendar-tomorrow",
                source_record_id="event-2",
                item_type="calendar_event",
                facts={
                    "title": "Project Review",
                    "start_at": "2026-07-28T13:00:00-04:00",
                    "end_at": "2026-07-28T14:00:00-04:00",
                },
                display_url="https://example.invalid/calendar/event-2",
                retrieved_at=RETRIEVED_AT,
                freshness_at=RETRIEVED_AT,
            ),
        ),
    )
    tasks = StaticConnector(
        source_name="synthetic_tasks",
        approved_scope="repository-owned task fixtures",
        status=CoverageStatus.PARTIAL,
        warnings=("one synthetic page was unavailable",),
        items=(
            SourceItem(
                id="task-today",
                source_record_id="task-1",
                item_type="task",
                facts={
                    "title": "Finish the briefing outline",
                    "due_at": "2026-07-27T16:00:00-04:00",
                    "importance": 5,
                    "explicit_commitment": True,
                    "status": "open",
                },
                display_url="https://example.invalid/tasks/1",
                retrieved_at=RETRIEVED_AT,
                freshness_at=RETRIEVED_AT,
            ),
            SourceItem(
                id="task-next",
                source_record_id="task-2",
                item_type="task",
                facts={
                    "title": "Draft the next project brief",
                    "due_at": "2026-07-29T12:00:00-04:00",
                    "importance": 3,
                    "status": "open",
                },
                display_url="https://example.invalid/tasks/2",
                retrieved_at=RETRIEVED_AT,
                freshness_at=RETRIEVED_AT,
            ),
        ),
    )
    repository = StaticConnector(
        source_name="synthetic_repository",
        approved_scope="repository-owned context fixtures",
        status=CoverageStatus.COMPLETE,
        items=(
            SourceItem(
                id="context-baseline",
                source_record_id="docs/product/requirements.md",
                item_type="context",
                facts={
                    "title": "Daily Briefing v1 design baseline",
                    "summary": "The accepted synthetic product context.",
                },
                display_url="https://example.invalid/repository/requirements",
                retrieved_at=RETRIEVED_AT,
                freshness_at=RETRIEVED_AT,
            ),
        ),
    )
    return calendar, tasks, repository


def main() -> None:
    """Generate and print one deterministic reduced briefing."""

    context = resolve_context(
        run_id="synthetic-demo-run",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )
    result = DeterministicBriefingPipeline().run(context, connectors())
    print(result.rendered.text, end="")


if __name__ == "__main__":
    main()
