"""Private local commands for the bounded Google Calendar live trial."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from chief_of_staff.auth import (
    GoogleInstalledAppOAuth,
    GoogleOAuthClientImporter,
    GoogleOAuthClientRegistrar,
    KeychainSecretReference,
    MacOSKeychain,
)
from chief_of_staff.connectors import (
    GoogleCalendarConnector,
    GoogleCalendarHttpTransport,
    StoredGoogleCalendarAuthorizationProvider,
)
from chief_of_staff.live_trial import LiveCalendarTrialRunner
from chief_of_staff.persistence import Database, StateStore

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCAL_ROOT = REPOSITORY_ROOT / ".local"
DATABASE_PATH = LOCAL_ROOT / "state.sqlite3"
BRIEFING_DIRECTORY = LOCAL_ROOT / "briefings"
APPROVED_REPOSITORY_PATHS = (
    Path("docs/product/features/daily-briefing-v1.md"),
    Path("docs/roadmap.md"),
)


def main(arguments: list[str] | None = None) -> int:
    """Run one explicit live-trial setup or retrieval command."""

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import-client")
    import_parser.add_argument("source", type=Path)

    register_parser = subparsers.add_parser("register-client-from-stdin")
    register_parser.add_argument("--project-id", required=True)
    register_parser.add_argument("--client-id", required=True)

    authorize_parser = subparsers.add_parser("authorize")
    authorize_parser.add_argument("--account-reference", default="primary-user")
    authorize_parser.add_argument("--account-identity", required=True)
    authorize_parser.add_argument("--refreshable", action="store_true")

    subparsers.add_parser("status")
    subparsers.add_parser("trial")

    parsed = parser.parse_args(arguments)
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    LOCAL_ROOT.chmod(0o700)
    with Database.open(DATABASE_PATH) as database:
        state_store = StateStore(database)
        keychain = MacOSKeychain()
        if parsed.command == "import-client":
            result = GoogleOAuthClientImporter(
                keychain=keychain,
                state_store=state_store,
            ).import_and_delete(parsed.source)
            _print_json(
                {
                    "client_id": result.metadata.oauth_client_id,
                    "connector": result.metadata.connector,
                    "oauth_project_id": result.metadata.oauth_project_id,
                    "source_deleted": result.source_deleted,
                }
            )
            return 0

        if parsed.command == "register-client-from-stdin":
            client_secret = sys.stdin.read(4097)
            if len(client_secret) > 4096:
                raise ValueError("OAuth client secret exceeds its size limit")
            client_metadata = GoogleOAuthClientRegistrar(
                keychain=keychain,
                state_store=state_store,
            ).register(
                project_id=parsed.project_id,
                client_id=parsed.client_id,
                client_secret=client_secret.rstrip("\r\n"),
            )
            _print_json(
                {
                    "client_id": client_metadata.oauth_client_id,
                    "connector": client_metadata.connector,
                    "oauth_project_id": client_metadata.oauth_project_id,
                    "secret_storage": "macOS Keychain",
                }
            )
            return 0

        if parsed.command == "authorize":
            authorization_metadata = GoogleInstalledAppOAuth(
                keychain=keychain,
                state_store=state_store,
            ).authorize_interactively(
                account_reference=parsed.account_reference,
                confirmed_account_identity=parsed.account_identity,
                request_refresh=parsed.refreshable,
            )
            client = state_store.get_oauth_client(authorization_metadata.connector)
            if client is None:
                raise RuntimeError("OAuth client metadata disappeared")
            _print_json(
                {
                    "account_identity": authorization_metadata.account_identity,
                    "account_reference": authorization_metadata.account_reference,
                    "authorization_status": (
                        authorization_metadata.authorization_status.value
                    ),
                    "credential_health": authorization_metadata.credential_health.value,
                    "granted_scope": authorization_metadata.granted_scope,
                    "oauth_project_id": client.oauth_project_id,
                    "refresh_credential": (
                        "healthy"
                        if authorization_metadata.refresh_token_account is not None
                        and authorization_metadata.refresh_health is not None
                        else "not configured"
                    ),
                    "token_expires_at": authorization_metadata.token_expires_at,
                }
            )
            return 0

        if parsed.command == "status":
            _print_status(state_store, keychain)
            return 0

        if parsed.command == "trial":
            authorization = state_store.get_connector_authorization("google_calendar")
            if authorization is None:
                raise RuntimeError("Google Calendar is not authorized")
            access_token_reference = KeychainSecretReference(
                service=authorization.credential_service,
                account=authorization.access_token_account,
            )
            calendar = GoogleCalendarConnector(
                account_reference=authorization.account_reference,
                authorization_provider=StoredGoogleCalendarAuthorizationProvider(
                    state_store=state_store,
                    keychain=keychain,
                ),
                transport=GoogleCalendarHttpTransport(
                    keychain=keychain,
                    access_token_reference=access_token_reference,
                ),
            )
            report = LiveCalendarTrialRunner(
                state_store=state_store,
                repository_root=REPOSITORY_ROOT,
                repository_paths=APPROVED_REPOSITORY_PATHS,
                calendar_connector=calendar,
                output_directory=BRIEFING_DIRECTORY,
            ).run()
            _print_json(
                asdict(report) | {"pagination_occurred": report.pagination_occurred}
            )
            return 0

    raise RuntimeError("unsupported live command")


def _print_status(state_store: StateStore, keychain: MacOSKeychain) -> None:
    client = state_store.get_oauth_client("google_calendar")
    authorization = state_store.get_connector_authorization("google_calendar")
    if client is None:
        _print_json({"connector": "google_calendar", "status": "not_configured"})
        return
    payload: dict[str, object] = {
        "client_id": client.oauth_client_id,
        "connector": client.connector,
        "oauth_project_id": client.oauth_project_id,
        "status": "configured",
    }
    if authorization is not None:
        reference = KeychainSecretReference(
            service=authorization.credential_service,
            account=authorization.access_token_account,
        )
        health = authorization.credential_health.value
        if not keychain.exists(reference):
            health = "missing"
        elif authorization.token_expires_at <= datetime.now(UTC):
            health = "expired"
        payload.update(
            {
                "account_identity": authorization.account_identity,
                "account_reference": authorization.account_reference,
                "authorization_status": authorization.authorization_status.value,
                "credential_health": health,
                "granted_scope": authorization.granted_scope,
                "last_used_at": authorization.last_used_at,
                "token_expires_at": authorization.token_expires_at,
                "refresh_credential": _refresh_health(
                    authorization,
                    keychain,
                ),
            }
        )
    _print_json(payload)


def _print_json(payload: dict[str, object]) -> None:
    print(
        json.dumps(
            payload,
            default=_json_default,
            indent=2,
            sort_keys=True,
        )
    )


def _refresh_health(
    authorization: object,
    keychain: MacOSKeychain,
) -> str:
    from chief_of_staff.domain import ConnectorAuthorizationMetadata

    if not isinstance(authorization, ConnectorAuthorizationMetadata):
        return "not configured"
    if authorization.refresh_token_account is None:
        return "not configured"
    reference = KeychainSecretReference(
        service=authorization.credential_service,
        account=authorization.refresh_token_account,
    )
    if not keychain.exists(reference):
        return "missing"
    if authorization.refresh_health is None:
        return "unknown"
    return authorization.refresh_health.value


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
