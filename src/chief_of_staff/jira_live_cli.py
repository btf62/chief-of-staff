"""Private local commands for the one bounded Jira project-discovery trial."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

from chief_of_staff.auth import (
    JIRA_CONNECTOR,
    JiraInstalledAppOAuth,
    JiraOAuthClientRegistrar,
    KeychainSecretReference,
    MacOSKeychain,
)
from chief_of_staff.connectors import (
    JiraProjectDiscoveryHttpTransport,
    JiraProjectDiscoveryService,
    JiraProjectDiscoveryTrialRunner,
    StoredJiraDiscoveryAuthorizationProvider,
)
from chief_of_staff.persistence import Database, StateStore

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCAL_ROOT = REPOSITORY_ROOT / ".local"
DATABASE_PATH = LOCAL_ROOT / "state.sqlite3"
DISCOVERY_DIRECTORY = LOCAL_ROOT / "jira"


def main(arguments: list[str] | None = None) -> int:
    """Register, inspect, or run the sole approved Jira discovery command."""

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_parser = subparsers.add_parser("register-client-from-stdin")
    register_parser.add_argument("--application-name", required=True)
    register_parser.add_argument("--application-owner", required=True)

    interactive_register_parser = subparsers.add_parser("register-client-interactive")
    interactive_register_parser.add_argument("--application-name", required=True)
    interactive_register_parser.add_argument("--application-owner", required=True)

    authorize_only_parser = subparsers.add_parser("authorize")
    authorize_parser = subparsers.add_parser("authorize-and-discover")
    for selected_parser in (authorize_only_parser, authorize_parser):
        selected_parser.add_argument(
            "--expected-account",
            default="bfiles@northridgerochester.com",
        )
        selected_parser.add_argument(
            "--account-reference",
            default="primary-user",
        )
        selected_parser.add_argument(
            "--resource-reference",
            default="approved-site",
        )

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
            metadata = JiraOAuthClientRegistrar(
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
                    "connector": metadata.connector,
                    "secret_storage": "macOS Keychain",
                }
            )
            return 0

        if parsed.command == "status":
            _print_status(state_store, keychain)
            return 0

        if parsed.command in {"authorize", "authorize-and-discover"}:
            authorization = JiraInstalledAppOAuth(
                keychain=keychain,
                state_store=state_store,
            ).authorize_interactively(
                account_reference=parsed.account_reference,
                expected_account_identity=parsed.expected_account,
                resource_reference=parsed.resource_reference,
            )
            if parsed.command == "authorize":
                _print_json(
                    {
                        "access_token_issued": authorization.access_token_issued,
                        "account_identity": authorization.metadata.account_identity,
                        "account_identity_source": (
                            authorization.account_identity_source
                        ),
                        "credential_health": (
                            authorization.metadata.credential_health.value
                        ),
                        "granted_scope": authorization.metadata.granted_scope,
                        "grant_type": authorization.resource.grant_type,
                        "refresh_token_issued": authorization.refresh_token_issued,
                        "site_url": authorization.resource.resource_url,
                        "token_expires_at": (authorization.metadata.token_expires_at),
                    }
                )
                return 0
            access_reference = KeychainSecretReference(
                service=authorization.metadata.credential_service,
                account=authorization.metadata.access_token_account,
            )
            report = JiraProjectDiscoveryTrialRunner(
                state_store=state_store,
                discovery_service=JiraProjectDiscoveryService(
                    authorization_provider=StoredJiraDiscoveryAuthorizationProvider(
                        state_store=state_store,
                        keychain=keychain,
                        refresher=JiraInstalledAppOAuth(
                            state_store=state_store,
                            keychain=keychain,
                        ),
                    ),
                    transport=JiraProjectDiscoveryHttpTransport(
                        keychain=keychain,
                        access_token_reference=access_reference,
                        approved_cloud_id=authorization.resource.resource_id,
                    ),
                    account_reference=parsed.account_reference,
                    resource_reference=parsed.resource_reference,
                ),
                output_directory=DISCOVERY_DIRECTORY,
                accessible_site_count=authorization.accessible_site_count,
                account_identity_source=authorization.account_identity_source,
            ).run()
            _print_json(
                asdict(report)
                | {
                    "access_token_issued": authorization.access_token_issued,
                    "pagination_occurred": report.pagination_occurred,
                }
            )
            return 0

    raise RuntimeError("unsupported Jira live command")


def _read_client_credentials() -> tuple[str, str]:
    raw = sys.stdin.read(8193)
    if len(raw) > 8192:
        raise ValueError("Jira client credential input exceeds its size limit")
    lines = raw.splitlines()
    raw = ""
    if len(lines) != 2 or not lines[0].strip() or not lines[1]:
        raise ValueError(
            "Jira client credential input must contain client ID and secret"
        )
    return lines[0].strip(), lines[1]


def _read_interactive_client_credentials() -> tuple[str, str]:
    client_id = input("Jira client ID: ").strip()
    client_secret = getpass.getpass(
        "Jira client secret (stored only in macOS Keychain): "
    )
    if not client_id or not client_secret:
        raise ValueError("Jira client ID and secret are required")
    return client_id, client_secret


def _print_status(state_store: StateStore, keychain: MacOSKeychain) -> None:
    client = state_store.get_oauth_client(JIRA_CONNECTOR)
    authorization = state_store.get_connector_authorization(JIRA_CONNECTOR)
    resource = state_store.get_connector_resource(JIRA_CONNECTOR)
    if client is None:
        _print_json({"connector": JIRA_CONNECTOR, "status": "not_configured"})
        return
    payload: dict[str, object] = {
        "application_name": client.oauth_project_id,
        "application_owner": client.application_owner,
        "connector": client.connector,
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
        refresh_reference = (
            None
            if authorization.refresh_token_account is None
            else KeychainSecretReference(
                service=authorization.credential_service,
                account=authorization.refresh_token_account,
            )
        )
        refresh_present = bool(
            refresh_reference is not None and keychain.exists(refresh_reference)
        )
        payload.update(
            {
                "access_token_present": keychain.exists(reference),
                "account_identity": authorization.account_identity,
                "account_reference": authorization.account_reference,
                "authorization_status": authorization.authorization_status.value,
                "credential_health": health,
                "granted_scope": authorization.granted_scope,
                "last_used_at": authorization.last_used_at,
                "refresh_health": (
                    None
                    if authorization.refresh_health is None
                    else authorization.refresh_health.value
                ),
                "refresh_token_present": refresh_present,
                "token_expires_at": authorization.token_expires_at,
            }
        )
    if resource is not None:
        payload.update(
            {
                "cloud_id": resource.resource_id,
                "grant_type": resource.grant_type,
                "resource_reference": resource.resource_reference,
                "site_url": resource.resource_url,
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
