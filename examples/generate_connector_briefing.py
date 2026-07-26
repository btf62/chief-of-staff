"""Generate a safe briefing from repository context and a mocked calendar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from chief_of_staff.connectors import (
    GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE,
    CalendarAuthorization,
    CalendarRetrievalError,
    GoogleCalendarConnector,
    GoogleCalendarEvent,
    GoogleCalendarListRequest,
    GoogleCalendarPage,
    RepositoryContextConnector,
)
from chief_of_staff.pipeline import DeterministicBriefingPipeline, resolve_context

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BRIEFING_DATE = date(2026, 7, 27)
RETRIEVED_AT = datetime(2026, 7, 27, 11, 0, tzinfo=UTC)
NEXT_PAGE_MARKER = "synthetic-page-2"


@dataclass(frozen=True, slots=True)
class MockCalendarAuthorization:
    """Return non-secret metadata without opening an OAuth flow."""

    def get_calendar_authorization(
        self,
        account_reference: str,
    ) -> CalendarAuthorization:
        return CalendarAuthorization(
            account_reference=account_reference,
            granted_scopes=frozenset({GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE}),
            credential_reference="demonstration-grant",
        )


@dataclass(frozen=True, slots=True)
class PartiallyAvailableCalendarTransport:
    """Return one synthetic page, then model a provider page failure."""

    def list_events(
        self,
        authorization: CalendarAuthorization,
        request: GoogleCalendarListRequest,
    ) -> GoogleCalendarPage:
        if authorization.credential_reference != "demonstration-grant":
            raise CalendarRetrievalError
        if request.page_token is not None:
            raise CalendarRetrievalError
        return GoogleCalendarPage(
            events=(
                GoogleCalendarEvent(
                    id="synthetic-calendar-event",
                    title="Planning Session",
                    start="2026-07-27T09:00:00-04:00",
                    end="2026-07-27T10:00:00-04:00",
                    updated_at=datetime(
                        2026,
                        7,
                        26,
                        18,
                        0,
                        tzinfo=UTC,
                    ),
                    html_link=(
                        "https://example.invalid/calendar/synthetic-calendar-event"
                    ),
                    location="Conference Room",
                ),
            ),
            next_page_token=NEXT_PAGE_MARKER,
        )


def main() -> None:
    """Print one on-demand, no-network connector demonstration."""

    repository = RepositoryContextConnector(
        root=REPOSITORY_ROOT,
        approved_paths=(
            Path("docs/product/features/daily-briefing-v1.md"),
            Path("docs/roadmap.md"),
        ),
        clock=lambda: RETRIEVED_AT,
    )
    calendar = GoogleCalendarConnector(
        account_reference="primary-user",
        authorization_provider=MockCalendarAuthorization(),
        transport=PartiallyAvailableCalendarTransport(),
        clock=lambda: RETRIEVED_AT,
    )
    context = resolve_context(
        run_id="safe-connector-demonstration",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )
    result = DeterministicBriefingPipeline().run(
        context,
        (repository, calendar),
    )
    print(result.rendered.text, end="")


if __name__ == "__main__":
    main()
