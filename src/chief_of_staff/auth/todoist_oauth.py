"""Todoist confidential-client OAuth with state and Keychain-only secrets."""

from __future__ import annotations

import base64
import hmac
import json
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Final, Protocol

from chief_of_staff.auth.keychain import (
    KeychainSecretNotFound,
    KeychainSecretReference,
    MacOSKeychain,
)
from chief_of_staff.connectors.todoist import TODOIST_DATA_READ_SCOPE
from chief_of_staff.domain import (
    AuthorizationStatus,
    ConnectorAuthorizationMetadata,
    CredentialHealth,
    OAuthClientMetadata,
)
from chief_of_staff.persistence import StateStore

TODOIST_AUTHORIZATION_ENDPOINT: Final = "https://app.todoist.com/oauth/authorize"
TODOIST_TOKEN_ENDPOINT: Final = "https://api.todoist.com/oauth/access_token"  # noqa: S105
TODOIST_REVOCATION_ENDPOINT: Final = "https://api.todoist.com/api/v1/revoke"
TODOIST_USER_ENDPOINT: Final = "https://api.todoist.com/api/v1/user"
TODOIST_REDIRECT_URI: Final = "http://127.0.0.1:8765/oauth/callback"
TODOIST_CONNECTOR: Final = "todoist"
KEYCHAIN_SERVICE: Final = "org.chief-of-staff.oauth"
MAX_OAUTH_RESPONSE_BYTES: Final = 64 * 1024


class TodoistOAuthError(RuntimeError):
    """Raised for a bounded OAuth validation or provider failure."""


@dataclass(frozen=True, slots=True)
class TodoistOAuthTokenResponse:
    """Validated token response with secret fields hidden from representation."""

    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    granted_scope: str = TODOIST_DATA_READ_SCOPE
    expires_in_seconds: int = 315_360_000


@dataclass(frozen=True, slots=True)
class TodoistIdentity:
    """Minimum authenticated identity returned before credential persistence."""

    id: str
    email: str
    timezone: str | None = None


@dataclass(frozen=True, slots=True)
class TodoistAuthorizationResult:
    """Privacy-safe authorization outcome."""

    metadata: ConnectorAuthorizationMetadata
    access_token_issued: bool
    refresh_token_issued: bool
    refresh_tested: bool


class TodoistOAuthTokenClientProtocol(Protocol):
    """Injectable OAuth token and revocation boundary."""

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
    ) -> TodoistOAuthTokenResponse:
        """Exchange an authorization code without logging secrets."""

    def refresh(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> TodoistOAuthTokenResponse:
        """Rotate an expiring access grant."""

    def revoke(
        self,
        *,
        client_id: str,
        client_secret: str,
        access_token: str,
    ) -> None:
        """Revoke one OAuth access token."""


class TodoistIdentityClientProtocol(Protocol):
    """Injectable current-user lookup used only for account confirmation."""

    def get_identity(self, *, access_token: str) -> TodoistIdentity:
        """Return minimum account identity without persisting the response."""


@dataclass(frozen=True, slots=True)
class TodoistOAuthClientRegistrar:
    """Store a Brad-controlled client secret only in Keychain."""

    keychain: MacOSKeychain
    state_store: StateStore
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def register(
        self,
        *,
        application_name: str,
        application_owner: str,
        client_id: str,
        client_secret: str,
    ) -> OAuthClientMetadata:
        """Persist non-secret client metadata after securing its secret."""

        for name, value in (
            ("application name", application_name),
            ("application owner", application_owner),
            ("client ID", client_id),
        ):
            if not value.strip():
                raise ValueError(f"Todoist {name} must not be empty")
        if not client_secret:
            raise ValueError("Todoist client secret must not be empty")
        reference = KeychainSecretReference(
            service=KEYCHAIN_SERVICE,
            account=f"{TODOIST_CONNECTOR}:client-secret",
        )
        self.keychain.store(reference, client_secret)
        metadata = OAuthClientMetadata(
            connector=TODOIST_CONNECTOR,
            oauth_project_id=application_name.strip(),
            oauth_client_id=client_id.strip(),
            credential_service=reference.service,
            client_secret_account=reference.account,
            configured_at=self.clock(),
            application_owner=application_owner.strip(),
        )
        try:
            self.state_store.save_oauth_client(metadata)
        except BaseException:
            self.keychain.delete(reference)
            raise
        return metadata


@dataclass(frozen=True, slots=True)
class TodoistInstalledAppOAuth:
    """Run one state-protected browser flow and store tokens in Keychain."""

    keychain: MacOSKeychain
    state_store: StateStore
    token_client: TodoistOAuthTokenClientProtocol = field(
        default_factory=lambda: TodoistOAuthTokenClient(),
        repr=False,
        compare=False,
    )
    identity_client: TodoistIdentityClientProtocol = field(
        default_factory=lambda: TodoistIdentityClient(),
        repr=False,
        compare=False,
    )
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )
    browser_opener: Callable[[str], None] = field(
        default=lambda url: _open_system_browser(url),
        repr=False,
        compare=False,
    )

    def authorize_interactively(
        self,
        *,
        account_reference: str,
        timeout_seconds: int = 300,
        test_refresh: bool = True,
    ) -> TodoistAuthorizationResult:
        """Authorize the browser-selected account with exact read-only scope."""

        _validate_account_reference(account_reference)
        client = self.state_store.get_oauth_client(TODOIST_CONNECTOR)
        if client is None:
            raise TodoistOAuthError("Todoist OAuth client is not configured")
        state = secrets.token_urlsafe(32)
        callback: dict[str, str] = {}
        handler_type = _callback_handler(expected_state=state, callback=callback)
        with HTTPServer(("127.0.0.1", 8765), handler_type) as server:
            self.browser_opener(
                _authorization_url(
                    client_id=client.oauth_client_id,
                    state=state,
                )
            )
            deadline = time.monotonic() + timeout_seconds
            server.timeout = 1
            while "code" not in callback and "error" not in callback:
                if time.monotonic() >= deadline:
                    raise TodoistOAuthError(
                        "Todoist OAuth browser authorization timed out"
                    )
                server.handle_request()
        if "error" in callback:
            raise TodoistOAuthError("Todoist OAuth authorization was denied")
        code = callback.pop("code", "")
        if not code:
            raise TodoistOAuthError("Todoist OAuth callback omitted a code")

        client_secret_reference = KeychainSecretReference(
            service=client.credential_service,
            account=client.client_secret_account,
        )
        try:
            client_secret = self.keychain.read(client_secret_reference)
        except KeychainSecretNotFound:
            raise TodoistOAuthError("Todoist OAuth client secret is missing") from None
        try:
            token = self.token_client.exchange_code(
                client_id=client.oauth_client_id,
                client_secret=client_secret,
                code=code,
                redirect_uri=TODOIST_REDIRECT_URI,
            )
        finally:
            code = ""
        identity = self.identity_client.get_identity(
            access_token=token.access_token,
        )
        refresh_issued = token.refresh_token is not None
        refresh_tested = False
        if test_refresh and token.refresh_token is not None:
            token = self.token_client.refresh(
                client_id=client.oauth_client_id,
                client_secret=client_secret,
                refresh_token=token.refresh_token,
            )
            refresh_tested = True
        client_secret = ""
        metadata = self._store_authorization(
            account_reference=account_reference,
            account_identity=identity.email,
            token=token,
        )
        return TodoistAuthorizationResult(
            metadata=metadata,
            access_token_issued=True,
            refresh_token_issued=refresh_issued,
            refresh_tested=refresh_tested,
        )

    def refresh_authorization(
        self,
        *,
        account_reference: str,
    ) -> ConnectorAuthorizationMetadata:
        """Refresh an exact existing grant and rotate both Keychain values."""

        metadata = self.state_store.get_connector_authorization(TODOIST_CONNECTOR)
        client = self.state_store.get_oauth_client(TODOIST_CONNECTOR)
        if (
            metadata is None
            or client is None
            or metadata.account_reference != account_reference
            or metadata.granted_scope != TODOIST_DATA_READ_SCOPE
            or metadata.refresh_token_account is None
        ):
            raise TodoistOAuthError("Todoist refresh metadata is unavailable")
        client_reference = KeychainSecretReference(
            service=client.credential_service,
            account=client.client_secret_account,
        )
        refresh_reference = KeychainSecretReference(
            service=metadata.credential_service,
            account=metadata.refresh_token_account,
        )
        try:
            client_secret = self.keychain.read(client_reference)
            refresh_token = self.keychain.read(refresh_reference)
        except KeychainSecretNotFound:
            raise TodoistOAuthError("Todoist refresh credential is missing") from None
        token = self.token_client.refresh(
            client_id=client.oauth_client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
        )
        client_secret = ""
        refresh_token = ""
        if token.refresh_token is None:
            raise TodoistOAuthError("Todoist refresh omitted the rotated token")
        return self._store_authorization(
            account_reference=metadata.account_reference,
            account_identity=metadata.account_identity,
            token=token,
            authorized_at=metadata.authorized_at,
        )

    def disconnect(self, *, revoke: bool = True) -> None:
        """Optionally revoke and then delete the local grant and token values."""

        metadata = self.state_store.get_connector_authorization(TODOIST_CONNECTOR)
        client = self.state_store.get_oauth_client(TODOIST_CONNECTOR)
        if metadata is None:
            return
        access_reference = KeychainSecretReference(
            service=metadata.credential_service,
            account=metadata.access_token_account,
        )
        refresh_reference = (
            None
            if metadata.refresh_token_account is None
            else KeychainSecretReference(
                service=metadata.credential_service,
                account=metadata.refresh_token_account,
            )
        )
        if revoke:
            if client is None:
                raise TodoistOAuthError("Todoist client metadata is unavailable")
            client_reference = KeychainSecretReference(
                service=client.credential_service,
                account=client.client_secret_account,
            )
            try:
                client_secret = self.keychain.read(client_reference)
                access_token = self.keychain.read(access_reference)
            except KeychainSecretNotFound:
                raise TodoistOAuthError(
                    "Todoist revocation credential is missing"
                ) from None
            self.token_client.revoke(
                client_id=client.oauth_client_id,
                client_secret=client_secret,
                access_token=access_token,
            )
            client_secret = ""
            access_token = ""
        self.keychain.delete(access_reference)
        if refresh_reference is not None:
            self.keychain.delete(refresh_reference)
        self.state_store.delete_connector_authorization(TODOIST_CONNECTOR)

    def _store_authorization(
        self,
        *,
        account_reference: str,
        account_identity: str,
        token: TodoistOAuthTokenResponse,
        authorized_at: datetime | None = None,
    ) -> ConnectorAuthorizationMetadata:
        if token.granted_scope != TODOIST_DATA_READ_SCOPE:
            raise TodoistOAuthError(
                "Todoist granted scope does not match the approved scope"
            )
        now = self.clock()
        access_reference = KeychainSecretReference(
            service=KEYCHAIN_SERVICE,
            account=f"{TODOIST_CONNECTOR}:access-token:{account_reference}",
        )
        refresh_reference = (
            None
            if token.refresh_token is None
            else KeychainSecretReference(
                service=KEYCHAIN_SERVICE,
                account=f"{TODOIST_CONNECTOR}:refresh-token:{account_reference}",
            )
        )
        self.keychain.store(access_reference, token.access_token)
        if refresh_reference is not None and token.refresh_token is not None:
            self.keychain.store(refresh_reference, token.refresh_token)
        metadata = ConnectorAuthorizationMetadata(
            connector=TODOIST_CONNECTOR,
            account_reference=account_reference,
            account_identity=account_identity,
            granted_scope=token.granted_scope,
            credential_service=KEYCHAIN_SERVICE,
            access_token_account=access_reference.account,
            refresh_token_account=(
                None if refresh_reference is None else refresh_reference.account
            ),
            authorization_status=AuthorizationStatus.AUTHORIZED,
            credential_health=CredentialHealth.HEALTHY,
            refresh_health=(
                None if refresh_reference is None else CredentialHealth.HEALTHY
            ),
            token_expires_at=now + timedelta(seconds=token.expires_in_seconds),
            authorized_at=now if authorized_at is None else authorized_at,
            updated_at=now,
        )
        try:
            self.state_store.save_connector_authorization(metadata)
        except BaseException:
            self.keychain.delete(access_reference)
            if refresh_reference is not None:
                self.keychain.delete(refresh_reference)
            raise
        return metadata


class TodoistOAuthTokenClient:
    """Minimal Todoist OAuth token and RFC 7009 revocation client."""

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
    ) -> TodoistOAuthTokenResponse:
        return self._token_request(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            }
        )

    def refresh(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> TodoistOAuthTokenResponse:
        return self._token_request(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )

    def revoke(
        self,
        *,
        client_id: str,
        client_secret: str,
        access_token: str,
    ) -> None:
        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        request = urllib.request.Request(  # noqa: S310 - fixed HTTPS endpoint
            TODOIST_REVOCATION_ENDPOINT,
            data=urllib.parse.urlencode(
                {
                    "token": access_token,
                    "token_type_hint": "access_token",
                }
            ).encode(),
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                response.read(1024)
        except urllib.error.HTTPError, urllib.error.URLError, TimeoutError:
            raise TodoistOAuthError("Todoist token revocation failed") from None

    def _token_request(
        self,
        parameters: dict[str, str],
    ) -> TodoistOAuthTokenResponse:
        request = urllib.request.Request(  # noqa: S310 - fixed HTTPS endpoint
            TODOIST_TOKEN_ENDPOINT,
            data=urllib.parse.urlencode(parameters).encode(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                raw_response = bytearray(response.read(MAX_OAUTH_RESPONSE_BYTES + 1))
        except urllib.error.HTTPError, urllib.error.URLError, TimeoutError:
            raise TodoistOAuthError("Todoist OAuth token request failed") from None
        try:
            if len(raw_response) > MAX_OAUTH_RESPONSE_BYTES:
                raise TodoistOAuthError("Todoist OAuth response exceeded its limit")
            payload = json.loads(raw_response)
        except json.JSONDecodeError, UnicodeDecodeError:
            raise TodoistOAuthError("Todoist OAuth response was invalid") from None
        finally:
            raw_response[:] = b"\x00" * len(raw_response)
        if not isinstance(payload, dict):
            raise TodoistOAuthError("Todoist OAuth response was invalid")
        try:
            access_token = payload.get("access_token")
            refresh_token = payload.get("refresh_token")
            scope = payload.get("scope")
            expires_in = payload.get("expires_in", 315_360_000)
            if (
                not isinstance(access_token, str)
                or not access_token
                or not (refresh_token is None or isinstance(refresh_token, str))
                or scope != TODOIST_DATA_READ_SCOPE
                or isinstance(expires_in, bool)
                or not isinstance(expires_in, int)
                or expires_in <= 0
            ):
                raise TodoistOAuthError(
                    "Todoist OAuth response omitted approved grant fields"
                )
            return TodoistOAuthTokenResponse(
                access_token=access_token,
                refresh_token=refresh_token,
                granted_scope=scope,
                expires_in_seconds=expires_in,
            )
        finally:
            payload.clear()


class TodoistIdentityClient:
    """Retrieve only current-user confirmation fields from the live API."""

    def get_identity(self, *, access_token: str) -> TodoistIdentity:
        request = urllib.request.Request(  # noqa: S310 - fixed HTTPS endpoint
            TODOIST_USER_ENDPOINT,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                raw_response = bytearray(response.read(MAX_OAUTH_RESPONSE_BYTES + 1))
        except urllib.error.HTTPError, urllib.error.URLError, TimeoutError:
            raise TodoistOAuthError("Todoist account confirmation failed") from None
        try:
            if len(raw_response) > MAX_OAUTH_RESPONSE_BYTES:
                raise TodoistOAuthError("Todoist user response exceeded its limit")
            payload = json.loads(raw_response)
        except json.JSONDecodeError, UnicodeDecodeError:
            raise TodoistOAuthError("Todoist user response was invalid") from None
        finally:
            raw_response[:] = b"\x00" * len(raw_response)
        if not isinstance(payload, dict):
            raise TodoistOAuthError("Todoist user response was invalid")
        try:
            user_id = payload.get("id")
            email = payload.get("email")
            tz_info = payload.get("tz_info")
            timezone = None
            if isinstance(tz_info, dict):
                raw_timezone = tz_info.get("timezone")
                if isinstance(raw_timezone, str) and raw_timezone:
                    timezone = raw_timezone
            if (
                isinstance(user_id, bool)
                or not isinstance(user_id, (int, str))
                or not str(user_id).strip()
                or not isinstance(email, str)
                or not email.strip()
            ):
                raise TodoistOAuthError("Todoist user response omitted identity fields")
            return TodoistIdentity(
                id=str(user_id),
                email=email.strip(),
                timezone=timezone,
            )
        finally:
            payload.clear()


def _authorization_url(*, client_id: str, state: str) -> str:
    return (
        TODOIST_AUTHORIZATION_ENDPOINT
        + "?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": TODOIST_REDIRECT_URI,
                "response_type": "code",
                "scope": TODOIST_DATA_READ_SCOPE,
                "state": state,
            }
        )
    )


def _callback_handler(
    *,
    expected_state: str,
    callback: dict[str, str],
) -> type[BaseHTTPRequestHandler]:
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            parameters = urllib.parse.parse_qs(parsed.query)
            state = parameters.get("state", [""])[0]
            if parsed.path != "/oauth/callback" or not hmac.compare_digest(
                state, expected_state
            ):
                callback["error"] = "state_mismatch"
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Authorization rejected. You may close this window.")
                return
            error = parameters.get("error", [None])[0]
            code = parameters.get("code", [None])[0]
            if isinstance(error, str):
                callback["error"] = error
            elif isinstance(code, str) and code:
                callback["code"] = code
            else:
                callback["error"] = "invalid_callback"
            self.send_response(200 if "code" in callback else 400)
            self.end_headers()
            self.wfile.write(
                b"Authorization received. You may return to Chief of Staff."
            )

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return CallbackHandler


def _open_system_browser(url: str) -> None:
    completed = subprocess.run(  # noqa: S603 - fixed system opener
        ("/usr/bin/open", url),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        raise TodoistOAuthError("the system browser could not be opened")


def _validate_account_reference(account_reference: str) -> None:
    if (
        not account_reference.strip()
        or "@" in account_reference
        or any(character.isspace() for character in account_reference)
    ):
        raise ValueError("Todoist account reference must be an opaque alias")
