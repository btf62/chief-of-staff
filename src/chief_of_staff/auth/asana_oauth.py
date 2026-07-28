"""Asana OAuth authorization code flow with state, PKCE, and Keychain storage."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import ssl
import subprocess
import tempfile
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
from chief_of_staff.connectors.instances import ASANA_PRIMARY_INSTANCE
from chief_of_staff.domain import (
    AuthorizationStatus,
    ConnectorAuthorizationMetadata,
    ConnectorDomain,
    ConnectorInstanceMetadata,
    CredentialHealth,
    OAuthClientMetadata,
)
from chief_of_staff.persistence import StateStore

ASANA_CONNECTOR: Final = "asana"
ASANA_APPLICATION_NAME: Final = "Chief of Staff (Local) — Asana"
ASANA_DISCOVERY_SCOPES: Final = frozenset({"workspaces:read", "projects:read"})
ASANA_DISCOVERY_SCOPE_STRING: Final = "workspaces:read projects:read"
ASANA_AUTHORIZATION_ENDPOINT: Final = "https://app.asana.com/-/oauth_authorize"
ASANA_TOKEN_ENDPOINT: Final = "https://app.asana.com/-/oauth_token"  # noqa: S105
ASANA_TOKEN_INFO_ENDPOINT: Final = "https://app.asana.com/-/token_info"  # noqa: S105
ASANA_REVOCATION_ENDPOINT: Final = "https://app.asana.com/-/oauth_revoke"
ASANA_REDIRECT_URI: Final = "https://127.0.0.1:8768/oauth/callback"
ASANA_CALLBACK_PORT: Final = 8768
KEYCHAIN_SERVICE: Final = "org.chief-of-staff.oauth"
MAX_OAUTH_RESPONSE_BYTES: Final = 64 * 1024


class AsanaOAuthError(RuntimeError):
    """Raised for a bounded Asana OAuth or credential failure."""


class AsanaOAuthStateMismatch(AsanaOAuthError):
    """Raised when a callback does not match the initiating local session."""


class AsanaAccountConfirmationError(AsanaOAuthError):
    """Raised when the browser account does not match explicit confirmation."""


@dataclass(frozen=True, slots=True)
class AsanaOAuthTokenResponse:
    """Validated OAuth tokens and minimum provider-returned account identity."""

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in_seconds: int
    identity_gid: str
    identity_name: str
    identity_email: str


@dataclass(frozen=True, slots=True)
class AsanaTokenInspection:
    """Non-secret token health and exact granted scope set."""

    active: bool
    token_type: str
    scopes: frozenset[str]
    expires_in_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class AsanaAuthorizationResult:
    """Privacy-safe result of one browser account authorization."""

    metadata: ConnectorAuthorizationMetadata
    access_token_issued: bool
    refresh_token_issued: bool
    account_identity_source: str
    pkce_method: str = "S256"


class AsanaOAuthTokenClientProtocol(Protocol):
    """Injectable token, introspection, refresh, and revocation boundary."""

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> AsanaOAuthTokenResponse:
        """Exchange one state-bound authorization code."""

    def inspect(self, *, token: str) -> AsanaTokenInspection:
        """Return scope and health without exposing token content."""

    def refresh(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> AsanaOAuthTokenResponse:
        """Exchange a refresh token through the same app registration."""

    def revoke(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> None:
        """Revoke the refresh grant and associated access tokens."""


class AsanaCallbackRunnerProtocol(Protocol):
    """Receive one HTTPS callback while keeping its code out of output."""

    def run(
        self,
        *,
        authorization_url: str,
        expected_state: str,
        timeout_seconds: int,
        browser_opener: Callable[[str], None],
    ) -> dict[str, str]:
        """Open the browser and return the in-memory callback parameters."""


@dataclass(frozen=True, slots=True)
class AsanaOAuthClientRegistrar:
    """Store one private Asana app secret only in macOS Keychain."""

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
        """Persist app metadata after securing its client secret."""

        for label, value in (
            ("application name", application_name),
            ("application owner", application_owner),
            ("client ID", client_id),
        ):
            if not value.strip():
                raise ValueError(f"Asana {label} must not be empty")
        if not client_secret:
            raise ValueError("Asana client secret must not be empty")
        now = self.clock()
        self.state_store.save_connector_instance(
            ConnectorInstanceMetadata(
                id=ASANA_PRIMARY_INSTANCE,
                provider=ASANA_CONNECTOR,
                alias="Asana",
                domain_classification=ConnectorDomain.WORK,
                approved_resource_boundary=(
                    "visible workspaces and active-project discovery only"
                ),
                approved_scopes=ASANA_DISCOVERY_SCOPE_STRING,
                retrieval_configuration="workspace-and-active-project-discovery",
                enabled=False,
                retention_policy_reference="adr-0004-discovery-only",
                created_at=now,
                updated_at=now,
            )
        )
        reference = KeychainSecretReference(
            service=KEYCHAIN_SERVICE,
            account=f"{ASANA_PRIMARY_INSTANCE}:client-secret",
        )
        self.keychain.store(reference, client_secret)
        metadata = OAuthClientMetadata(
            connector=ASANA_CONNECTOR,
            connector_instance_id=ASANA_PRIMARY_INSTANCE,
            oauth_project_id=application_name.strip(),
            oauth_client_id=client_id.strip(),
            credential_service=reference.service,
            client_secret_account=reference.account,
            configured_at=now,
            application_owner=application_owner.strip(),
            oauth_grant_type="authorization_code",
        )
        try:
            self.state_store.save_oauth_client(metadata)
        except BaseException:
            self.keychain.delete(reference)
            raise
        return metadata


@dataclass(frozen=True, slots=True)
class AsanaInstalledAppOAuth:
    """Authorize one explicitly confirmed account through local HTTPS."""

    keychain: MacOSKeychain
    state_store: StateStore
    token_client: AsanaOAuthTokenClientProtocol = field(
        default_factory=lambda: AsanaOAuthTokenClient(),
        repr=False,
        compare=False,
    )
    callback_runner: AsanaCallbackRunnerProtocol = field(
        default_factory=lambda: LocalTlsOAuthCallbackRunner(),
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
    ) -> AsanaAuthorizationResult:
        """Use exact discovery scopes and persist both tokens in Keychain."""

        _validate_account_reference(account_reference)
        if not confirmed_account_identity.strip():
            raise AsanaAccountConfirmationError(
                "Asana account confirmation must not be empty"
            )
        client = self.state_store.get_oauth_client(ASANA_PRIMARY_INSTANCE)
        if client is None:
            raise AsanaOAuthError("Asana OAuth client is not configured")

        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = _pkce_challenge(code_verifier)
        callback = self.callback_runner.run(
            authorization_url=_authorization_url(
                client_id=client.oauth_client_id,
                state=state,
                code_challenge=code_challenge,
            ),
            expected_state=state,
            timeout_seconds=timeout_seconds,
            browser_opener=self.browser_opener,
        )
        returned_state = callback.pop("state", "")
        if not returned_state or not hmac.compare_digest(returned_state, state):
            raise AsanaOAuthStateMismatch("Asana OAuth state did not match")
        if callback.get("error"):
            raise AsanaOAuthError("Asana OAuth authorization was denied")
        code = callback.pop("code", "")
        if not code:
            raise AsanaOAuthError("Asana OAuth callback omitted a code")

        client_reference = KeychainSecretReference(
            service=client.credential_service,
            account=client.client_secret_account,
        )
        try:
            client_secret = self.keychain.read(client_reference)
        except KeychainSecretNotFound:
            raise AsanaOAuthError("Asana OAuth client secret is missing") from None
        try:
            token = self.token_client.exchange_code(
                client_id=client.oauth_client_id,
                client_secret=client_secret,
                code=code,
                code_verifier=code_verifier,
                redirect_uri=ASANA_REDIRECT_URI,
            )
        finally:
            code = ""
            code_verifier = ""
        inspection = self.token_client.inspect(token=token.access_token)
        if (
            not inspection.active
            or inspection.token_type.casefold() != "bearer"
            or inspection.scopes != ASANA_DISCOVERY_SCOPES
        ):
            self._revoke_rejected_grant(
                client_id=client.oauth_client_id,
                client_secret=client_secret,
                refresh_token=token.refresh_token,
            )
            raise AsanaOAuthError(
                "Asana granted scopes do not match the discovery boundary"
            )
        if (
            token.identity_email.casefold()
            != confirmed_account_identity.strip().casefold()
        ):
            self._revoke_rejected_grant(
                client_id=client.oauth_client_id,
                client_secret=client_secret,
                refresh_token=token.refresh_token,
            )
            raise AsanaAccountConfirmationError(
                "Asana API identity did not match the confirmed browser account"
            )
        client_secret = ""
        metadata = self._store_authorization(
            account_reference=account_reference,
            account_identity=token.identity_email,
            token=token,
        )
        return AsanaAuthorizationResult(
            metadata=metadata,
            access_token_issued=True,
            refresh_token_issued=True,
            account_identity_source="user-confirmed-and-api-verified",
        )

    def _revoke_rejected_grant(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> None:
        """Remove a provider grant that failed scope or identity validation."""

        try:
            self.token_client.revoke(
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
            )
        except AsanaOAuthError:
            raise AsanaOAuthError(
                "Asana rejected grant validation and revocation failed"
            ) from None

    def refresh_authorization(
        self,
        *,
        account_reference: str,
    ) -> ConnectorAuthorizationMetadata:
        """Refresh and replace one instance's access token safely."""

        metadata = self.state_store.get_connector_authorization(ASANA_PRIMARY_INSTANCE)
        client = self.state_store.get_oauth_client(ASANA_PRIMARY_INSTANCE)
        if (
            metadata is None
            or client is None
            or metadata.account_reference != account_reference
            or frozenset(metadata.granted_scope.split()) != ASANA_DISCOVERY_SCOPES
            or metadata.refresh_token_account is None
        ):
            raise AsanaOAuthError("Asana refresh metadata is unavailable")
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
            raise AsanaOAuthError("Asana refresh credential is missing") from None
        token = self.token_client.refresh(
            client_id=client.oauth_client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
        )
        inspection = self.token_client.inspect(token=token.access_token)
        if not inspection.active or inspection.scopes != ASANA_DISCOVERY_SCOPES:
            raise AsanaOAuthError("Asana refreshed grant has unexpected scopes")
        client_secret = ""
        refresh_token = ""
        return self._store_authorization(
            account_reference=metadata.account_reference,
            account_identity=metadata.account_identity,
            token=token,
            authorized_at=metadata.authorized_at,
        )

    def disconnect(self, *, revoke: bool = True) -> None:
        """Revoke one Asana grant and remove only its Keychain tokens."""

        metadata = self.state_store.get_connector_authorization(ASANA_PRIMARY_INSTANCE)
        client = self.state_store.get_oauth_client(ASANA_PRIMARY_INSTANCE)
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
            if client is None or refresh_reference is None:
                raise AsanaOAuthError("Asana revocation metadata is unavailable")
            client_reference = KeychainSecretReference(
                service=client.credential_service,
                account=client.client_secret_account,
            )
            try:
                client_secret = self.keychain.read(client_reference)
                refresh_token = self.keychain.read(refresh_reference)
            except KeychainSecretNotFound:
                raise AsanaOAuthError(
                    "Asana revocation credential is missing"
                ) from None
            self.token_client.revoke(
                client_id=client.oauth_client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
            )
            client_secret = ""
            refresh_token = ""
        self.keychain.delete(access_reference)
        if refresh_reference is not None:
            self.keychain.delete(refresh_reference)
        self.state_store.delete_connector_authorization(ASANA_PRIMARY_INSTANCE)

    def _store_authorization(
        self,
        *,
        account_reference: str,
        account_identity: str,
        token: AsanaOAuthTokenResponse,
        authorized_at: datetime | None = None,
    ) -> ConnectorAuthorizationMetadata:
        now = self.clock()
        access_reference = KeychainSecretReference(
            service=KEYCHAIN_SERVICE,
            account=f"{ASANA_PRIMARY_INSTANCE}:access-token:{account_reference}",
        )
        refresh_reference = KeychainSecretReference(
            service=KEYCHAIN_SERVICE,
            account=f"{ASANA_PRIMARY_INSTANCE}:refresh-token:{account_reference}",
        )
        self.keychain.store(access_reference, token.access_token)
        try:
            self.keychain.store(refresh_reference, token.refresh_token)
        except BaseException:
            self.keychain.delete(access_reference)
            raise
        metadata = ConnectorAuthorizationMetadata(
            connector=ASANA_CONNECTOR,
            connector_instance_id=ASANA_PRIMARY_INSTANCE,
            account_reference=account_reference,
            account_identity=account_identity,
            granted_scope=ASANA_DISCOVERY_SCOPE_STRING,
            credential_service=KEYCHAIN_SERVICE,
            access_token_account=access_reference.account,
            refresh_token_account=refresh_reference.account,
            authorization_status=AuthorizationStatus.AUTHORIZED,
            credential_health=CredentialHealth.HEALTHY,
            refresh_health=CredentialHealth.HEALTHY,
            token_expires_at=now + timedelta(seconds=token.expires_in_seconds),
            authorized_at=now if authorized_at is None else authorized_at,
            updated_at=now,
        )
        try:
            self.state_store.save_connector_authorization(metadata)
        except BaseException:
            self.keychain.delete(access_reference)
            self.keychain.delete(refresh_reference)
            raise
        return metadata


class AsanaOAuthTokenClient:
    """Minimal fixed-endpoint Asana OAuth client."""

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> AsanaOAuthTokenResponse:
        return self._token_request(
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "code": code,
                "code_verifier": code_verifier,
            }
        )

    def inspect(self, *, token: str) -> AsanaTokenInspection:
        payload = _post_form(
            ASANA_TOKEN_INFO_ENDPOINT,
            {"token": token},
        )
        active = payload.get("active")
        token_type = payload.get("token_type")
        scope = payload.get("scope")
        expires_in = payload.get("expires_in")
        if (
            not isinstance(active, bool)
            or not isinstance(token_type, str)
            or not isinstance(scope, str)
            or (
                expires_in is not None
                and (not isinstance(expires_in, int) or isinstance(expires_in, bool))
            )
        ):
            raise AsanaOAuthError("Asana token inspection response was invalid")
        return AsanaTokenInspection(
            active=active,
            token_type=token_type,
            scopes=frozenset(scope.split()),
            expires_in_seconds=expires_in,
        )

    def refresh(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> AsanaOAuthTokenResponse:
        return self._token_request(
            {
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            }
        )

    def revoke(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> None:
        _post_form(
            ASANA_REVOCATION_ENDPOINT,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "token": refresh_token,
            },
            allow_empty=True,
        )

    def _token_request(self, form: dict[str, str]) -> AsanaOAuthTokenResponse:
        payload = _post_form(ASANA_TOKEN_ENDPOINT, form)
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        expires_in = payload.get("expires_in")
        token_type = payload.get("token_type")
        data = payload.get("data")
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(refresh_token, str)
            or not refresh_token
            or not isinstance(expires_in, int)
            or isinstance(expires_in, bool)
            or expires_in <= 0
            or not isinstance(token_type, str)
            or token_type.casefold() != "bearer"
            or not isinstance(data, dict)
        ):
            raise AsanaOAuthError("Asana token response omitted required fields")
        gid = data.get("gid")
        name = data.get("name")
        email = data.get("email")
        if (
            not isinstance(gid, str)
            or not gid
            or not isinstance(name, str)
            or not name
            or not isinstance(email, str)
            or not email
        ):
            raise AsanaOAuthError("Asana token response omitted account identity")
        return AsanaOAuthTokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in_seconds=expires_in,
            identity_gid=gid,
            identity_name=name,
            identity_email=email,
        )


@dataclass(frozen=True, slots=True)
class LocalTlsOAuthCallbackRunner:
    """Serve one ephemeral self-signed HTTPS callback for local OAuth."""

    openssl_path: Path = Path("/usr/bin/openssl")

    def run(
        self,
        *,
        authorization_url: str,
        expected_state: str,
        timeout_seconds: int,
        browser_opener: Callable[[str], None],
    ) -> dict[str, str]:
        callback: dict[str, str] = {}
        handler_type = _callback_handler(callback)
        with tempfile.TemporaryDirectory(prefix="chief-of-staff-asana-oauth-") as root:
            certificate = Path(root) / "certificate.pem"
            private_key = Path(root) / "private-key.pem"
            _create_ephemeral_certificate(
                openssl_path=self.openssl_path,
                certificate=certificate,
                private_key=private_key,
            )
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certificate, private_key)
            with HTTPServer(("127.0.0.1", ASANA_CALLBACK_PORT), handler_type) as server:
                server.socket = context.wrap_socket(server.socket, server_side=True)
                browser_opener(authorization_url)
                deadline = time.monotonic() + timeout_seconds
                server.timeout = 1
                while "code" not in callback and "error" not in callback:
                    if time.monotonic() >= deadline:
                        raise AsanaOAuthError(
                            "Asana OAuth browser authorization timed out"
                        )
                    server.handle_request()
        if callback.get("state") != expected_state:
            raise AsanaOAuthStateMismatch("Asana OAuth state did not match")
        return callback


def _authorization_url(
    *,
    client_id: str,
    state: str,
    code_challenge: str,
) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": ASANA_REDIRECT_URI,
            "response_type": "code",
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
            "scope": ASANA_DISCOVERY_SCOPE_STRING,
        },
        quote_via=urllib.parse.quote,
    )
    return f"{ASANA_AUTHORIZATION_ENDPOINT}?{query}"


def _pkce_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _callback_handler(
    callback: dict[str, str],
) -> type[BaseHTTPRequestHandler]:
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/oauth/callback":
                self.send_error(404)
                return
            parameters = urllib.parse.parse_qs(parsed.query)
            for key in ("code", "state", "error"):
                values = parameters.get(key)
                if values and values[0]:
                    callback[key] = values[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Asana authorization received. Return to Chief of Staff.")

        def log_message(self, _format: str, *_arguments: object) -> None:
            return

    return CallbackHandler


def _create_ephemeral_certificate(
    *,
    openssl_path: Path,
    certificate: Path,
    private_key: Path,
) -> None:
    if openssl_path != Path("/usr/bin/openssl") or not openssl_path.is_file():
        raise AsanaOAuthError("approved OpenSSL executable is unavailable")
    completed = subprocess.run(  # noqa: S603 - fixed executable and safe args
        (
            str(openssl_path),
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        raise AsanaOAuthError("ephemeral HTTPS certificate creation failed")
    private_key.chmod(0o600)
    certificate.chmod(0o600)


def _post_form(
    endpoint: str,
    form: dict[str, str],
    *,
    allow_empty: bool = False,
) -> dict[str, object]:
    request = urllib.request.Request(  # noqa: S310 - fixed HTTPS endpoints
        endpoint,
        data=urllib.parse.urlencode(form).encode(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 - fixed HTTPS endpoints
            request,
            timeout=30,
        ) as response:
            raw = response.read(MAX_OAUTH_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError, urllib.error.URLError, TimeoutError:
        raise AsanaOAuthError("Asana OAuth provider request failed") from None
    if len(raw) > MAX_OAUTH_RESPONSE_BYTES:
        raise AsanaOAuthError("Asana OAuth provider response exceeded its limit")
    if not raw and allow_empty:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError, UnicodeDecodeError:
        raise AsanaOAuthError("Asana OAuth provider response was invalid") from None
    if not isinstance(payload, dict):
        raise AsanaOAuthError("Asana OAuth provider response was invalid")
    return payload


def _validate_account_reference(value: str) -> None:
    if (
        not value.strip()
        or "@" in value
        or any(character.isspace() for character in value)
    ):
        raise ValueError("Asana account reference must be an opaque alias")


def _open_system_browser(url: str) -> None:
    subprocess.run(  # noqa: S603 - fixed macOS opener
        ("/usr/bin/open", url),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
