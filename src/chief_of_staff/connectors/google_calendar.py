"""Read-only Google Calendar contract with injectable authorization and transport."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Final, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from chief_of_staff.connectors.contracts import (
    ConnectorRequest,
    ConnectorResult,
    SourceCoverage,
    SourceItem,
)
from chief_of_staff.domain import CoverageStatus

GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE: Final = (
    "https://www.googleapis.com/auth/calendar.events.owned.readonly"
)
DEFAULT_MAX_PAGES: Final = 100


class CalendarAuthorizationUnavailable(RuntimeError):
    """Raised by an authorization boundary with no usable approved grant."""


class CalendarAuthenticationError(RuntimeError):
    """Raised when a provider rejects an otherwise present authorization."""


class CalendarRetrievalError(RuntimeError):
    """Expected provider retrieval failure without private response content."""


@dataclass(frozen=True, slots=True)
class CalendarAuthorization:
    """Non-secret authorization metadata supplied to a calendar transport."""

    account_reference: str
    granted_scopes: frozenset[str]
    credential_reference: str


@dataclass(frozen=True, slots=True)
class GoogleCalendarListRequest:
    """Bounded parameters for the provider's event-list operation."""

    calendar_id: str
    time_min: datetime
    time_max: datetime
    timezone: str
    page_token: str | None
    single_events: bool = True
    show_deleted: bool = False
    order_by: str = "startTime"


@dataclass(frozen=True, slots=True)
class GoogleCalendarEvent:
    """Minimal provider event needed for deterministic normalization."""

    id: str
    title: str
    start: str
    end: str
    updated_at: datetime
    html_link: str | None = None
    status: str = "confirmed"
    self_response_status: str | None = None
    event_type: str = "default"
    location: str | None = None
    all_day: bool = False
    preparation: str | None = None


@dataclass(frozen=True, slots=True)
class GoogleCalendarPage:
    """One provider page and its opaque continuation token."""

    events: tuple[GoogleCalendarEvent, ...]
    next_page_token: str | None = None


@runtime_checkable
class CalendarAuthorizationProvider(Protocol):
    """Mockable OAuth boundary; live implementation requires later approval."""

    def get_calendar_authorization(
        self,
        account_reference: str,
    ) -> CalendarAuthorization:
        """Return non-secret grant metadata or raise unavailable."""


@runtime_checkable
class GoogleCalendarTransport(Protocol):
    """Provider boundary exposing only the read-only event-list operation."""

    def list_events(
        self,
        authorization: CalendarAuthorization,
        request: GoogleCalendarListRequest,
    ) -> GoogleCalendarPage:
        """Return one event page without exposing mutation operations."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class GoogleCalendarConnector:
    """Retrieve primary-calendar events through approved injected boundaries."""

    account_reference: str
    authorization_provider: CalendarAuthorizationProvider
    transport: GoogleCalendarTransport
    calendar_id: str = "primary"
    max_pages: int = DEFAULT_MAX_PAGES
    clock: Callable[[], datetime] = field(
        default=_utc_now,
        repr=False,
        compare=False,
    )
    source_name: str = field(default="google_calendar", init=False)
    approved_scope: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.account_reference.strip():
            raise ValueError("calendar account reference must not be empty")
        if "@" in self.account_reference or any(
            character.isspace() for character in self.account_reference
        ):
            raise ValueError("calendar account reference must be an opaque alias")
        if self.calendar_id != "primary":
            raise ValueError("Milestone 4 permits only the primary calendar")
        if self.max_pages < 1:
            raise ValueError("calendar max_pages must be positive")
        object.__setattr__(
            self,
            "approved_scope",
            f"Google account alias={self.account_reference}; calendar=primary",
        )

    def retrieve(self, request: ConnectorRequest) -> ConnectorResult:
        """Retrieve all available event pages or disclose bounded failure."""

        if request.approved_scope != self.approved_scope:
            raise ValueError("request scope does not match connector scope")
        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("connector clock must return a timezone-aware value")

        try:
            authorization = self.authorization_provider.get_calendar_authorization(
                self.account_reference
            )
        except CalendarAuthorizationUnavailable:
            return self._coverage_result(
                retrieved_at=retrieved_at,
                status=CoverageStatus.UNAUTHORIZED,
                error_category="CalendarAuthorizationUnavailable",
                page_count=0,
            )

        if (
            authorization.account_reference != self.account_reference
            or authorization.granted_scopes
            != frozenset({GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE})
        ):
            return self._coverage_result(
                retrieved_at=retrieved_at,
                status=CoverageStatus.UNAUTHORIZED,
                error_category="CalendarAuthorizationScopeMismatch",
                page_count=0,
            )

        items: list[SourceItem] = []
        warnings: list[str] = []
        page_token: str | None = None
        seen_page_tokens: set[str] = set()
        page_number = 0
        while page_number < self.max_pages:
            page_number += 1
            list_request = GoogleCalendarListRequest(
                calendar_id=self.calendar_id,
                time_min=request.window.starts_at,
                time_max=request.window.ends_at,
                timezone=request.timezone,
                page_token=page_token,
            )
            try:
                page = self.transport.list_events(authorization, list_request)
            except CalendarAuthenticationError:
                return self._coverage_result(
                    retrieved_at=retrieved_at,
                    status=CoverageStatus.UNAUTHORIZED,
                    items=tuple(items),
                    warnings=(
                        *warnings,
                        f"calendar authorization failed before page {page_number}",
                    ),
                    error_category="CalendarAuthenticationError",
                    page_count=page_number - 1,
                )
            except CalendarRetrievalError:
                return self._coverage_result(
                    retrieved_at=retrieved_at,
                    status=(
                        CoverageStatus.PARTIAL if items else CoverageStatus.UNAVAILABLE
                    ),
                    items=tuple(items),
                    warnings=(
                        *warnings,
                        f"calendar retrieval stopped before page {page_number}",
                    ),
                    error_category="CalendarRetrievalError",
                    page_count=page_number - 1,
                )

            for event in page.events:
                try:
                    items.append(
                        _event_to_source_item(
                            event,
                            timezone=request.timezone,
                            retrieved_at=retrieved_at,
                        )
                    )
                except ValueError:
                    warnings.append(
                        f"one event on page {page_number} was invalid and omitted"
                    )

            next_page_token = page.next_page_token
            if next_page_token is None:
                return self._coverage_result(
                    retrieved_at=retrieved_at,
                    status=(
                        CoverageStatus.PARTIAL if warnings else CoverageStatus.COMPLETE
                    ),
                    items=tuple(items),
                    warnings=tuple(warnings),
                    error_category=(
                        "CalendarEventValidationError" if warnings else None
                    ),
                    page_count=page_number,
                )
            if not next_page_token:
                warnings.append("calendar pagination returned an empty page token")
                return self._coverage_result(
                    retrieved_at=retrieved_at,
                    status=CoverageStatus.PARTIAL,
                    items=tuple(items),
                    warnings=tuple(warnings),
                    error_category="CalendarPaginationTokenInvalid",
                    page_count=page_number,
                )
            if next_page_token in seen_page_tokens:
                warnings.append("calendar pagination returned a repeated page token")
                return self._coverage_result(
                    retrieved_at=retrieved_at,
                    status=CoverageStatus.PARTIAL,
                    items=tuple(items),
                    warnings=tuple(warnings),
                    error_category="CalendarPaginationLoop",
                    page_count=page_number,
                )
            seen_page_tokens.add(next_page_token)
            page_token = next_page_token

        warnings.append(f"calendar retrieval reached the {self.max_pages}-page limit")
        return self._coverage_result(
            retrieved_at=retrieved_at,
            status=CoverageStatus.PARTIAL,
            items=tuple(items),
            warnings=tuple(warnings),
            error_category="CalendarPageLimit",
            page_count=page_number,
        )

    def _coverage_result(
        self,
        *,
        retrieved_at: datetime,
        status: CoverageStatus,
        items: tuple[SourceItem, ...] = (),
        warnings: tuple[str, ...] = (),
        error_category: str | None = None,
        page_count: int | None = None,
    ) -> ConnectorResult:
        freshness_values = tuple(
            item.freshness_at for item in items if item.freshness_at is not None
        )
        return ConnectorResult(
            items=items,
            coverage=SourceCoverage(
                source=self.source_name,
                approved_scope=self.approved_scope,
                status=status,
                retrieved_at=retrieved_at,
                record_count=len(items),
                freshness_at=max(freshness_values) if freshness_values else None,
                warnings=warnings,
                error_category=error_category,
                page_count=page_count,
            ),
        )


def _event_to_source_item(
    event: GoogleCalendarEvent,
    *,
    timezone: str,
    retrieved_at: datetime,
) -> SourceItem:
    if not event.id.strip():
        raise ValueError("calendar event ID must not be empty")
    if not event.title.strip():
        raise ValueError("calendar event title must not be empty")
    zone = ZoneInfo(timezone)
    start_at = _event_time(event.start, all_day=event.all_day, zone=zone)
    end_at = _event_time(event.end, all_day=event.all_day, zone=zone)
    if end_at <= start_at:
        raise ValueError("calendar event end must follow its start")
    if event.updated_at.tzinfo is None or event.updated_at.utcoffset() is None:
        raise ValueError("calendar event freshness must be timezone-aware")

    summary = None if event.location is None else f"Location: {event.location}"
    return SourceItem(
        id=event.id,
        source_record_id=event.id,
        item_type="calendar_event",
        facts={
            "title": event.title.strip(),
            "summary": summary,
            "status": event.status,
            "self_response_status": event.self_response_status,
            "event_type": event.event_type,
            "preparation": event.preparation,
            "all_day": event.all_day,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
        },
        retrieved_at=retrieved_at,
        freshness_at=event.updated_at.astimezone(UTC),
        display_url=event.html_link,
    )


def _event_time(value: str, *, all_day: bool, zone: ZoneInfo) -> datetime:
    if all_day:
        try:
            return datetime.combine(date.fromisoformat(value), time.min, tzinfo=zone)
        except ValueError:
            raise ValueError("all-day calendar values must be ISO dates") from None

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("calendar values must be ISO date-times") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("calendar date-times must be timezone-aware")
    return parsed.astimezone(zone)
