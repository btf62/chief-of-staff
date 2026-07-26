"""Approved live Google Calendar read transport and stored authorization."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Protocol, cast

from chief_of_staff.auth.keychain import (
    KeychainSecretNotFound,
    KeychainSecretReference,
    MacOSKeychain,
)
from chief_of_staff.connectors.google_calendar import (
    GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE,
    CalendarAuthenticationError,
    CalendarAuthorization,
    CalendarAuthorizationUnavailable,
    CalendarRetrievalError,
    GoogleCalendarEvent,
    GoogleCalendarListRequest,
    GoogleCalendarPage,
)
from chief_of_staff.domain import AuthorizationStatus, CredentialHealth
from chief_of_staff.persistence import StateStore

GOOGLE_CALENDAR_EVENTS_ENDPOINT: Final = (
    "https://www.googleapis.com/calendar/v3/calendars/primary/events"
)
MAX_CALENDAR_RESPONSE_BYTES: Final = 5 * 1024 * 1024


class CalendarHttpResponse(Protocol):
    """Minimal response surface used by the read-only transport."""

    def read(self, amount: int = -1) -> bytes:
        """Read a bounded response body."""

    def __enter__(self) -> CalendarHttpResponse:
        """Enter the response context."""

    def __exit__(self, *args: object) -> None:
        """Close the response context."""


class CalendarUrlOpener(Protocol):
    """Injectable HTTPS opener for contract tests."""

    def __call__(
        self,
        request: urllib.request.Request,
        *,
        timeout: int,
    ) -> CalendarHttpResponse:
        """Open one GET request."""


def _open_url(
    request: urllib.request.Request,
    *,
    timeout: int,
) -> CalendarHttpResponse:
    return cast(
        CalendarHttpResponse,
        urllib.request.urlopen(  # noqa: S310 - fixed HTTPS request
            request,
            timeout=timeout,
        ),
    )


@dataclass(frozen=True, slots=True)
class StoredGoogleCalendarAuthorizationProvider:
    """Resolve approved non-secret metadata and verify Keychain presence."""

    state_store: StateStore
    keychain: MacOSKeychain
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def get_calendar_authorization(
        self,
        account_reference: str,
    ) -> CalendarAuthorization:
        metadata = self.state_store.get_connector_authorization("google_calendar")
        if (
            metadata is None
            or metadata.account_reference != account_reference
            or metadata.granted_scope != GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE
            or metadata.authorization_status is not AuthorizationStatus.AUTHORIZED
            or metadata.credential_health is not CredentialHealth.HEALTHY
            or metadata.token_expires_at <= self.clock()
        ):
            raise CalendarAuthorizationUnavailable
        reference = KeychainSecretReference(
            service=metadata.credential_service,
            account=metadata.access_token_account,
        )
        if not self.keychain.exists(reference):
            raise CalendarAuthorizationUnavailable
        return CalendarAuthorization(
            account_reference=metadata.account_reference,
            granted_scopes=frozenset({metadata.granted_scope}),
            credential_reference=reference.identifier,
        )


@dataclass(frozen=True, slots=True)
class GoogleCalendarHttpTransport:
    """Call only `events.list` for `calendarId=primary`."""

    keychain: MacOSKeychain
    access_token_reference: KeychainSecretReference
    url_opener: CalendarUrlOpener = field(
        default=_open_url,
        repr=False,
        compare=False,
    )

    def list_events(
        self,
        authorization: CalendarAuthorization,
        request: GoogleCalendarListRequest,
    ) -> GoogleCalendarPage:
        """Retrieve one bounded page without mutation or link traversal."""

        if authorization.credential_reference != (
            self.access_token_reference.identifier
        ):
            raise CalendarAuthenticationError
        _validate_list_request(request)
        try:
            access_token = self.keychain.read(self.access_token_reference)
        except KeychainSecretNotFound:
            raise CalendarAuthenticationError from None

        query: dict[str, str] = {
            "maxResults": "250",
            "orderBy": "startTime",
            "showDeleted": "false",
            "singleEvents": "true",
            "timeMax": request.time_max.isoformat(),
            "timeMin": request.time_min.isoformat(),
            "timeZone": request.timezone,
        }
        if request.page_token is not None:
            query["pageToken"] = request.page_token
        url = f"{GOOGLE_CALENDAR_EVENTS_ENDPOINT}?{urllib.parse.urlencode(query)}"
        http_request = urllib.request.Request(  # noqa: S310 - fixed HTTPS endpoint
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
            method="GET",
        )
        try:
            with self.url_opener(http_request, timeout=30) as response:
                raw_response = response.read(MAX_CALENDAR_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                raise CalendarAuthenticationError from None
            raise CalendarRetrievalError from None
        except urllib.error.URLError, TimeoutError:
            raise CalendarRetrievalError from None
        finally:
            access_token = ""

        if len(raw_response) > MAX_CALENDAR_RESPONSE_BYTES:
            raise CalendarRetrievalError
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError, UnicodeDecodeError:
            raise CalendarRetrievalError from None
        finally:
            raw_response = b""
        if not isinstance(payload, dict):
            raise CalendarRetrievalError
        items = payload.get("items", [])
        next_page_token = payload.get("nextPageToken")
        if not isinstance(items, list) or not (
            next_page_token is None or isinstance(next_page_token, str)
        ):
            raise CalendarRetrievalError

        events = tuple(_event_from_payload(item) for item in items)
        payload.clear()
        return GoogleCalendarPage(
            events=events,
            next_page_token=next_page_token,
        )


def _validate_list_request(request: GoogleCalendarListRequest) -> None:
    if (
        request.calendar_id != "primary"
        or not request.single_events
        or request.show_deleted
        or request.order_by != "startTime"
        or request.time_min.tzinfo is None
        or request.time_max.tzinfo is None
        or request.time_max <= request.time_min
    ):
        raise CalendarRetrievalError


def _event_from_payload(payload: object) -> GoogleCalendarEvent:
    if not isinstance(payload, dict):
        return _invalid_event()
    event_id = payload.get("id")
    title = payload.get("summary", "(No title)")
    start = payload.get("start")
    end = payload.get("end")
    updated = payload.get("updated")
    html_link = payload.get("htmlLink")
    status = payload.get("status", "confirmed")
    location = payload.get("location")
    if not (
        isinstance(event_id, str)
        and isinstance(title, str)
        and isinstance(start, dict)
        and isinstance(end, dict)
        and isinstance(updated, str)
        and (html_link is None or isinstance(html_link, str))
        and isinstance(status, str)
        and (location is None or isinstance(location, str))
    ):
        return _invalid_event()

    start_datetime = start.get("dateTime")
    end_datetime = end.get("dateTime")
    start_date = start.get("date")
    end_date = end.get("date")
    if isinstance(start_datetime, str) and isinstance(end_datetime, str):
        start_value = start_datetime
        end_value = end_datetime
        all_day = False
    elif isinstance(start_date, str) and isinstance(end_date, str):
        start_value = start_date
        end_value = end_date
        all_day = True
    else:
        return _invalid_event()
    try:
        updated_at = datetime.fromisoformat(updated)
    except ValueError:
        return _invalid_event()

    return GoogleCalendarEvent(
        id=event_id,
        title=title,
        start=start_value,
        end=end_value,
        updated_at=updated_at,
        html_link=html_link,
        status=status,
        location=location,
        all_day=all_day,
    )


def _invalid_event() -> GoogleCalendarEvent:
    return GoogleCalendarEvent(
        id="",
        title="",
        start="",
        end="",
        updated_at=datetime.fromtimestamp(0, tz=UTC),
    )
