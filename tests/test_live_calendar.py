"""Synthetic security and lifecycle tests for the bounded live Calendar path."""

from __future__ import annotations

import json
import stat
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path

import pytest

from chief_of_staff.auth.google_oauth import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GOOGLE_CALENDAR_CONNECTOR,
    GOOGLE_OAUTH_EXCHANGE_ENDPOINT,
    KEYCHAIN_SERVICE,
    GoogleInstalledAppOAuth,
    GoogleOAuthClientImporter,
    OAuthTokenResponse,
)
from chief_of_staff.auth.keychain import (
    KeychainSecretNotFound,
    KeychainSecretReference,
    MacOSKeychain,
    SecurityCommandResult,
)
from chief_of_staff.connectors import (
    GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE,
    CalendarAuthenticationError,
    CalendarAuthorization,
    CalendarAuthorizationUnavailable,
    GoogleCalendarConnector,
    GoogleCalendarEvent,
    GoogleCalendarHttpTransport,
    GoogleCalendarListRequest,
    GoogleCalendarPage,
    StoredGoogleCalendarAuthorizationProvider,
)
from chief_of_staff.domain import (
    AuthorizationStatus,
    ConnectorAuthorizationMetadata,
    CredentialHealth,
    OAuthClientMetadata,
)
from chief_of_staff.live_trial import LiveCalendarTrialRunner
from chief_of_staff.persistence import Database, StateStore
from chief_of_staff.pipeline import resolve_context

NOW = datetime(2026, 7, 25, 14, 0, tzinfo=UTC)
CLIENT_ID = "synthetic-client.apps.googleusercontent.com"
PROJECT_ID = "synthetic-owned-project"
ACCOUNT_IDENTITY = "selected@example.invalid"
ACCOUNT_REFERENCE = "primary-user"


@dataclass(slots=True)
class _FakeSecurityRunner:
    items: dict[tuple[str, str], str] = field(default_factory=dict)
    calls: list[tuple[tuple[str, ...], str | None]] = field(default_factory=list)

    def __call__(
        self,
        arguments: tuple[str, ...],
        *,
        input_text: str | None,
        capture_output: bool,
    ) -> SecurityCommandResult:
        del capture_output
        self.calls.append((arguments, input_text))
        account = _argument_value(arguments, "-a")
        service = _argument_value(arguments, "-s")
        key = (service, account)
        if arguments[0] == "add-generic-password":
            assert input_text is not None
            self.items[key] = input_text.rstrip("\n")
            return SecurityCommandResult(returncode=0)
        if arguments[0] == "find-generic-password":
            if key not in self.items:
                return SecurityCommandResult(returncode=44)
            return SecurityCommandResult(
                returncode=0,
                stdout=f"{self.items[key]}\n" if "-w" in arguments else "",
            )
        if arguments[0] == "delete-generic-password":
            existed = self.items.pop(key, None) is not None
            return SecurityCommandResult(returncode=0 if existed else 44)
        raise AssertionError("unexpected security operation")


def _argument_value(arguments: tuple[str, ...], flag: str) -> str:
    return arguments[arguments.index(flag) + 1]


def _keychain() -> tuple[MacOSKeychain, _FakeSecurityRunner]:
    runner = _FakeSecurityRunner()
    return MacOSKeychain(command_runner=runner), runner


def _save_client(store: StateStore) -> OAuthClientMetadata:
    metadata = OAuthClientMetadata(
        connector=GOOGLE_CALENDAR_CONNECTOR,
        oauth_project_id=PROJECT_ID,
        oauth_client_id=CLIENT_ID,
        credential_service=KEYCHAIN_SERVICE,
        client_secret_account="google_calendar:client-secret",
        configured_at=NOW,
    )
    store.save_oauth_client(metadata)
    return metadata


def _save_authorization(
    store: StateStore,
    *,
    expires_at: datetime = NOW + timedelta(hours=1),
) -> ConnectorAuthorizationMetadata:
    metadata = ConnectorAuthorizationMetadata(
        connector=GOOGLE_CALENDAR_CONNECTOR,
        account_reference=ACCOUNT_REFERENCE,
        account_identity=ACCOUNT_IDENTITY,
        granted_scope=GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE,
        credential_service=KEYCHAIN_SERVICE,
        access_token_account=(
            f"{GOOGLE_CALENDAR_CONNECTOR}:access-token:{ACCOUNT_REFERENCE}"
        ),
        authorization_status=AuthorizationStatus.AUTHORIZED,
        credential_health=CredentialHealth.HEALTHY,
        token_expires_at=expires_at,
        authorized_at=NOW,
        updated_at=NOW,
    )
    store.save_connector_authorization(metadata)
    return metadata


def test_keychain_boundary_keeps_secret_out_of_arguments_and_repr() -> None:
    keychain, runner = _keychain()
    reference = KeychainSecretReference("test.service", "test-account")
    synthetic_secret = "synthetic-sensitive-value"

    keychain.store(reference, synthetic_secret)

    assert all(synthetic_secret not in argument for argument in runner.calls[0][0])
    assert runner.calls[0][1] == f"{synthetic_secret}\n"
    assert keychain.exists(reference)
    assert keychain.read(reference) == synthetic_secret
    assert synthetic_secret not in repr(keychain)
    assert keychain.delete(reference)
    with pytest.raises(KeychainSecretNotFound):
        keychain.read(reference)


def test_client_import_moves_secret_to_keychain_and_deletes_source(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    source = tmp_path / "desktop-client.json"
    client_secret = "synthetic-client-secret"
    source.write_text(
        json.dumps(
            {
                "installed": {
                    "auth_uri": GOOGLE_AUTHORIZATION_ENDPOINT,
                    "client_id": CLIENT_ID,
                    "client_secret": client_secret,
                    "project_id": PROJECT_ID,
                    "token_uri": GOOGLE_OAUTH_EXCHANGE_ENDPOINT,
                }
            }
        ),
        encoding="utf-8",
    )
    keychain, runner = _keychain()

    with Database.open(database_path) as database:
        store = StateStore(database)
        result = GoogleOAuthClientImporter(
            keychain=keychain,
            state_store=store,
            clock=lambda: NOW,
        ).import_and_delete(source)

        assert result.source_deleted
        assert not source.exists()
        assert result.metadata.oauth_project_id == PROJECT_ID
        assert store.get_oauth_client(GOOGLE_CALENDAR_CONNECTOR) == result.metadata
        assert store.get_connector_authorization(GOOGLE_CALENDAR_CONNECTOR) is None

    assert client_secret in runner.items.values()
    assert client_secret.encode() not in database_path.read_bytes()
    assert stat.S_IMODE(database_path.stat().st_mode) == 0o600


@dataclass(slots=True)
class _FakeTokenClient:
    response: OAuthTokenResponse
    received_code: str | None = None
    received_verifier: str | None = None
    received_redirect_uri: str | None = None

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> OAuthTokenResponse:
        assert client_id == CLIENT_ID
        assert client_secret == "synthetic-client-secret"
        self.received_code = code
        self.received_verifier = code_verifier
        self.received_redirect_uri = redirect_uri
        return self.response


@dataclass(slots=True)
class _CallbackBrowser:
    authorization_url: str | None = None
    callback_thread: threading.Thread | None = None

    def __call__(self, authorization_url: str) -> None:
        self.authorization_url = authorization_url
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(authorization_url).query)
        redirect_uri = query["redirect_uri"][0]
        state_value = query["state"][0]
        callback_url = (
            f"{redirect_uri}?"
            f"{urllib.parse.urlencode({'code': 'synthetic-code', 'state': state_value})}"
        )

        def send_callback() -> None:
            with urllib.request.urlopen(  # noqa: S310 - loopback test callback
                callback_url,
                timeout=5,
            ) as response:
                response.read()

        self.callback_thread = threading.Thread(target=send_callback)
        self.callback_thread.start()


def test_installed_oauth_uses_exact_scope_state_pkce_and_keychain(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    keychain, runner = _keychain()
    client_secret_reference = KeychainSecretReference(
        KEYCHAIN_SERVICE,
        "google_calendar:client-secret",
    )
    keychain.store(client_secret_reference, "synthetic-client-secret")
    access_token = "synthetic-access-value"
    token_client = _FakeTokenClient(
        OAuthTokenResponse(
            access_token=access_token,
            granted_scope=GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE,
            expires_in_seconds=3600,
        )
    )
    browser = _CallbackBrowser()

    with Database.open(database_path) as database:
        store = StateStore(database)
        _save_client(store)
        metadata = GoogleInstalledAppOAuth(
            keychain=keychain,
            state_store=store,
            token_client=token_client,
            clock=lambda: NOW,
            browser_opener=browser,
        ).authorize_interactively(
            account_reference=ACCOUNT_REFERENCE,
            confirmed_account_identity=ACCOUNT_IDENTITY,
            timeout_seconds=5,
        )

        stored = store.get_connector_authorization(GOOGLE_CALENDAR_CONNECTOR)
        assert stored == metadata
        assert stored is not None
        assert stored.granted_scope == (GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE)
        assert stored.account_identity == ACCOUNT_IDENTITY

    assert browser.callback_thread is not None
    browser.callback_thread.join(timeout=5)
    assert browser.authorization_url is not None
    authorization_query = urllib.parse.parse_qs(
        urllib.parse.urlsplit(browser.authorization_url).query
    )
    assert authorization_query["scope"] == [GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE]
    assert authorization_query["prompt"] == ["select_account consent"]
    assert authorization_query["login_hint"] == [ACCOUNT_IDENTITY]
    assert authorization_query["code_challenge_method"] == ["S256"]
    assert "access_type" not in authorization_query
    assert token_client.received_code == "synthetic-code"
    assert token_client.received_verifier is not None
    assert access_token in runner.items.values()
    assert access_token.encode() not in database_path.read_bytes()


@dataclass(slots=True)
class _FakeHttpResponse:
    body: bytes

    def read(self, amount: int = -1) -> bytes:
        return self.body[:amount]

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        del args


@dataclass(slots=True)
class _RecordingOpener:
    response: _FakeHttpResponse
    request: urllib.request.Request | None = None

    def __call__(
        self,
        request: urllib.request.Request,
        *,
        timeout: int,
    ) -> _FakeHttpResponse:
        assert timeout == 30
        self.request = request
        return self.response


def _list_request() -> GoogleCalendarListRequest:
    context = resolve_context(
        run_id="live-http-test",
        briefing_date=NOW.date(),
        timezone="America/New_York",
        lookahead_days=7,
    )
    return GoogleCalendarListRequest(
        calendar_id="primary",
        time_min=context.retrieval_window.starts_at,
        time_max=context.retrieval_window.ends_at,
        timezone=context.timezone,
        page_token=None,
    )


def test_live_transport_calls_only_primary_events_list_and_minimizes_payload() -> None:
    keychain, _runner = _keychain()
    reference = KeychainSecretReference(
        KEYCHAIN_SERVICE,
        "google_calendar:access-token:primary-user",
    )
    access_token = "synthetic-access-value"
    keychain.store(reference, access_token)
    raw_private_marker = "raw-description-must-not-survive"
    response_body = json.dumps(
        {
            "items": [
                {
                    "attendees": [{"email": "private-person@example.invalid"}],
                    "description": raw_private_marker,
                    "end": {"dateTime": "2026-07-25T11:00:00-04:00"},
                    "htmlLink": "https://calendar.google.com/calendar/event?eid=safe",
                    "id": "event-1",
                    "location": "Room",
                    "start": {"dateTime": "2026-07-25T10:00:00-04:00"},
                    "status": "confirmed",
                    "summary": "Synthetic Event",
                    "updated": "2026-07-24T18:00:00Z",
                }
            ],
            "nextPageToken": "next-page",
        }
    ).encode()
    opener = _RecordingOpener(_FakeHttpResponse(response_body))
    transport = GoogleCalendarHttpTransport(
        keychain=keychain,
        access_token_reference=reference,
        url_opener=opener,
    )
    authorization = CalendarAuthorization(
        account_reference=ACCOUNT_REFERENCE,
        granted_scopes=frozenset({GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE}),
        credential_reference=reference.identifier,
    )

    page = transport.list_events(authorization, _list_request())

    assert opener.request is not None
    parsed_url = urllib.parse.urlsplit(opener.request.full_url)
    query = urllib.parse.parse_qs(parsed_url.query)
    assert parsed_url.scheme == "https"
    assert parsed_url.netloc == "www.googleapis.com"
    assert parsed_url.path == "/calendar/v3/calendars/primary/events"
    assert query["singleEvents"] == ["true"]
    assert query["showDeleted"] == ["false"]
    assert query["orderBy"] == ["startTime"]
    assert query["maxResults"] == ["250"]
    assert access_token not in opener.request.full_url
    assert opener.request.get_method() == "GET"
    assert page.next_page_token == "next-page"
    assert page.events[0].id == "event-1"
    assert raw_private_marker not in repr(page)
    assert "private-person" not in repr(page)
    for mutation in ("create", "insert", "update", "patch", "delete", "write"):
        assert not hasattr(transport, mutation)


@dataclass(slots=True)
class _RejectingOpener:
    def __call__(
        self,
        request: urllib.request.Request,
        *,
        timeout: int,
    ) -> _FakeHttpResponse:
        del request, timeout
        raise urllib.error.HTTPError(
            url="https://www.googleapis.com/",
            code=401,
            msg="Unauthorized",
            hdrs=Message(),
            fp=None,
        )


def test_live_transport_distinguishes_provider_authorization_failure() -> None:
    keychain, _runner = _keychain()
    reference = KeychainSecretReference(
        KEYCHAIN_SERVICE,
        "google_calendar:access-token:primary-user",
    )
    keychain.store(reference, "synthetic-access-value")
    transport = GoogleCalendarHttpTransport(
        keychain=keychain,
        access_token_reference=reference,
        url_opener=_RejectingOpener(),
    )
    authorization = CalendarAuthorization(
        account_reference=ACCOUNT_REFERENCE,
        granted_scopes=frozenset({GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE}),
        credential_reference=reference.identifier,
    )

    with pytest.raises(CalendarAuthenticationError):
        transport.list_events(authorization, _list_request())


def test_stored_authorization_distinguishes_expired_and_missing_keychain(
    tmp_path: Path,
) -> None:
    keychain, _runner = _keychain()
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        _save_client(store)
        metadata = _save_authorization(store, expires_at=NOW + timedelta(hours=1))
        provider = StoredGoogleCalendarAuthorizationProvider(
            state_store=store,
            keychain=keychain,
            clock=lambda: NOW,
        )
        with pytest.raises(CalendarAuthorizationUnavailable):
            provider.get_calendar_authorization(ACCOUNT_REFERENCE)

        reference = KeychainSecretReference(
            metadata.credential_service,
            metadata.access_token_account,
        )
        keychain.store(reference, "synthetic-access-value")
        authorization = provider.get_calendar_authorization(ACCOUNT_REFERENCE)
        assert authorization.credential_reference == reference.identifier

        expired_provider = StoredGoogleCalendarAuthorizationProvider(
            state_store=store,
            keychain=keychain,
            clock=lambda: NOW + timedelta(hours=2),
        )
        with pytest.raises(CalendarAuthorizationUnavailable):
            expired_provider.get_calendar_authorization(ACCOUNT_REFERENCE)


@dataclass(slots=True)
class _TwoPageCalendarTransport:
    calls: list[GoogleCalendarListRequest] = field(default_factory=list)

    def list_events(
        self,
        authorization: CalendarAuthorization,
        request: GoogleCalendarListRequest,
    ) -> GoogleCalendarPage:
        assert authorization.account_reference == ACCOUNT_REFERENCE
        self.calls.append(request)
        if request.page_token is None:
            return GoogleCalendarPage(
                events=(
                    GoogleCalendarEvent(
                        id="event-today",
                        title="Synthetic Private Event",
                        start="2026-07-25T10:00:00-04:00",
                        end="2026-07-25T11:00:00-04:00",
                        updated_at=NOW - timedelta(hours=1),
                        html_link=(
                            "https://calendar.google.com/calendar/event?eid=today"
                        ),
                    ),
                ),
                next_page_token="page-2",
            )
        return GoogleCalendarPage(
            events=(
                GoogleCalendarEvent(
                    id="event-next",
                    title="Synthetic Future Event",
                    start="2026-07-28T13:00:00-04:00",
                    end="2026-07-28T14:00:00-04:00",
                    updated_at=NOW - timedelta(hours=2),
                    html_link=("https://calendar.google.com/calendar/event?eid=next"),
                ),
            )
        )


def test_bounded_trial_persists_only_minimal_state_and_private_output(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    feature_path = repository / "docs/product/features/daily-briefing-v1.md"
    roadmap_path = repository / "docs/roadmap.md"
    feature_path.parent.mkdir(parents=True)
    feature_path.write_text(
        "# Daily Briefing v1\n\nSynthetic approved context.\n",
        encoding="utf-8",
    )
    roadmap_path.write_text(
        "# Roadmap\n\nSynthetic approved sequence.\n",
        encoding="utf-8",
    )
    database_path = tmp_path / "private/state.sqlite3"
    output_directory = tmp_path / "private/briefings"
    keychain, _runner = _keychain()
    access_token = "synthetic-access-value"
    raw_marker = "raw-payload-marker"

    with Database.open(database_path) as database:
        store = StateStore(database)
        _save_client(store)
        metadata = _save_authorization(store)
        reference = KeychainSecretReference(
            metadata.credential_service,
            metadata.access_token_account,
        )
        keychain.store(reference, access_token)
        transport = _TwoPageCalendarTransport()
        connector = GoogleCalendarConnector(
            account_reference=ACCOUNT_REFERENCE,
            authorization_provider=StoredGoogleCalendarAuthorizationProvider(
                state_store=store,
                keychain=keychain,
                clock=lambda: NOW,
            ),
            transport=transport,
            clock=lambda: NOW,
        )

        report = LiveCalendarTrialRunner(
            state_store=store,
            repository_root=repository,
            repository_paths=(
                Path("docs/product/features/daily-briefing-v1.md"),
                Path("docs/roadmap.md"),
            ),
            calendar_connector=connector,
            output_directory=output_directory,
            clock=lambda: NOW,
        ).run()

        inspection = store.inspect_state()
        assert inspection.connector_runs == 2
        assert inspection.briefing_runs == 1
        assert inspection.source_evidence == 4
        assert inspection.oauth_clients == 1
        assert inspection.connector_authorizations == 1
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM source_evidence WHERE excerpt IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
        authorization = store.get_connector_authorization(GOOGLE_CALENDAR_CONNECTOR)
        assert authorization is not None
        assert authorization.last_used_at == NOW

    assert report.calendar_event_count == 2
    assert report.calendar_page_count == 2
    assert report.pagination_occurred
    assert report.briefing_word_count <= 800
    assert not report.raw_payload_persisted
    assert not report.hosted_inference_used
    assert stat.S_IMODE(report.output_path.stat().st_mode) == 0o600
    output = report.output_path.read_text(encoding="utf-8")
    assert "Synthetic Private Event" in output
    assert raw_marker not in output
    database_bytes = database_path.read_bytes()
    assert access_token.encode() not in database_bytes
    assert raw_marker.encode() not in database_bytes
    assert stat.S_IMODE(database_path.stat().st_mode) == 0o600
    assert all(call.calendar_id == "primary" for call in transport.calls)
    assert [call.page_token for call in transport.calls] == [None, "page-2"]
