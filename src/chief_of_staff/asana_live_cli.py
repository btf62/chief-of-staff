"""Private local commands for the one bounded Asana discovery trial."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from chief_of_staff.auth.asana_oauth import (
    ASANA_APPLICATION_NAME,
    AsanaInstalledAppOAuth,
    AsanaOAuthClientRegistrar,
)
from chief_of_staff.auth.keychain import KeychainSecretReference, MacOSKeychain
from chief_of_staff.connectors.asana_discovery import (
    AsanaDiscoveryHttpTransport,
    AsanaDiscoveryService,
    AsanaDiscoveryTrialRunner,
    StoredAsanaDiscoveryAuthorizationProvider,
)
from chief_of_staff.connectors.instances import ASANA_PRIMARY_INSTANCE
from chief_of_staff.persistence import Database, StateStore

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCAL_ROOT = REPOSITORY_ROOT / ".local"
DATABASE_PATH = LOCAL_ROOT / "state.sqlite3"
DISCOVERY_DIRECTORY = LOCAL_ROOT / "asana"


def main(arguments: list[str] | None = None) -> int:
    """Register, inspect, or run the sole approved Asana discovery command."""

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_parser = subparsers.add_parser("register-client-interactive")
    register_parser.add_argument(
        "--application-name",
        default=ASANA_APPLICATION_NAME,
    )
    register_parser.add_argument("--application-owner", required=True)

    stdin_register_parser = subparsers.add_parser("register-client-from-stdin")
    stdin_register_parser.add_argument(
        "--application-name",
        default=ASANA_APPLICATION_NAME,
    )
    stdin_register_parser.add_argument("--application-owner", required=True)

    authorize_parser = subparsers.add_parser("authorize-and-discover")
    authorize_parser.add_argument("--account-reference", default="primary-user")
    authorize_parser.add_argument("--timeout-seconds", type=int, default=300)

    subparsers.add_parser("status")

    parsed = parser.parse_args(arguments)
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    LOCAL_ROOT.chmod(0o700)
    with Database.open(DATABASE_PATH) as database:
        state_store = StateStore(database)
        keychain = MacOSKeychain()

        if parsed.command in {
            "register-client-from-stdin",
            "register-client-interactive",
        }:
            if parsed.command == "register-client-interactive":
                client_id, client_secret = _read_interactive_client_credentials()
            else:
                client_id, client_secret = _read_client_credentials()
            metadata = AsanaOAuthClientRegistrar(
                keychain=keychain,
                state_store=state_store,
            ).register(
                application_name=parsed.application_name,
                application_owner=parsed.application_owner,
                client_id=client_id,
                client_secret=client_secret,
            )
            client_id = ""
            client_secret = ""
            _print_json(
                {
                    "application_name": metadata.oauth_project_id,
                    "application_owner": metadata.application_owner,
                    "connector_instance_id": metadata.connector_instance_id,
                    "secret_storage": "macOS Keychain",
                }
            )
            return 0

        if parsed.command == "status":
            _print_status(state_store, keychain)
            return 0

        if parsed.command == "authorize-and-discover":
            confirmed_identity = getpass.getpass(
                "Confirmed Asana account email shown in the browser: "
            ).strip()
            if not confirmed_identity:
                raise ValueError("explicit Asana account confirmation is required")
            authorization = AsanaInstalledAppOAuth(
                keychain=keychain,
                state_store=state_store,
            ).authorize_interactively(
                account_reference=parsed.account_reference,
                confirmed_account_identity=confirmed_identity,
                timeout_seconds=parsed.timeout_seconds,
            )
            confirmed_identity = ""
            client = state_store.get_oauth_client(ASANA_PRIMARY_INSTANCE)
            if client is None:
                raise RuntimeError("Asana OAuth client metadata disappeared")
            if client.application_owner is None:
                raise RuntimeError("Asana OAuth application owner is missing")
            report = AsanaDiscoveryTrialRunner(
                state_store=state_store,
                discovery_service=AsanaDiscoveryService(
                    authorization_provider=(
                        StoredAsanaDiscoveryAuthorizationProvider(
                            state_store=state_store,
                            keychain=keychain,
                        )
                    ),
                    transport=AsanaDiscoveryHttpTransport(),
                ),
                output_directory=DISCOVERY_DIRECTORY,
                application_name=client.oauth_project_id,
                application_owner=client.application_owner,
                account_identity_source=authorization.account_identity_source,
            ).run()
            _print_json(
                {
                    "access_token_issued": report.access_token_issued,
                    "account_alias": "Asana",
                    "account_identity_source": report.account_identity_source,
                    "application_name": report.application_name,
                    "application_owner": report.application_owner,
                    "complete_project_catalog_persisted": (
                        report.complete_project_catalog_persisted
                    ),
                    "credential_health": report.credential_health,
                    "granted_scope": report.granted_scope,
                    "offset_persisted": report.offset_persisted,
                    "private_report_path": report.private_report_path,
                    "project_count": report.project_count,
                    "project_discovery_performed": (report.project_discovery_performed),
                    "project_page_count": report.project_page_count,
                    "project_pagination_occurred": (report.project_pagination_occurred),
                    "raw_payload_persisted": report.raw_payload_persisted,
                    "refresh_health": report.refresh_health,
                    "refresh_token_issued": report.refresh_token_issued,
                    "task_endpoint_called": report.task_endpoint_called,
                    "workspace_count": report.workspace_count,
                    "workspace_page_count": report.workspace_page_count,
                    "workspace_pagination_occurred": (
                        report.workspace_pagination_occurred
                    ),
                }
            )
            return 0

    raise RuntimeError("unsupported Asana live command")


def _read_interactive_client_credentials() -> tuple[str, str]:
    client_id = getpass.getpass("Asana client ID: ").strip()
    client_secret = getpass.getpass(
        "Asana client secret (stored only in macOS Keychain): "
    )
    if not client_id or not client_secret:
        raise ValueError("Asana client ID and secret are required")
    return client_id, client_secret


def _read_client_credentials() -> tuple[str, str]:
    raw = sys.stdin.read(8193)
    if len(raw) > 8192:
        raise ValueError("Asana client credential input exceeds its size limit")
    lines = raw.splitlines()
    raw = ""
    if len(lines) != 2 or not lines[0].strip() or not lines[1]:
        raise ValueError(
            "Asana client credential input must contain client ID and secret"
        )
    return lines[0].strip(), lines[1]


def _print_status(state_store: StateStore, keychain: MacOSKeychain) -> None:
    client = state_store.get_oauth_client(ASANA_PRIMARY_INSTANCE)
    authorization = state_store.get_connector_authorization(ASANA_PRIMARY_INSTANCE)
    if client is None:
        _print_json(
            {
                "connector_instance_id": ASANA_PRIMARY_INSTANCE,
                "status": "not_configured",
            }
        )
        return
    payload: dict[str, object] = {
        "application_name": client.oauth_project_id,
        "application_owner": client.application_owner,
        "connector_instance_id": ASANA_PRIMARY_INSTANCE,
        "status": "configured",
    }
    if authorization is not None:
        access_reference = KeychainSecretReference(
            service=authorization.credential_service,
            account=authorization.access_token_account,
        )
        refresh_reference = (
            None
            if authorization.refresh_token_account is None
            else KeychainSecretReference(
                service=authorization.credential_service,
                account=authorization.refresh_token_account,
            )
        )
        health = authorization.credential_health.value
        if not keychain.exists(access_reference):
            health = "missing"
        elif authorization.token_expires_at <= datetime.now(UTC):
            health = "expired"
        payload.update(
            {
                "access_token_present": keychain.exists(access_reference),
                "account_alias": "Asana",
                "authorization_status": authorization.authorization_status.value,
                "credential_health": health,
                "granted_scope": authorization.granted_scope,
                "refresh_health": (
                    None
                    if authorization.refresh_health is None
                    else authorization.refresh_health.value
                ),
                "refresh_token_present": (
                    refresh_reference is not None and keychain.exists(refresh_reference)
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
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
