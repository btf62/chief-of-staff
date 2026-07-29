"""Synthetic security tests for Work Gmail OAuth and fixed HTTP transport."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chief_of_staff.auth.gmail_oauth import (
    GMAIL_AUTHORIZATION_ENDPOINT,
    GMAIL_DESKTOP_CLIENT_AUTHORIZATION_ENDPOINTS,
    GMAIL_KEYCHAIN_SERVICE,
    GMAIL_OAUTH_PROJECT,
    GMAIL_TOKEN_ENDPOINT,
    GmailOAuthStateMismatch,
    GmailOAuthTokenResponse,
    WorkGmailInstalledAppOAuth,
    WorkGmailOAuthClientImporter,
    WorkGmailOAuthClientRegistrar,
)
from chief_of_staff.auth.keychain import (
    KeychainSecretReference,
    MacOSKeychain,
    SecurityCommandResult,
)
from chief_of_staff.connectors import (
    GMAIL_READONLY_SCOPE,
    GMAIL_WORK_ACCOUNT,
    GMAIL_WORK_INSTANCE,
    GmailAuthorization,
    GmailMessageListRequest,
    WorkGmailHttpTransport,
)
from chief_of_staff.persistence import Database, StateStore

NOW = datetime(2026, 7, 28, 13, 0, tzinfo=UTC)
CLIENT_ID = "synthetic.apps.googleusercontent.com"
ACCOUNT_REFERENCE = "primary-user"


@dataclass(slots=True)
class _SecurityRunner:
    secrets: dict[tuple[str, str], str] = field(default_factory=dict)

    def __call__(
        self,
        arguments: tuple[str, ...],
        *,
        input_text: str | None,
        capture_output: bool,
    ) -> SecurityCommandResult:
        del capture_output
        account = arguments[arguments.index("-a") + 1]
        service = arguments[arguments.index("-s") + 1]
        key = service, account
        if arguments[0] == "add-generic-password":
            assert input_text is not None
            self.secrets[key] = input_text.rstrip("\n")
            return SecurityCommandResult(0)
        if arguments[0] == "find-generic-password":
            if key not in self.secrets:
                return SecurityCommandResult(44)
            return SecurityCommandResult(0, stdout=f"{self.secrets[key]}\n")
        if arguments[0] == "delete-generic-password":
            existed = self.secrets.pop(key, None) is not None
            return SecurityCommandResult(0 if existed else 44)
        raise AssertionError("unexpected Keychain command")


def _keychain() -> tuple[MacOSKeychain, _SecurityRunner]:
    runner = _SecurityRunner()
    return MacOSKeychain(command_runner=runner), runner


@dataclass(slots=True)
class _TokenClient:
    response: GmailOAuthTokenResponse
    verifier: str | None = None
    revoked: list[str] = field(default_factory=list)

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> GmailOAuthTokenResponse:
        assert client_id == CLIENT_ID
        assert client_secret == "synthetic-client-secret"
        assert code == "synthetic-code"
        assert redirect_uri.startswith("http://127.0.0.1:")
        self.verifier = code_verifier
        return self.response

    def refresh(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> GmailOAuthTokenResponse:
        assert client_id == CLIENT_ID
        assert client_secret == "synthetic-client-secret"
        assert refresh_token == "synthetic-refresh-token"
        return self.response

    def revoke(self, token: str) -> None:
        self.revoked.append(token)


@dataclass(frozen=True, slots=True)
class _ProfileClient:
    account: str = GMAIL_WORK_ACCOUNT

    def get_email_address(self, access_token: str) -> str:
        assert access_token == "synthetic-access-token"
        return self.account


@dataclass(slots=True)
class _BrowserCallback:
    wrong_state: bool = False
    url: str | None = None
    thread: threading.Thread | None = None

    def __call__(self, url: str) -> None:
        self.url = url
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        redirect_uri = query["redirect_uri"][0]
        state = "wrong-state" if self.wrong_state else query["state"][0]
        callback = (
            f"{redirect_uri}?"
            f"{urllib.parse.urlencode({'code': 'synthetic-code', 'state': state})}"
        )

        def visit() -> None:
            try:
                with urllib.request.urlopen(  # noqa: S310 - loopback test callback
                    callback,
                    timeout=5,
                ) as response:
                    response.read()
            except urllib.error.HTTPError:
                if not self.wrong_state:
                    raise

        self.thread = threading.Thread(target=visit, daemon=True)
        self.thread.start()


def _register(store: StateStore, keychain: MacOSKeychain) -> None:
    WorkGmailOAuthClientRegistrar(
        keychain=keychain,
        state_store=store,
        clock=lambda: NOW,
    ).register(
        project_id=GMAIL_OAUTH_PROJECT,
        client_id=CLIENT_ID,
        client_secret="synthetic-client-secret",
        application_owner="Northridge",
    )


def test_desktop_client_import_deletes_file_and_keeps_secret_out_of_sqlite(
    tmp_path: Path,
) -> None:
    source = tmp_path / "client.json"
    source.write_text(
        json.dumps(
            {
                "installed": {
                    "project_id": GMAIL_OAUTH_PROJECT,
                    "client_id": CLIENT_ID,
                    "client_secret": "synthetic-client-secret",
                    "auth_uri": GMAIL_AUTHORIZATION_ENDPOINT,
                    "token_uri": GMAIL_TOKEN_ENDPOINT,
                }
            }
        ),
        encoding="utf-8",
    )
    keychain, runner = _keychain()
    database_path = tmp_path / "state.sqlite3"

    with Database.open(database_path) as database:
        result = WorkGmailOAuthClientImporter(
            keychain=keychain,
            state_store=StateStore(database),
            clock=lambda: NOW,
        ).import_and_delete(source, application_owner="Northridge")

        assert result.source_deleted
        assert not source.exists()
        assert result.metadata.connector_instance_id == GMAIL_WORK_INSTANCE

    assert "synthetic-client-secret" in runner.secrets.values()
    assert b"synthetic-client-secret" not in database_path.read_bytes()


def test_desktop_client_import_accepts_google_download_authorization_endpoint(
    tmp_path: Path,
) -> None:
    source = tmp_path / "client.json"
    downloaded_endpoint = "https://accounts.google.com/o/oauth2/auth"
    assert downloaded_endpoint in GMAIL_DESKTOP_CLIENT_AUTHORIZATION_ENDPOINTS
    source.write_text(
        json.dumps(
            {
                "installed": {
                    "project_id": GMAIL_OAUTH_PROJECT,
                    "client_id": CLIENT_ID,
                    "client_secret": "synthetic-client-secret",
                    "auth_uri": downloaded_endpoint,
                    "token_uri": GMAIL_TOKEN_ENDPOINT,
                }
            }
        ),
        encoding="utf-8",
    )
    keychain, _ = _keychain()

    with Database.open(tmp_path / "state.sqlite3") as database:
        result = WorkGmailOAuthClientImporter(
            keychain=keychain,
            state_store=StateStore(database),
            clock=lambda: NOW,
        ).import_and_delete(source, application_owner="Northridge")

    assert result.source_deleted
    assert not source.exists()


def test_desktop_client_import_rejects_unapproved_authorization_endpoint(
    tmp_path: Path,
) -> None:
    source = tmp_path / "client.json"
    source.write_text(
        json.dumps(
            {
                "installed": {
                    "project_id": GMAIL_OAUTH_PROJECT,
                    "client_id": CLIENT_ID,
                    "client_secret": "synthetic-client-secret",
                    "auth_uri": "https://example.test/oauth",
                    "token_uri": GMAIL_TOKEN_ENDPOINT,
                }
            }
        ),
        encoding="utf-8",
    )
    keychain, _ = _keychain()

    with (
        Database.open(tmp_path / "state.sqlite3") as database,
        pytest.raises(ValueError, match="unexpected metadata"),
    ):
        WorkGmailOAuthClientImporter(
            keychain=keychain,
            state_store=StateStore(database),
            clock=lambda: NOW,
        ).import_and_delete(source, application_owner="Northridge")


def test_oauth_uses_exact_scope_state_pkce_account_and_separate_keychain_entries(
    tmp_path: Path,
) -> None:
    keychain, runner = _keychain()
    browser = _BrowserCallback()
    token_client = _TokenClient(
        GmailOAuthTokenResponse(
            access_token="synthetic-access-token",
            refresh_token="synthetic-refresh-token",
        )
    )
    with Database.open(tmp_path / "oauth.sqlite3") as database:
        store = StateStore(database)
        _register(store, keychain)
        result = WorkGmailInstalledAppOAuth(
            keychain=keychain,
            state_store=store,
            token_client=token_client,
            profile_client=_ProfileClient(),
            browser_opener=browser,
            clock=lambda: NOW,
        ).authorize_interactively(
            account_reference=ACCOUNT_REFERENCE,
            confirmed_account_identity=GMAIL_WORK_ACCOUNT,
        )
        assert browser.thread is not None
        browser.thread.join(timeout=5)

        assert result.metadata.granted_scope == GMAIL_READONLY_SCOPE
        assert result.metadata.connector_instance_id == GMAIL_WORK_INSTANCE
        assert token_client.verifier
        assert browser.url is not None
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(browser.url).query)
        assert query["scope"] == [GMAIL_READONLY_SCOPE]
        assert query["code_challenge_method"] == ["S256"]
        assert query["state"][0]
        assert query["login_hint"] == [GMAIL_WORK_ACCOUNT]
        assert all(
            account.startswith(f"{GMAIL_WORK_INSTANCE}:")
            for service, account in runner.secrets
            if service == GMAIL_KEYCHAIN_SERVICE
        )
        database_bytes = (tmp_path / "oauth.sqlite3").read_bytes()
        assert b"synthetic-access-token" not in database_bytes
        assert b"synthetic-refresh-token" not in database_bytes
        assert store.get_connector_instance("gmail:personal") is None


def test_oauth_rejects_state_mismatch(tmp_path: Path) -> None:
    keychain, _runner = _keychain()
    database = Database.open(tmp_path / "state-mismatch.sqlite3")
    try:
        store = StateStore(database)
        _register(store, keychain)
        browser = _BrowserCallback(wrong_state=True)
        oauth = WorkGmailInstalledAppOAuth(
            keychain=keychain,
            state_store=store,
            token_client=_TokenClient(
                GmailOAuthTokenResponse(access_token="synthetic-access-token")
            ),
            profile_client=_ProfileClient(),
            browser_opener=browser,
            clock=lambda: NOW,
        )

        with pytest.raises(GmailOAuthStateMismatch):
            oauth.authorize_interactively(
                account_reference=ACCOUNT_REFERENCE,
                confirmed_account_identity=GMAIL_WORK_ACCOUNT,
            )
        assert browser.thread is not None
        browser.thread.join(timeout=5)
    finally:
        database.close()


@dataclass(slots=True)
class _Response:
    payload: bytes

    def read(self, amount: int = -1) -> bytes:
        return self.payload[:amount]

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None


@dataclass(slots=True)
class _Opener:
    urls: list[str] = field(default_factory=list)

    def __call__(
        self,
        request: urllib.request.Request,
        *,
        timeout: int,
    ) -> _Response:
        assert timeout == 30
        assert request.method == "GET"
        self.urls.append(request.full_url)
        if request.full_url.endswith("/profile"):
            payload: object = {"emailAddress": GMAIL_WORK_ACCOUNT}
        elif (
            "?format=metadata" in request.full_url or "?format=full" in request.full_url
        ):
            payload = _message_payload()
        else:
            payload = {"messages": [{"id": "message-1", "threadId": "thread-1"}]}
        return _Response(json.dumps(payload).encode())


def _message_payload() -> dict[str, object]:
    return {
        "id": "message-1",
        "threadId": "thread-1",
        "internalDate": "1785258000000",
        "labelIds": ["INBOX"],
        "sizeEstimate": 100,
        "payload": {
            "mimeType": "text/plain",
            "filename": "",
            "headers": [
                {"name": "From", "value": "person@example.invalid"},
                {"name": "To", "value": GMAIL_WORK_ACCOUNT},
            ],
            "body": {"data": "UGxlYXNlIGNvbmZpcm0u"},
        },
    }


def test_live_transport_exposes_only_fixed_read_methods_and_never_raw_or_attachment() -> (
    None
):
    keychain, _runner = _keychain()
    reference = KeychainSecretReference(
        GMAIL_KEYCHAIN_SERVICE,
        f"{GMAIL_WORK_INSTANCE}:access-token:{ACCOUNT_REFERENCE}",
    )
    keychain.store(reference, "synthetic-access-token")
    opener = _Opener()
    transport = WorkGmailHttpTransport(
        keychain=keychain,
        access_token_reference=reference,
        url_opener=opener,
    )
    authorization = GmailAuthorization(
        account_reference=ACCOUNT_REFERENCE,
        granted_scopes=frozenset({GMAIL_READONLY_SCOPE}),
        credential_reference=reference.identifier,
    )

    transport.get_profile(authorization)
    page = transport.list_messages(
        authorization,
        GmailMessageListRequest(query="after:1 before:2", page_size=100),
    )
    transport.get_message_metadata(authorization, page.messages[0].id)
    transport.get_message_full(authorization, page.messages[0].id)

    assert all(
        url.startswith("https://gmail.googleapis.com/gmail/v1/users/me")
        for url in opener.urls
    )
    assert not any("format=raw" in url or "/attachments/" in url for url in opener.urls)
    forbidden = {
        "send",
        "draft",
        "reply",
        "forward",
        "modify",
        "archive",
        "trash",
        "delete",
        "insert",
        "import_message",
        "watch",
    }
    assert not forbidden.intersection(dir(transport))
