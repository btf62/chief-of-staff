"""Private local commands for the bounded Todoist live trial."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from chief_of_staff.auth import (
    KeychainSecretReference,
    MacOSKeychain,
    TodoistInstalledAppOAuth,
    TodoistOAuthClientRegistrar,
)
from chief_of_staff.connectors import (
    GoogleCalendarConnector,
    GoogleCalendarHttpTransport,
    StoredGoogleCalendarAuthorizationProvider,
    StoredTodoistAuthorizationProvider,
    TodoistConnector,
    TodoistHttpTransport,
)
from chief_of_staff.live_trial import LiveTodoistTrialRunner
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
    """Run one explicit Todoist setup, inspection, or bounded trial command."""

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_parser = subparsers.add_parser("register-client-from-stdin")
    register_parser.add_argument("--application-name", required=True)
    register_parser.add_argument("--application-owner", required=True)
    register_parser.add_argument("--client-id", required=True)

    authorize_parser = subparsers.add_parser("authorize")
    authorize_parser.add_argument("--account-reference", default="primary-user")

    subparsers.add_parser("status")
    disconnect_parser = subparsers.add_parser("disconnect")
    disconnect_parser.add_argument("--without-revocation", action="store_true")
    subparsers.add_parser("trial")

    parsed = parser.parse_args(arguments)
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    LOCAL_ROOT.chmod(0o700)
    with Database.open(DATABASE_PATH) as database:
        state_store = StateStore(database)
        keychain = MacOSKeychain()
        if parsed.command == "register-client-from-stdin":
            client_secret = sys.stdin.read(4097)
            if len(client_secret) > 4096:
                raise ValueError("Todoist client secret exceeds its size limit")
            metadata = TodoistOAuthClientRegistrar(
                keychain=keychain,
                state_store=state_store,
            ).register(
                application_name=parsed.application_name,
                application_owner=parsed.application_owner,
                client_id=parsed.client_id,
                client_secret=client_secret.rstrip("\r\n"),
            )
            client_secret = ""
            _print_json(
                {
                    "application_name": metadata.oauth_project_id,
                    "application_owner": metadata.application_owner,
                    "client_id": metadata.oauth_client_id,
                    "connector": metadata.connector,
                    "secret_storage": "macOS Keychain",
                }
            )
            return 0

        oauth = TodoistInstalledAppOAuth(
            keychain=keychain,
            state_store=state_store,
        )
        if parsed.command == "authorize":
            result = oauth.authorize_interactively(
                account_reference=parsed.account_reference,
                test_refresh=True,
            )
            authorization_metadata = result.metadata
            _print_json(
                {
                    "access_token_issued": result.access_token_issued,
                    "account_identity": authorization_metadata.account_identity,
                    "account_reference": authorization_metadata.account_reference,
                    "authorization_status": (
                        authorization_metadata.authorization_status.value
                    ),
                    "credential_health": (
                        authorization_metadata.credential_health.value
                    ),
                    "granted_scope": authorization_metadata.granted_scope,
                    "refresh_health": (
                        None
                        if authorization_metadata.refresh_health is None
                        else authorization_metadata.refresh_health.value
                    ),
                    "refresh_tested": result.refresh_tested,
                    "refresh_token_issued": result.refresh_token_issued,
                    "token_expires_at": authorization_metadata.token_expires_at,
                }
            )
            return 0

        if parsed.command == "status":
            _print_status(state_store, keychain)
            return 0

        if parsed.command == "disconnect":
            oauth.disconnect(revoke=not parsed.without_revocation)
            _print_json(
                {
                    "connector": "todoist",
                    "local_grant_deleted": True,
                    "provider_revocation_requested": (not parsed.without_revocation),
                }
            )
            return 0

        if parsed.command == "trial":
            calendar = _calendar_connector(state_store, keychain)
            todoist = _todoist_connector(state_store, keychain, oauth)
            report = LiveTodoistTrialRunner(
                state_store=state_store,
                repository_root=REPOSITORY_ROOT,
                repository_paths=APPROVED_REPOSITORY_PATHS,
                calendar_connector=calendar,
                todoist_connector=todoist,
                output_directory=BRIEFING_DIRECTORY,
            ).run()
            _print_json(
                asdict(report) | {"pagination_occurred": report.pagination_occurred}
            )
            return 0
    raise RuntimeError("unsupported Todoist live command")


def _calendar_connector(
    state_store: StateStore,
    keychain: MacOSKeychain,
) -> GoogleCalendarConnector:
    authorization = state_store.get_connector_authorization("google_calendar")
    if authorization is None:
        raise RuntimeError("Google Calendar is not authorized")
    reference = KeychainSecretReference(
        service=authorization.credential_service,
        account=authorization.access_token_account,
    )
    return GoogleCalendarConnector(
        account_reference=authorization.account_reference,
        authorization_provider=StoredGoogleCalendarAuthorizationProvider(
            state_store=state_store,
            keychain=keychain,
        ),
        transport=GoogleCalendarHttpTransport(
            keychain=keychain,
            access_token_reference=reference,
        ),
    )


def _todoist_connector(
    state_store: StateStore,
    keychain: MacOSKeychain,
    oauth: TodoistInstalledAppOAuth,
) -> TodoistConnector:
    authorization = state_store.get_connector_authorization("todoist")
    if authorization is None:
        raise RuntimeError("Todoist is not authorized")
    reference = KeychainSecretReference(
        service=authorization.credential_service,
        account=authorization.access_token_account,
    )
    return TodoistConnector(
        account_reference=authorization.account_reference,
        authorization_provider=StoredTodoistAuthorizationProvider(
            state_store=state_store,
            keychain=keychain,
            refresher=oauth,
        ),
        transport=TodoistHttpTransport(
            keychain=keychain,
            access_token_reference=reference,
        ),
    )


def _print_status(state_store: StateStore, keychain: MacOSKeychain) -> None:
    client = state_store.get_oauth_client("todoist")
    authorization = state_store.get_connector_authorization("todoist")
    if client is None:
        _print_json({"connector": "todoist", "status": "not_configured"})
        return
    payload: dict[str, object] = {
        "application_name": client.oauth_project_id,
        "application_owner": client.application_owner,
        "client_id": client.oauth_client_id,
        "connector": client.connector,
        "status": "configured",
    }
    if authorization is not None:
        access_reference = KeychainSecretReference(
            service=authorization.credential_service,
            account=authorization.access_token_account,
        )
        access_health = authorization.credential_health.value
        if not keychain.exists(access_reference):
            access_health = "missing"
        elif authorization.token_expires_at <= datetime.now(UTC):
            access_health = "expired"
        refresh_health = None
        if authorization.refresh_token_account is not None:
            refresh_reference = KeychainSecretReference(
                service=authorization.credential_service,
                account=authorization.refresh_token_account,
            )
            refresh_health = (
                authorization.refresh_health.value
                if authorization.refresh_health is not None
                else "error"
            )
            if not keychain.exists(refresh_reference):
                refresh_health = "missing"
        payload.update(
            {
                "access_token_present": keychain.exists(access_reference),
                "account_identity": authorization.account_identity,
                "account_reference": authorization.account_reference,
                "authorization_status": authorization.authorization_status.value,
                "credential_health": access_health,
                "granted_scope": authorization.granted_scope,
                "last_used_at": authorization.last_used_at,
                "refresh_health": refresh_health,
                "refresh_token_present": (
                    authorization.refresh_token_account is not None
                    and refresh_health != "missing"
                ),
                "token_expires_at": authorization.token_expires_at,
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


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
