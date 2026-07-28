"""Private local commands for the active exact-project Asana boundary."""

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
    StoredAsanaDiscoveryAuthorizationProvider,
)
from chief_of_staff.connectors.asana_project_boundary import (
    AsanaExactProjectHttpTransport,
    AsanaExactProjectTrialRunner,
    AsanaExactProjectVerificationService,
    parse_approved_asana_project_url,
)
from chief_of_staff.connectors.instances import ASANA_PRIMARY_INSTANCE
from chief_of_staff.persistence import Database, StateStore

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCAL_ROOT = REPOSITORY_ROOT / ".local"
DATABASE_PATH = LOCAL_ROOT / "state.sqlite3"
DISCOVERY_DIRECTORY = LOCAL_ROOT / "asana"


def main(arguments: list[str] | None = None) -> int:
    """Register, inspect, or run one explicitly approved Asana gate."""

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

    subparsers.add_parser("restrict-to-exact-project-interactive")

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

        if parsed.command == "restrict-to-exact-project-interactive":
            approved_url = getpass.getpass("Exact approved Asana project URL: ").strip()
            approved_reference = parse_approved_asana_project_url(approved_url)
            approved_url = ""
            stored_authorization = state_store.get_connector_authorization(
                ASANA_PRIMARY_INSTANCE
            )
            if stored_authorization is None:
                raise RuntimeError("Asana authorization metadata is unavailable")
            if stored_authorization.token_expires_at <= datetime.now(UTC):
                stored_authorization = AsanaInstalledAppOAuth(
                    keychain=keychain,
                    state_store=state_store,
                ).refresh_authorization(
                    account_reference=stored_authorization.account_reference,
                )
            client = state_store.get_oauth_client(ASANA_PRIMARY_INSTANCE)
            if client is None:
                raise RuntimeError("Asana OAuth client metadata is unavailable")
            if client.application_owner is None:
                raise RuntimeError("Asana OAuth application owner is missing")
            exact_report = AsanaExactProjectTrialRunner(
                state_store=state_store,
                verification_service=AsanaExactProjectVerificationService(
                    authorization_provider=StoredAsanaDiscoveryAuthorizationProvider(
                        state_store=state_store,
                        keychain=keychain,
                    ),
                    transport=AsanaExactProjectHttpTransport(),
                    approved_reference=approved_reference,
                ),
                output_directory=DISCOVERY_DIRECTORY,
                application_name=client.oauth_project_id,
                application_owner=client.application_owner,
            ).run()
            _print_json(
                {
                    "account_alias": "Asana",
                    "active_resource_type": exact_report.active_resource_type,
                    "application_name": exact_report.application_name,
                    "application_owner": exact_report.application_owner,
                    "credential_health": exact_report.credential_health,
                    "granted_scope": exact_report.granted_scope,
                    "private_report_path": exact_report.private_report_path,
                    "project_endpoint_calls": exact_report.project_endpoint_calls,
                    "project_list_endpoint_called": (
                        exact_report.project_list_endpoint_called
                    ),
                    "project_verified": exact_report.project_verified,
                    "raw_payload_persisted": exact_report.raw_payload_persisted,
                    "refresh_health": exact_report.refresh_health,
                    "task_endpoint_called": exact_report.task_endpoint_called,
                    "workspace_list_endpoint_called": (
                        exact_report.workspace_list_endpoint_called
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
