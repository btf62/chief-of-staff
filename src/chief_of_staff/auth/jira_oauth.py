"""Atlassian resource-level OAuth with Keychain-only secret storage."""

from __future__ import annotations

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

from chief_of_staff.auth.keychain import KeychainSecretReference, MacOSKeychain
from chief_of_staff.connectors.instances import JIRA_PRIMARY_INSTANCE
from chief_of_staff.domain import (
    AuthorizationStatus,
    ConnectorAuthorizationMetadata,
    ConnectorResourceMetadata,
    CredentialHealth,
    OAuthClientMetadata,
)
from chief_of_staff.persistence import StateStore

JIRA_OAUTH_AUDIENCE: Final = "api.atlassian.com"
JIRA_PROPOSED_READ_SCOPE: Final = "read:jira-work"
JIRA_CONNECTOR: Final = "jira"
JIRA_GRANT_TYPE: Final = "resource_level"
JIRA_AUTHORIZATION_ENDPOINT: Final = "https://auth.atlassian.com/authorize"
JIRA_TOKEN_ENDPOINT: Final = "https://auth.atlassian.com/oauth/token"  # noqa: S105
JIRA_ACCESSIBLE_RESOURCES_ENDPOINT: Final = (
    "https://api.atlassian.com/oauth/token/accessible-resources"
)
JIRA_REDIRECT_URI: Final = "http://127.0.0.1:8766/oauth/callback"
KEYCHAIN_SERVICE: Final = "org.chief-of-staff.oauth"
MAX_OAUTH_RESPONSE_BYTES: Final = 64 * 1024


class JiraLiveAccessNotApproved(RuntimeError):
    """Raised when a mocked boundary attempts live token exchange."""


class JiraOAuthError(RuntimeError):
    """Raised for a bounded OAuth validation or provider failure."""


class JiraOAuthStateMismatch(JiraOAuthError):
    """Raised when an OAuth callback does not match its pending state."""


class JiraAccountConfirmationError(JiraOAuthError):
    """Raised when the browser-selected account is not explicitly confirmed."""


class JiraNoAccessibleSiteError(JiraOAuthError):
    """Raised when the resource-level grant includes no Jira site."""


class JiraAmbiguousSiteError(JiraOAuthError):
    """Raised when the grant includes more than one site."""


class JiraResourceAuthenticationError(JiraOAuthError):
    """Raised when Atlassian rejects the token during site discovery."""


class JiraResourceRateLimitError(JiraOAuthError):
    """Raised when Atlassian rate-limits site discovery."""


@dataclass(frozen=True, slots=True)
class JiraOAuthTokenResponse:
    """Validated short-lived token response with its secret hidden."""

    access_token: str = field(repr=False)
    granted_scope: str
    expires_in_seconds: int
    refresh_token_issued: bool = False


@dataclass(frozen=True, slots=True)
class JiraAccessibleResource:
    """Minimum site resource returned for the selected 3LO grant."""

    cloud_id: str
    url: str
    scopes: frozenset[str]


@dataclass(frozen=True, slots=True)
class JiraAuthorizationResult:
    """Privacy-safe result of a resource-restricted authorization."""

    metadata: ConnectorAuthorizationMetadata
    resource: ConnectorResourceMetadata
    accessible_site_count: int
    access_token_issued: bool
    refresh_token_issued: bool
    account_identity_source: str = "user-confirmed"


class JiraOAuthTokenClientProtocol(Protocol):
    """Injectable authorization-code exchange boundary."""

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
    ) -> JiraOAuthTokenResponse:
        """Exchange one code without logging secret material."""


class JiraResourceClientProtocol(Protocol):
    """Injectable site-discovery boundary."""

    def get_accessible_resources(
        self,
        *,
        access_token: str,
    ) -> tuple[JiraAccessibleResource, ...]:
        """Return only the resources authorized for this token."""


@dataclass(frozen=True, slots=True)
class JiraOAuthClientRegistrar:
    """Store one Northridge-approved Atlassian client secret in Keychain."""

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
        """Persist non-secret app metadata after securing the client secret."""

        for name, value in (
            ("application name", application_name),
            ("application owner", application_owner),
            ("client ID", client_id),
        ):
            if not value.strip():
                raise ValueError(f"Jira {name} must not be empty")
        if not client_secret:
            raise ValueError("Jira client secret must not be empty")
        reference = KeychainSecretReference(
            service=KEYCHAIN_SERVICE,
            account=f"{JIRA_CONNECTOR}:client-secret",
        )
        self.keychain.store(reference, client_secret)
        metadata = OAuthClientMetadata(
            connector=JIRA_CONNECTOR,
            oauth_project_id=application_name.strip(),
            oauth_client_id=client_id.strip(),
            credential_service=reference.service,
            client_secret_account=reference.account,
            configured_at=self.clock(),
            application_owner=application_owner.strip(),
            oauth_grant_type=JIRA_GRANT_TYPE,
            connector_instance_id=JIRA_PRIMARY_INSTANCE,
        )
        try:
            self.state_store.save_oauth_client(metadata)
        except BaseException:
            self.keychain.delete(reference)
            raise
        return metadata


@dataclass(frozen=True, slots=True)
class JiraInstalledAppOAuth:
    """Run one exact-scope resource-level flow and persist its selected site."""

    keychain: MacOSKeychain
    state_store: StateStore
    token_client: JiraOAuthTokenClientProtocol = field(
        default_factory=lambda: JiraOAuthTokenClient(),
        repr=False,
        compare=False,
    )
    resource_client: JiraResourceClientProtocol = field(
        default_factory=lambda: JiraAccessibleResourcesClient(),
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
    account_confirmer: Callable[[str], bool] = field(
        default=lambda expected: _confirm_browser_account(expected),
        repr=False,
        compare=False,
    )

    def authorize_interactively(
        self,
        *,
        account_reference: str,
        expected_account_identity: str,
        resource_reference: str = "approved-site",
        timeout_seconds: int = 300,
    ) -> JiraAuthorizationResult:
        """Authorize one user-confirmed account and exactly one selected site."""

        _validate_account_inputs(
            account_reference=account_reference,
            account_identity=expected_account_identity,
            resource_reference=resource_reference,
        )
        client = self.state_store.get_oauth_client(JIRA_CONNECTOR)
        if client is None:
            raise JiraOAuthError("Jira OAuth client is not configured")
        if client.oauth_grant_type != JIRA_GRANT_TYPE:
            raise JiraOAuthError("Jira OAuth client is not resource-level")

        state = secrets.token_urlsafe(32)
        callback: dict[str, str] = {}
        handler_type = _callback_handler(expected_state=state, callback=callback)
        with HTTPServer(("127.0.0.1", 8766), handler_type) as server:
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
                    raise JiraOAuthError("Jira OAuth browser authorization timed out")
                server.handle_request()

        if callback.get("error") == "state_mismatch":
            raise JiraOAuthStateMismatch("Jira OAuth state did not match")
        if "error" in callback:
            raise JiraOAuthError("Jira OAuth authorization was denied or invalid")
        code = callback.get("code")
        if code is None:
            raise JiraOAuthError("Jira OAuth callback omitted its code")
        if not self.account_confirmer(expected_account_identity):
            raise JiraAccountConfirmationError(
                "the browser-selected Atlassian account was not confirmed"
            )

        client_reference = KeychainSecretReference(
            service=client.credential_service,
            account=client.client_secret_account,
        )
        client_secret = self.keychain.read(client_reference)
        token = self.token_client.exchange_code(
            client_id=client.oauth_client_id,
            client_secret=client_secret,
            code=code,
            redirect_uri=JIRA_REDIRECT_URI,
        )
        client_secret = ""
        code = ""
        if token.refresh_token_issued:
            raise JiraOAuthError("Jira issued an unauthorized refresh token")
        resources = self.resource_client.get_accessible_resources(
            access_token=token.access_token
        )
        resource = _select_one_resource(resources)
        return self._store_authorization(
            account_reference=account_reference,
            account_identity=expected_account_identity,
            resource_reference=resource_reference,
            token=token,
            selected_resource=resource,
            accessible_site_count=len(resources),
        )

    def _store_authorization(
        self,
        *,
        account_reference: str,
        account_identity: str,
        resource_reference: str,
        token: JiraOAuthTokenResponse,
        selected_resource: JiraAccessibleResource,
        accessible_site_count: int,
    ) -> JiraAuthorizationResult:
        if token.granted_scope != JIRA_PROPOSED_READ_SCOPE:
            raise JiraOAuthError("Jira granted scope does not match the approved scope")
        if selected_resource.scopes != frozenset({JIRA_PROPOSED_READ_SCOPE}):
            raise JiraOAuthError("Jira site scopes do not match the approved scope")

        now = self.clock()
        access_reference = KeychainSecretReference(
            service=KEYCHAIN_SERVICE,
            account=f"{JIRA_CONNECTOR}:access-token:{account_reference}",
        )
        self.keychain.store(access_reference, token.access_token)
        authorization = ConnectorAuthorizationMetadata(
            connector=JIRA_CONNECTOR,
            account_reference=account_reference,
            account_identity=account_identity,
            granted_scope=token.granted_scope,
            credential_service=KEYCHAIN_SERVICE,
            access_token_account=access_reference.account,
            refresh_token_account=None,
            authorization_status=AuthorizationStatus.AUTHORIZED,
            credential_health=CredentialHealth.HEALTHY,
            refresh_health=None,
            token_expires_at=now + timedelta(seconds=token.expires_in_seconds),
            authorized_at=now,
            updated_at=now,
            connector_instance_id=JIRA_PRIMARY_INSTANCE,
        )
        resource = ConnectorResourceMetadata(
            connector=JIRA_CONNECTOR,
            resource_reference=resource_reference,
            resource_id=selected_resource.cloud_id,
            resource_url=selected_resource.url,
            resource_type="jira_cloud_site",
            grant_type=JIRA_GRANT_TYPE,
            selected_at=now,
            connector_instance_id=JIRA_PRIMARY_INSTANCE,
        )
        try:
            self.state_store.save_connector_authorization(authorization)
            self.state_store.save_connector_resource(resource)
        except BaseException:
            self.keychain.delete(access_reference)
            self.state_store.delete_connector_authorization(JIRA_CONNECTOR)
            raise
        return JiraAuthorizationResult(
            metadata=authorization,
            resource=resource,
            accessible_site_count=accessible_site_count,
            access_token_issued=True,
            refresh_token_issued=False,
        )


class JiraOAuthTokenClient:
    """Minimal Atlassian authorization-code token client."""

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
    ) -> JiraOAuthTokenResponse:
        request_body = json.dumps(
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            }
        ).encode()
        request = urllib.request.Request(  # noqa: S310 - fixed HTTPS endpoint
            JIRA_TOKEN_ENDPOINT,
            data=request_body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                raw_response = bytearray(response.read(MAX_OAUTH_RESPONSE_BYTES + 1))
        except urllib.error.HTTPError, urllib.error.URLError, TimeoutError:
            raise JiraOAuthError("Jira OAuth token request failed") from None
        try:
            if len(raw_response) > MAX_OAUTH_RESPONSE_BYTES:
                raise JiraOAuthError("Jira OAuth response exceeded its limit")
            payload = json.loads(raw_response)
        except json.JSONDecodeError, UnicodeDecodeError:
            raise JiraOAuthError("Jira OAuth response was invalid") from None
        finally:
            raw_response[:] = b"\x00" * len(raw_response)
        if not isinstance(payload, dict):
            raise JiraOAuthError("Jira OAuth response was invalid")
        try:
            access_token = payload.get("access_token")
            scope = payload.get("scope")
            expires_in = payload.get("expires_in")
            refresh_token = payload.get("refresh_token")
            if (
                not isinstance(access_token, str)
                or not access_token
                or scope != JIRA_PROPOSED_READ_SCOPE
                or isinstance(expires_in, bool)
                or not isinstance(expires_in, int)
                or expires_in <= 0
                or refresh_token is not None
            ):
                raise JiraOAuthError(
                    "Jira OAuth response omitted the exact approved grant"
                )
            return JiraOAuthTokenResponse(
                access_token=access_token,
                granted_scope=scope,
                expires_in_seconds=expires_in,
                refresh_token_issued=False,
            )
        finally:
            payload.clear()


class JiraAccessibleResourcesClient:
    """Retrieve and minimize the sites authorized for one token."""

    def get_accessible_resources(
        self,
        *,
        access_token: str,
    ) -> tuple[JiraAccessibleResource, ...]:
        request = urllib.request.Request(  # noqa: S310 - fixed HTTPS endpoint
            JIRA_ACCESSIBLE_RESOURCES_ENDPOINT,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                raw_response = bytearray(response.read(MAX_OAUTH_RESPONSE_BYTES + 1))
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                raise JiraResourceAuthenticationError from None
            if error.code == 429:
                raise JiraResourceRateLimitError from None
            raise JiraOAuthError("Jira accessible-site discovery failed") from None
        except urllib.error.URLError, TimeoutError:
            raise JiraOAuthError("Jira accessible-site discovery failed") from None
        try:
            if len(raw_response) > MAX_OAUTH_RESPONSE_BYTES:
                raise JiraOAuthError("Jira site response exceeded its limit")
            payload = json.loads(raw_response)
        except json.JSONDecodeError, UnicodeDecodeError:
            raise JiraOAuthError("Jira site response was invalid") from None
        finally:
            raw_response[:] = b"\x00" * len(raw_response)
        if not isinstance(payload, list):
            raise JiraOAuthError("Jira site response was invalid")
        try:
            return tuple(_resource_from_payload(item) for item in payload)
        finally:
            payload.clear()


@dataclass(frozen=True, slots=True)
class JiraOAuthPreview:
    """Inspectable non-secret plan retained for mocked contract tests."""

    audience: str
    requested_scopes: tuple[str, ...]
    state: str
    resource_restricted: bool
    live_authorization_enabled: bool = False


@dataclass(slots=True)
class MockJiraOAuthBoundary:
    """Exercise OAuth state handling without credentials or network I/O."""

    state_factory: Callable[[], str]
    _pending_state: str | None = field(default=None, init=False, repr=False)

    def prepare_preview(
        self,
        *,
        requested_scopes: tuple[str, ...] = (JIRA_PROPOSED_READ_SCOPE,),
    ) -> JiraOAuthPreview:
        """Create a non-live resource-restricted authorization preview."""

        if not requested_scopes or any(not scope.strip() for scope in requested_scopes):
            raise ValueError("at least one proposed Jira scope is required")
        state = self.state_factory()
        if not state.strip():
            raise ValueError("OAuth state must not be empty")
        self._pending_state = state
        return JiraOAuthPreview(
            audience=JIRA_OAUTH_AUDIENCE,
            requested_scopes=requested_scopes,
            state=state,
            resource_restricted=True,
        )

    def validate_mock_callback(self, *, returned_state: str) -> None:
        """Validate and consume state without accepting an authorization code."""

        if self._pending_state is None or returned_state != self._pending_state:
            raise JiraOAuthStateMismatch("mocked Jira OAuth state did not match")
        self._pending_state = None

    def exchange_authorization_code(self) -> None:
        """Retain the mocked boundary's explicit no-live-exchange behavior."""

        raise JiraLiveAccessNotApproved(
            "mocked Jira OAuth boundary cannot exchange authorization codes"
        )


def _authorization_url(*, client_id: str, state: str) -> str:
    return (
        JIRA_AUTHORIZATION_ENDPOINT
        + "?"
        + urllib.parse.urlencode(
            {
                "audience": JIRA_OAUTH_AUDIENCE,
                "client_id": client_id,
                "scope": JIRA_PROPOSED_READ_SCOPE,
                "redirect_uri": JIRA_REDIRECT_URI,
                "state": state,
                "response_type": "code",
                "prompt": "consent",
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
                state,
                expected_state,
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
                b"Authorization received. Return to Chief of Staff to confirm "
                b"the displayed account."
            )

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return CallbackHandler


def _resource_from_payload(payload: object) -> JiraAccessibleResource:
    if not isinstance(payload, dict):
        raise JiraOAuthError("Jira site response contained an invalid resource")
    cloud_id = payload.get("id")
    url = payload.get("url")
    scopes = payload.get("scopes")
    if (
        not isinstance(cloud_id, str)
        or not cloud_id.strip()
        or not isinstance(url, str)
        or not _valid_atlassian_site_url(url)
        or not isinstance(scopes, list)
        or any(not isinstance(scope, str) for scope in scopes)
    ):
        raise JiraOAuthError("Jira site response omitted required fields")
    return JiraAccessibleResource(
        cloud_id=cloud_id.strip(),
        url=url.rstrip("/"),
        scopes=frozenset(scopes),
    )


def _select_one_resource(
    resources: tuple[JiraAccessibleResource, ...],
) -> JiraAccessibleResource:
    if not resources:
        raise JiraNoAccessibleSiteError("the Jira grant includes no accessible site")
    if len(resources) != 1:
        raise JiraAmbiguousSiteError(
            "the Jira grant is not demonstrably restricted to one site"
        )
    resource = resources[0]
    if resource.scopes != frozenset({JIRA_PROPOSED_READ_SCOPE}):
        raise JiraOAuthError("the selected Jira site has unapproved scopes")
    return resource


def _valid_atlassian_site_url(value: str) -> bool:
    parsed = urllib.parse.urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.hostname.endswith(".atlassian.net")
        and not parsed.username
        and not parsed.password
        and parsed.query == ""
        and parsed.fragment == ""
    )


def _validate_account_inputs(
    *,
    account_reference: str,
    account_identity: str,
    resource_reference: str,
) -> None:
    if (
        not account_reference.strip()
        or "@" in account_reference
        or any(character.isspace() for character in account_reference)
    ):
        raise ValueError("Jira account reference must be an opaque alias")
    if "@" not in account_identity or any(
        character.isspace() for character in account_identity
    ):
        raise ValueError("Jira account identity must be an email address")
    if not resource_reference.strip() or any(
        character.isspace() for character in resource_reference
    ):
        raise ValueError("Jira resource reference must be an opaque alias")


def _confirm_browser_account(expected_account_identity: str) -> bool:
    response = input(
        "Enter the displayed Atlassian account email address (not the "
        "application name) to confirm "
        f"{expected_account_identity}: "
    )
    return hmac.compare_digest(
        response.strip().casefold(),
        expected_account_identity.casefold(),
    )


def _open_system_browser(url: str) -> None:
    completed = subprocess.run(  # noqa: S603 - fixed system opener
        ("/usr/bin/open", url),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        raise JiraOAuthError("the system browser could not be opened")
