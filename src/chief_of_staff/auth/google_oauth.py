"""Google installed-application OAuth with state, PKCE, and Keychain storage."""

from __future__ import annotations

import base64
import hashlib
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
from pathlib import Path
from typing import Final, Protocol

from chief_of_staff.auth.keychain import (
    KeychainSecretReference,
    MacOSKeychain,
)
from chief_of_staff.connectors.google_calendar import (
    GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE,
)
from chief_of_staff.domain import (
    AuthorizationStatus,
    ConnectorAuthorizationMetadata,
    CredentialHealth,
    OAuthClientMetadata,
)
from chief_of_staff.persistence import StateStore

GOOGLE_AUTHORIZATION_ENDPOINT: Final = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_EXCHANGE_ENDPOINT: Final = "https://oauth2.googleapis.com/token"
KEYCHAIN_SERVICE: Final = "org.chief-of-staff.oauth"
GOOGLE_CALENDAR_CONNECTOR: Final = "google_calendar"
MAX_CLIENT_FILE_BYTES: Final = 64 * 1024
MAX_TOKEN_RESPONSE_BYTES: Final = 64 * 1024


class OAuthError(RuntimeError):
    """Raised for a bounded OAuth validation or provider failure."""


@dataclass(frozen=True, slots=True)
class OAuthImportResult:
    """Non-secret result of importing and deleting a client file."""

    metadata: OAuthClientMetadata
    source_deleted: bool


@dataclass(frozen=True, slots=True)
class OAuthTokenResponse:
    """Validated token response with a secret excluded from representation."""

    access_token: str = field(repr=False)
    granted_scope: str
    expires_in_seconds: int


class OAuthTokenClient(Protocol):
    """Injectable authorization-code exchange boundary."""

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> OAuthTokenResponse:
        """Exchange one code without logging request or response content."""


class GoogleOAuthTokenClient:
    """Minimal Google token endpoint client for installed applications."""

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> OAuthTokenResponse:
        form = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            }
        ).encode()
        request = urllib.request.Request(  # noqa: S310 - fixed HTTPS endpoint
            GOOGLE_OAUTH_EXCHANGE_ENDPOINT,
            data=form,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - fixed HTTPS endpoint
                request,
                timeout=30,
            ) as response:
                raw_response = response.read(MAX_TOKEN_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError, urllib.error.URLError, TimeoutError:
            raise OAuthError("Google OAuth code exchange failed") from None
        if len(raw_response) > MAX_TOKEN_RESPONSE_BYTES:
            raise OAuthError("Google OAuth token response exceeded its limit")
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError, UnicodeDecodeError:
            raise OAuthError("Google OAuth token response was invalid") from None
        if not isinstance(payload, dict):
            raise OAuthError("Google OAuth token response was invalid")

        access_token = payload.get("access_token")
        scope = payload.get("scope")
        expires_in = payload.get("expires_in")
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(scope, str)
            or not isinstance(expires_in, int)
            or isinstance(expires_in, bool)
            or expires_in <= 0
        ):
            raise OAuthError("Google OAuth token response omitted required fields")
        if frozenset(scope.split()) != frozenset(
            {GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE}
        ):
            raise OAuthError("Google granted scopes do not match the approved scope")
        return OAuthTokenResponse(
            access_token=access_token,
            granted_scope=GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE,
            expires_in_seconds=expires_in,
        )


@dataclass(frozen=True, slots=True)
class GoogleOAuthClientRegistrar:
    """Store one validated Desktop client secret only in Keychain."""

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
        project_id: str,
        client_id: str,
        client_secret: str,
    ) -> OAuthClientMetadata:
        """Register non-secret metadata after securing the secret in Keychain."""

        _validate_google_client_identifiers(project_id, client_id)
        if not client_secret:
            raise ValueError("OAuth client secret must not be empty")

        reference = KeychainSecretReference(
            service=KEYCHAIN_SERVICE,
            account=f"{GOOGLE_CALENDAR_CONNECTOR}:client-secret",
        )
        self.keychain.store(reference, client_secret)
        metadata = OAuthClientMetadata(
            connector=GOOGLE_CALENDAR_CONNECTOR,
            oauth_project_id=project_id,
            oauth_client_id=client_id,
            credential_service=reference.service,
            client_secret_account=reference.account,
            configured_at=self.clock(),
        )
        try:
            self.state_store.save_oauth_client(metadata)
        except BaseException:
            self.keychain.delete(reference)
            raise
        return metadata


@dataclass(frozen=True, slots=True)
class GoogleOAuthClientImporter:
    """Import one Google Desktop client file directly into Keychain and SQLite."""

    keychain: MacOSKeychain
    state_store: StateStore
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def import_and_delete(self, source: Path) -> OAuthImportResult:
        """Import a bounded client file and remove its secret-bearing source."""

        if not source.is_file():
            raise ValueError("OAuth client source must be an existing file")
        with source.open("rb") as stream:
            raw = bytearray(stream.read(MAX_CLIENT_FILE_BYTES + 1))
        try:
            if len(raw) > MAX_CLIENT_FILE_BYTES:
                raise ValueError("OAuth client source exceeds its size limit")
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError, UnicodeDecodeError:
                raise ValueError("OAuth client source is not valid JSON") from None
            installed = payload.get("installed") if isinstance(payload, dict) else None
            if not isinstance(installed, dict):
                raise ValueError("OAuth client must be a Google Desktop client")
            project_id = installed.get("project_id")
            client_id = installed.get("client_id")
            client_secret = installed.get("client_secret")
            auth_uri = installed.get("auth_uri")
            token_uri = installed.get("token_uri")
            if (
                not isinstance(project_id, str)
                or not project_id
                or not isinstance(client_id, str)
                or not client_id
                or not isinstance(client_secret, str)
                or not client_secret
                or not isinstance(auth_uri, str)
                or not auth_uri
                or not isinstance(token_uri, str)
                or not token_uri
            ):
                raise ValueError("OAuth client source omitted required fields")
            if auth_uri != GOOGLE_AUTHORIZATION_ENDPOINT:
                raise ValueError("OAuth client authorization endpoint is unexpected")
            if token_uri != GOOGLE_OAUTH_EXCHANGE_ENDPOINT:
                raise ValueError("OAuth client token endpoint is unexpected")
            metadata = GoogleOAuthClientRegistrar(
                keychain=self.keychain,
                state_store=self.state_store,
                clock=self.clock,
            ).register(
                project_id=project_id,
                client_id=client_id,
                client_secret=client_secret,
            )
        finally:
            raw[:] = b"\x00" * len(raw)

        source.unlink()
        return OAuthImportResult(metadata=metadata, source_deleted=True)


@dataclass(frozen=True, slots=True)
class GoogleInstalledAppOAuth:
    """Open a bounded system-browser flow and persist only the access token."""

    keychain: MacOSKeychain
    state_store: StateStore
    token_client: OAuthTokenClient = field(
        default_factory=GoogleOAuthTokenClient,
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
        confirmed_account_identity: str,
        timeout_seconds: int = 300,
    ) -> ConnectorAuthorizationMetadata:
        """Authorize the confirmed account through a loopback callback."""

        client = self.state_store.get_oauth_client(GOOGLE_CALENDAR_CONNECTOR)
        if client is None:
            raise OAuthError("Google Calendar OAuth client is not configured")
        _validate_account_inputs(account_reference, confirmed_account_identity)

        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        challenge = _pkce_challenge(code_verifier)
        callback: dict[str, str] = {}

        handler_type = _callback_handler(
            expected_state=state,
            callback=callback,
        )
        with HTTPServer(("127.0.0.1", 0), handler_type) as server:
            port = int(server.server_address[1])
            redirect_uri = f"http://127.0.0.1:{port}/oauth2/callback"
            authorization_url = _authorization_url(
                client_id=client.oauth_client_id,
                redirect_uri=redirect_uri,
                state=state,
                code_challenge=challenge,
                account_identity=confirmed_account_identity,
            )
            self.browser_opener(authorization_url)
            deadline = time.monotonic() + timeout_seconds
            server.timeout = 1
            while "code" not in callback and "error" not in callback:
                if time.monotonic() >= deadline:
                    raise OAuthError("Google OAuth browser authorization timed out")
                server.handle_request()

        if "error" in callback:
            raise OAuthError("Google OAuth authorization was denied or invalid")
        code = callback.get("code")
        if code is None:
            raise OAuthError("Google OAuth callback omitted its code")

        client_secret_reference = KeychainSecretReference(
            service=client.credential_service,
            account=client.client_secret_account,
        )
        client_secret = self.keychain.read(client_secret_reference)
        token = self.token_client.exchange_code(
            client_id=client.oauth_client_id,
            client_secret=client_secret,
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
        return self._store_authorization(
            client=client,
            account_reference=account_reference,
            confirmed_account_identity=confirmed_account_identity,
            token=token,
        )

    def _store_authorization(
        self,
        *,
        client: OAuthClientMetadata,
        account_reference: str,
        confirmed_account_identity: str,
        token: OAuthTokenResponse,
    ) -> ConnectorAuthorizationMetadata:
        now = self.clock()
        access_token_reference = KeychainSecretReference(
            service=KEYCHAIN_SERVICE,
            account=f"{GOOGLE_CALENDAR_CONNECTOR}:access-token:{account_reference}",
        )
        self.keychain.store(access_token_reference, token.access_token)
        metadata = ConnectorAuthorizationMetadata(
            connector=GOOGLE_CALENDAR_CONNECTOR,
            account_reference=account_reference,
            account_identity=confirmed_account_identity,
            granted_scope=token.granted_scope,
            credential_service=access_token_reference.service,
            access_token_account=access_token_reference.account,
            refresh_token_account=None,
            authorization_status=AuthorizationStatus.AUTHORIZED,
            credential_health=CredentialHealth.HEALTHY,
            refresh_health=None,
            token_expires_at=now + timedelta(seconds=token.expires_in_seconds),
            authorized_at=now,
            updated_at=now,
        )
        try:
            self.state_store.save_connector_authorization(metadata)
        except BaseException:
            self.keychain.delete(access_token_reference)
            raise
        return metadata


def _authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    account_identity: str,
) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "include_granted_scopes": "false",
            "login_hint": account_identity,
            "prompt": "select_account consent",
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE,
            "state": state,
        }
    )
    return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{query}"


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _validate_account_inputs(account_reference: str, account_identity: str) -> None:
    if (
        not account_reference
        or "@" in account_reference
        or any(character.isspace() for character in account_reference)
    ):
        raise ValueError("account reference must be an opaque non-email alias")
    if "@" not in account_identity or any(
        character.isspace() for character in account_identity
    ):
        raise ValueError("confirmed Google account identity must be an email")


def _validate_google_client_identifiers(project_id: str, client_id: str) -> None:
    if (
        not project_id
        or any(character.isspace() for character in project_id)
        or not client_id.endswith(".apps.googleusercontent.com")
        or any(character.isspace() for character in client_id)
    ):
        raise ValueError("OAuth client identifiers are invalid")


def _open_system_browser(url: str) -> None:
    completed = subprocess.run(  # noqa: S603 - fixed /usr/bin/open executable
        ("/usr/bin/open", url),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        raise OAuthError("system browser could not be opened")


def _callback_handler(
    *,
    expected_state: str,
    callback: dict[str, str],
) -> type[BaseHTTPRequestHandler]:
    class OAuthCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            code = query.get("code", [None])[0]
            state = query.get("state", [None])[0]
            error = query.get("error", [None])[0]
            valid_state = isinstance(state, str) and hmac.compare_digest(
                state,
                expected_state,
            )
            if (
                parsed.path != "/oauth2/callback"
                or not valid_state
                or not isinstance(code, str)
                or error is not None
            ):
                callback["error"] = "invalid_callback"
                self.send_response(400)
                message = b"Authorization was not accepted. Return to Chief of Staff."
            else:
                callback["code"] = code
                self.send_response(200)
                message = b"Authorization received. You may close this window."
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)

        def log_message(self, _format: str, *args: object) -> None:
            del args

    return OAuthCallbackHandler
