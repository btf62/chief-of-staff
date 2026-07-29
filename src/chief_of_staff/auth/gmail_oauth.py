"""Installed-app OAuth for one exact Work Gmail connector instance."""

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
    KeychainSecretNotFound,
    KeychainSecretReference,
    MacOSKeychain,
)
from chief_of_staff.connectors.gmail import (
    GMAIL_READONLY_SCOPE,
    GMAIL_WORK_ACCOUNT,
    GMAIL_WORK_ALIAS,
    GMAIL_WORK_INSTANCE,
)
from chief_of_staff.domain import (
    AuthorizationStatus,
    ConnectorAuthorizationMetadata,
    ConnectorDomain,
    ConnectorInstanceMetadata,
    CredentialHealth,
    OAuthClientMetadata,
)
from chief_of_staff.persistence import StateStore

GMAIL_OAUTH_PROJECT: Final = "nrc-chief-of-staff"
GMAIL_CONNECTOR_PROVIDER: Final = "gmail"
GMAIL_AUTHORIZATION_ENDPOINT: Final = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_DESKTOP_CLIENT_AUTHORIZATION_ENDPOINTS: Final = frozenset(
    {
        GMAIL_AUTHORIZATION_ENDPOINT,
        "https://accounts.google.com/o/oauth2/auth",
    }
)
GMAIL_TOKEN_ENDPOINT: Final = "https://oauth2.googleapis.com/token"  # noqa: S105
GMAIL_REVOCATION_ENDPOINT: Final = "https://oauth2.googleapis.com/revoke"
GMAIL_PROFILE_ENDPOINT: Final = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
GMAIL_KEYCHAIN_SERVICE: Final = "org.chief-of-staff.oauth"
MAX_GMAIL_OAUTH_RESPONSE_BYTES: Final = 64 * 1024
MAX_GMAIL_CLIENT_FILE_BYTES: Final = 64 * 1024


class GmailOAuthError(RuntimeError):
    """Raised for a bounded Work Gmail OAuth failure."""


class GmailOAuthStateMismatch(GmailOAuthError):
    """Raised when the browser callback does not match the session state."""


@dataclass(frozen=True, slots=True)
class GmailOAuthTokenResponse:
    """Validated token response with secret values excluded from representation."""

    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    granted_scope: str = GMAIL_READONLY_SCOPE
    expires_in_seconds: int = 3600


@dataclass(frozen=True, slots=True)
class GmailOAuthAuthorizationResult:
    """Privacy-safe authorization facts."""

    metadata: ConnectorAuthorizationMetadata
    access_token_issued: bool
    refresh_token_issued: bool


@dataclass(frozen=True, slots=True)
class GmailOAuthImportResult:
    """Result of importing and deleting a Desktop client file."""

    metadata: OAuthClientMetadata
    source_deleted: bool


class GmailOAuthTokenBoundary(Protocol):
    """Exchange, refresh, and revoke secrets without logging them."""

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> GmailOAuthTokenResponse:
        """Exchange one authorization code."""

    def refresh(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> GmailOAuthTokenResponse:
        """Refresh one access token."""

    def revoke(self, token: str) -> None:
        """Revoke one Google grant token."""


class GmailProfileBoundary(Protocol):
    """Verify the account represented by one access token."""

    def get_email_address(self, access_token: str) -> str:
        """Return the exact provider account identity."""


class GoogleGmailOAuthTokenClient:
    """Minimal fixed-endpoint Google token and revocation client."""

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> GmailOAuthTokenResponse:
        return self._token_request(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            }
        )

    def refresh(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> GmailOAuthTokenResponse:
        return self._token_request(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )

    def revoke(self, token: str) -> None:
        form = urllib.parse.urlencode({"token": token}).encode()
        request = urllib.request.Request(  # noqa: S310 - fixed HTTPS endpoint
            GMAIL_REVOCATION_ENDPOINT,
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                response.read(MAX_GMAIL_OAUTH_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            if error.code != 400:
                raise GmailOAuthError("Google Gmail revocation failed") from None
        except urllib.error.URLError, TimeoutError:
            raise GmailOAuthError("Google Gmail revocation failed") from None

    def _token_request(self, values: dict[str, str]) -> GmailOAuthTokenResponse:
        request = urllib.request.Request(  # noqa: S310 - fixed HTTPS endpoint
            GMAIL_TOKEN_ENDPOINT,
            data=urllib.parse.urlencode(values).encode(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                raw = response.read(MAX_GMAIL_OAUTH_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError, urllib.error.URLError, TimeoutError:
            raise GmailOAuthError("Google Gmail token request failed") from None
        if len(raw) > MAX_GMAIL_OAUTH_RESPONSE_BYTES:
            raise GmailOAuthError("Google Gmail token response exceeded its limit")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError, UnicodeDecodeError:
            raise GmailOAuthError("Google Gmail token response was invalid") from None
        finally:
            raw = b""
        if not isinstance(payload, dict):
            raise GmailOAuthError("Google Gmail token response was invalid")
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        expires_in = payload.get("expires_in")
        scope = payload.get("scope", GMAIL_READONLY_SCOPE)
        if not (
            isinstance(access_token, str)
            and access_token
            and (refresh_token is None or isinstance(refresh_token, str))
            and isinstance(expires_in, int)
            and not isinstance(expires_in, bool)
            and expires_in > 0
            and isinstance(scope, str)
            and frozenset(scope.split()) == frozenset({GMAIL_READONLY_SCOPE})
        ):
            payload.clear()
            raise GmailOAuthError("Google Gmail token response omitted required fields")
        payload.clear()
        return GmailOAuthTokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            granted_scope=GMAIL_READONLY_SCOPE,
            expires_in_seconds=expires_in,
        )


class GoogleGmailProfileClient:
    """Retrieve only the current Gmail profile identity."""

    def get_email_address(self, access_token: str) -> str:
        request = urllib.request.Request(  # noqa: S310 - fixed HTTPS endpoint
            GMAIL_PROFILE_ENDPOINT,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                raw = response.read(MAX_GMAIL_OAUTH_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError, urllib.error.URLError, TimeoutError:
            raise GmailOAuthError("Work Gmail profile confirmation failed") from None
        if len(raw) > MAX_GMAIL_OAUTH_RESPONSE_BYTES:
            raise GmailOAuthError("Work Gmail profile response exceeded its limit")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError, UnicodeDecodeError:
            raise GmailOAuthError("Work Gmail profile response was invalid") from None
        finally:
            raw = b""
        if not isinstance(payload, dict):
            raise GmailOAuthError("Work Gmail profile response was invalid")
        email_address = payload.get("emailAddress")
        payload.clear()
        if not isinstance(email_address, str) or "@" not in email_address:
            raise GmailOAuthError(
                "Work Gmail profile response omitted account identity"
            )
        return email_address


@dataclass(frozen=True, slots=True)
class WorkGmailOAuthClientRegistrar:
    """Store one dedicated Work Gmail Desktop client in Keychain."""

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
        application_owner: str,
    ) -> OAuthClientMetadata:
        """Validate the exact project and persist only non-secret metadata."""

        _validate_client(project_id, client_id, client_secret, application_owner)
        now = self.clock()
        instance = ConnectorInstanceMetadata(
            id=GMAIL_WORK_INSTANCE,
            provider=GMAIL_CONNECTOR_PROVIDER,
            alias=GMAIL_WORK_ALIAS,
            domain_classification=ConnectorDomain.WORK,
            approved_resource_boundary=GMAIL_WORK_ACCOUNT,
            approved_scopes=GMAIL_READONLY_SCOPE,
            retrieval_configuration="bounded-14-calendar-days-metadata-first",
            enabled=False,
            retention_policy_reference="adr-0004-work-gmail",
            created_at=now,
            updated_at=now,
        )
        reference = KeychainSecretReference(
            GMAIL_KEYCHAIN_SERVICE,
            f"{GMAIL_WORK_INSTANCE}:client-secret",
        )
        self.keychain.store(reference, client_secret)
        metadata = OAuthClientMetadata(
            connector=GMAIL_CONNECTOR_PROVIDER,
            connector_instance_id=GMAIL_WORK_INSTANCE,
            oauth_project_id=project_id,
            oauth_client_id=client_id,
            credential_service=reference.service,
            client_secret_account=reference.account,
            configured_at=now,
            application_owner=application_owner,
        )
        try:
            self.state_store.save_connector_instance(instance)
            self.state_store.save_oauth_client(metadata)
        except BaseException:
            self.keychain.delete(reference)
            raise
        return metadata


@dataclass(frozen=True, slots=True)
class WorkGmailOAuthClientImporter:
    """Import a bounded Desktop JSON file and delete it after Keychain storage."""

    keychain: MacOSKeychain
    state_store: StateStore
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def import_and_delete(
        self,
        source: Path,
        *,
        application_owner: str,
    ) -> GmailOAuthImportResult:
        """Import only an exact-project Google Desktop client."""

        if not source.is_file():
            raise ValueError("Gmail OAuth client source must be a file")
        raw = bytearray(source.read_bytes())
        try:
            if len(raw) > MAX_GMAIL_CLIENT_FILE_BYTES:
                raise ValueError("Gmail OAuth client source exceeded its limit")
            try:
                payload = json.loads(raw.decode())
            except json.JSONDecodeError, UnicodeDecodeError:
                raise ValueError("Gmail OAuth client source was invalid") from None
            installed = payload.get("installed") if isinstance(payload, dict) else None
            if not isinstance(installed, dict):
                raise ValueError("Gmail OAuth client must be a Desktop client")
            project_id = installed.get("project_id")
            client_id = installed.get("client_id")
            client_secret = installed.get("client_secret")
            auth_uri = installed.get("auth_uri")
            token_uri = installed.get("token_uri")
            if not (
                isinstance(project_id, str)
                and isinstance(client_id, str)
                and isinstance(client_secret, str)
                and auth_uri in GMAIL_DESKTOP_CLIENT_AUTHORIZATION_ENDPOINTS
                and token_uri == GMAIL_TOKEN_ENDPOINT
            ):
                raise ValueError("Gmail OAuth client file had unexpected metadata")
            metadata = WorkGmailOAuthClientRegistrar(
                keychain=self.keychain,
                state_store=self.state_store,
                clock=self.clock,
            ).register(
                project_id=project_id,
                client_id=client_id,
                client_secret=client_secret,
                application_owner=application_owner,
            )
        finally:
            raw[:] = b"\x00" * len(raw)
        source.unlink()
        return GmailOAuthImportResult(metadata=metadata, source_deleted=True)


@dataclass(frozen=True, slots=True)
class WorkGmailInstalledAppOAuth:
    """Authorize, refresh, revoke, and disconnect only `gmail:work`."""

    keychain: MacOSKeychain
    state_store: StateStore
    token_client: GmailOAuthTokenBoundary = field(
        default_factory=GoogleGmailOAuthTokenClient,
        repr=False,
        compare=False,
    )
    profile_client: GmailProfileBoundary = field(
        default_factory=GoogleGmailProfileClient,
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
    ) -> GmailOAuthAuthorizationResult:
        """Run one state- and PKCE-protected exact-account flow."""

        _validate_account(account_reference, confirmed_account_identity)
        client = self.state_store.get_oauth_client(GMAIL_WORK_INSTANCE)
        if client is None or client.oauth_project_id != GMAIL_OAUTH_PROJECT:
            raise GmailOAuthError("Work Gmail OAuth client is not configured")
        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        callback: dict[str, str] = {}
        handler_type = _callback_handler(expected_state=state, callback=callback)
        with HTTPServer(("127.0.0.1", 0), handler_type) as server:
            port = int(server.server_address[1])
            redirect_uri = f"http://127.0.0.1:{port}/oauth2/callback"
            self.browser_opener(
                _authorization_url(
                    client_id=client.oauth_client_id,
                    redirect_uri=redirect_uri,
                    state=state,
                    code_challenge=_pkce_challenge(code_verifier),
                    account_identity=confirmed_account_identity,
                )
            )
            deadline = time.monotonic() + timeout_seconds
            server.timeout = 1
            while "code" not in callback and "error" not in callback:
                if time.monotonic() >= deadline:
                    raise GmailOAuthError("Work Gmail browser authorization timed out")
                server.handle_request()
        if callback.get("error") == "state_mismatch":
            raise GmailOAuthStateMismatch("Work Gmail OAuth state did not match")
        if "error" in callback:
            raise GmailOAuthError("Work Gmail authorization was denied")
        code = callback.get("code")
        if code is None:
            raise GmailOAuthError("Work Gmail callback omitted its code")
        client_secret = self.keychain.read(
            KeychainSecretReference(
                client.credential_service,
                client.client_secret_account,
            )
        )
        token = self.token_client.exchange_code(
            client_id=client.oauth_client_id,
            client_secret=client_secret,
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
        account_identity = self.profile_client.get_email_address(token.access_token)
        if not hmac.compare_digest(
            account_identity.casefold(),
            confirmed_account_identity.casefold(),
        ) or not hmac.compare_digest(
            account_identity.casefold(),
            GMAIL_WORK_ACCOUNT.casefold(),
        ):
            self.token_client.revoke(token.access_token)
            raise GmailOAuthError("Authorized Gmail account did not match Work Gmail")
        metadata = self._store_tokens(
            account_reference=account_reference,
            account_identity=account_identity,
            token=token,
            authorized_at=None,
            existing_refresh_token=None,
        )
        return GmailOAuthAuthorizationResult(
            metadata=metadata,
            access_token_issued=True,
            refresh_token_issued=token.refresh_token is not None,
        )

    def refresh(
        self,
        *,
        account_reference: str,
    ) -> ConnectorAuthorizationMetadata:
        """Refresh exactly one Work Gmail grant and rotate the access token."""

        client = self.state_store.get_oauth_client(GMAIL_WORK_INSTANCE)
        metadata = self.state_store.get_connector_authorization(GMAIL_WORK_INSTANCE)
        if (
            client is None
            or metadata is None
            or metadata.account_reference != account_reference
            or metadata.refresh_token_account is None
            or metadata.granted_scope != GMAIL_READONLY_SCOPE
        ):
            raise GmailOAuthError("Work Gmail refresh metadata is unavailable")
        client_secret = self.keychain.read(
            KeychainSecretReference(
                client.credential_service,
                client.client_secret_account,
            )
        )
        refresh_reference = KeychainSecretReference(
            metadata.credential_service,
            metadata.refresh_token_account,
        )
        try:
            refresh_token = self.keychain.read(refresh_reference)
        except KeychainSecretNotFound:
            raise GmailOAuthError("Work Gmail refresh token is missing") from None
        token = self.token_client.refresh(
            client_id=client.oauth_client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
        )
        return self._store_tokens(
            account_reference=metadata.account_reference,
            account_identity=metadata.account_identity,
            token=token,
            authorized_at=metadata.authorized_at,
            existing_refresh_token=refresh_token,
        )

    def disconnect(self, *, revoke: bool = True) -> None:
        """Optionally revoke and then delete the exact local Work Gmail grant."""

        metadata = self.state_store.get_connector_authorization(GMAIL_WORK_INSTANCE)
        if metadata is None:
            return
        access_reference = KeychainSecretReference(
            metadata.credential_service,
            metadata.access_token_account,
        )
        refresh_reference = (
            None
            if metadata.refresh_token_account is None
            else KeychainSecretReference(
                metadata.credential_service,
                metadata.refresh_token_account,
            )
        )
        if revoke:
            token_reference = refresh_reference or access_reference
            try:
                token = self.keychain.read(token_reference)
            except KeychainSecretNotFound:
                token = ""
            if token:
                self.token_client.revoke(token)
        self.keychain.delete(access_reference)
        if refresh_reference is not None:
            self.keychain.delete(refresh_reference)
        self.state_store.delete_connector_authorization(GMAIL_WORK_INSTANCE)

    def _store_tokens(
        self,
        *,
        account_reference: str,
        account_identity: str,
        token: GmailOAuthTokenResponse,
        authorized_at: datetime | None,
        existing_refresh_token: str | None,
    ) -> ConnectorAuthorizationMetadata:
        if token.granted_scope != GMAIL_READONLY_SCOPE:
            raise GmailOAuthError("Work Gmail granted scope was not exact")
        now = self.clock()
        access_reference = KeychainSecretReference(
            GMAIL_KEYCHAIN_SERVICE,
            f"{GMAIL_WORK_INSTANCE}:access-token:{account_reference}",
        )
        refresh_token = token.refresh_token or existing_refresh_token
        refresh_reference = (
            None
            if refresh_token is None
            else KeychainSecretReference(
                GMAIL_KEYCHAIN_SERVICE,
                f"{GMAIL_WORK_INSTANCE}:refresh-token:{account_reference}",
            )
        )
        self.keychain.store(access_reference, token.access_token)
        if refresh_reference is not None and refresh_token is not None:
            self.keychain.store(refresh_reference, refresh_token)
        metadata = ConnectorAuthorizationMetadata(
            connector=GMAIL_CONNECTOR_PROVIDER,
            connector_instance_id=GMAIL_WORK_INSTANCE,
            account_reference=account_reference,
            account_identity=account_identity,
            granted_scope=GMAIL_READONLY_SCOPE,
            credential_service=GMAIL_KEYCHAIN_SERVICE,
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
            authorized_at=authorized_at or now,
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
            "access_type": "offline",
            "client_id": client_id,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "include_granted_scopes": "false",
            "login_hint": account_identity,
            "prompt": "select_account consent",
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GMAIL_READONLY_SCOPE,
            "state": state,
        }
    )
    return f"{GMAIL_AUTHORIZATION_ENDPOINT}?{query}"


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _callback_handler(
    *,
    expected_state: str,
    callback: dict[str, str],
) -> type[BaseHTTPRequestHandler]:
    class GmailOAuthCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            state = query.get("state", [None])[0]
            valid_state = isinstance(state, str) and hmac.compare_digest(
                state,
                expected_state,
            )
            if parsed.path != "/oauth2/callback" or not valid_state:
                callback["error"] = (
                    "state_mismatch" if not valid_state else "invalid_callback"
                )
                self.send_response(400)
            elif isinstance(query.get("error", [None])[0], str):
                callback["error"] = "authorization_denied"
                self.send_response(400)
            elif isinstance(query.get("code", [None])[0], str):
                callback["code"] = query["code"][0]
                self.send_response(200)
            else:
                callback["error"] = "missing_code"
                self.send_response(400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"Work Gmail authorization received. Return to Chief of Staff."
            )

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return GmailOAuthCallbackHandler


def _validate_client(
    project_id: str,
    client_id: str,
    client_secret: str,
    application_owner: str,
) -> None:
    if (
        project_id != GMAIL_OAUTH_PROJECT
        or not client_id.endswith(".apps.googleusercontent.com")
        or any(character.isspace() for character in client_id)
        or not client_secret
        or not application_owner.strip()
    ):
        raise ValueError("Work Gmail OAuth client metadata was invalid")


def _validate_account(account_reference: str, account_identity: str) -> None:
    if (
        not account_reference
        or "@" in account_reference
        or any(character.isspace() for character in account_reference)
        or account_identity.casefold() != GMAIL_WORK_ACCOUNT.casefold()
    ):
        raise ValueError("Work Gmail account confirmation was invalid")


def _open_system_browser(url: str) -> None:
    completed = subprocess.run(  # noqa: S603 - fixed system browser executable
        ("/usr/bin/open", url),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        raise GmailOAuthError("system browser could not be opened")
