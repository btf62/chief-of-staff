"""Read-only source connector boundaries."""

from chief_of_staff.connectors.contracts import (
    ConnectorRequest,
    ConnectorResult,
    ReadOnlyConnector,
    RetrievalWindow,
    SourceCoverage,
    SourceItem,
)
from chief_of_staff.connectors.google_calendar import (
    GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE,
    CalendarAuthenticationError,
    CalendarAuthorization,
    CalendarAuthorizationProvider,
    CalendarAuthorizationUnavailable,
    CalendarRetrievalError,
    GoogleCalendarConnector,
    GoogleCalendarEvent,
    GoogleCalendarListRequest,
    GoogleCalendarPage,
    GoogleCalendarTransport,
)
from chief_of_staff.connectors.google_calendar_live import (
    GoogleCalendarHttpTransport,
    StoredGoogleCalendarAuthorizationProvider,
)
from chief_of_staff.connectors.repository import RepositoryContextConnector
from chief_of_staff.connectors.static import StaticConnector

__all__ = (
    "GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE",
    "CalendarAuthenticationError",
    "CalendarAuthorization",
    "CalendarAuthorizationProvider",
    "CalendarAuthorizationUnavailable",
    "CalendarRetrievalError",
    "ConnectorRequest",
    "ConnectorResult",
    "GoogleCalendarConnector",
    "GoogleCalendarEvent",
    "GoogleCalendarHttpTransport",
    "GoogleCalendarListRequest",
    "GoogleCalendarPage",
    "GoogleCalendarTransport",
    "ReadOnlyConnector",
    "RepositoryContextConnector",
    "RetrievalWindow",
    "SourceCoverage",
    "SourceItem",
    "StaticConnector",
    "StoredGoogleCalendarAuthorizationProvider",
)
