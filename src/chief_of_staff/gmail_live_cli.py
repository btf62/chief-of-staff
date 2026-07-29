"""Private local commands for exact-scope Work Gmail setup and MVP trial."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

from chief_of_staff.auth import (
    KeychainSecretReference,
    MacOSKeychain,
    WorkGmailInstalledAppOAuth,
    WorkGmailOAuthClientImporter,
)
from chief_of_staff.connectors import (
    GMAIL_WORK_ACCOUNT,
    GMAIL_WORK_INSTANCE,
    GmailConnector,
    StoredWorkGmailAuthorizationProvider,
    WorkGmailHttpTransport,
)
from chief_of_staff.gmail_mvp_trial import GmailMvpTrialFailure, GmailMvpTrialRunner
from chief_of_staff.jira_issue_live_cli import (
    _calendar_connector,
    _jira_connector,
    _todoist_connector,
)
from chief_of_staff.persistence import Database, StateStore

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCAL_ROOT = REPOSITORY_ROOT / ".local"
DATABASE_PATH = LOCAL_ROOT / "state.sqlite3"
BRIEFING_DIRECTORY = LOCAL_ROOT / "briefings"
REVIEW_DIRECTORY = LOCAL_ROOT / "gmail" / "reviews"
APPROVED_REPOSITORY_PATHS = (
    Path("docs/product/features/daily-briefing-v1.md"),
    Path("docs/roadmap.md"),
)


def main(arguments: list[str] | None = None) -> int:
    """Run one explicit Work Gmail setup, inspection, or bounded trial command."""

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import-client")
    import_parser.add_argument("source", type=Path)
    import_parser.add_argument("--application-owner", required=True)

    authorize_parser = subparsers.add_parser("authorize")
    authorize_parser.add_argument("--account-reference", default="primary-user")
    authorize_parser.add_argument(
        "--account-identity",
        default=GMAIL_WORK_ACCOUNT,
    )

    subparsers.add_parser("status")
    disconnect_parser = subparsers.add_parser("disconnect")
    disconnect_parser.add_argument("--without-revocation", action="store_true")
    trial_parser = subparsers.add_parser("trial")
    trial_parser.add_argument("--briefing-date", type=date.fromisoformat)

    parsed = parser.parse_args(arguments)
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    LOCAL_ROOT.chmod(0o700)
    with Database.open(DATABASE_PATH) as database:
        state_store = StateStore(database)
        keychain = MacOSKeychain()
        if parsed.command == "import-client":
            import_result = WorkGmailOAuthClientImporter(
                keychain=keychain,
                state_store=state_store,
            ).import_and_delete(
                parsed.source,
                application_owner=parsed.application_owner,
            )
            _print_json(
                {
                    "connector_instance": (
                        import_result.metadata.connector_instance_id
                    ),
                    "oauth_project_id": import_result.metadata.oauth_project_id,
                    "secret_storage": "macOS Keychain",
                    "source_deleted": import_result.source_deleted,
                }
            )
            return 0

        oauth = WorkGmailInstalledAppOAuth(
            keychain=keychain,
            state_store=state_store,
        )
        if parsed.command == "authorize":
            authorization_result = oauth.authorize_interactively(
                account_reference=parsed.account_reference,
                confirmed_account_identity=parsed.account_identity,
            )
            _print_json(
                {
                    "account_confirmed": True,
                    "authorization_status": (
                        authorization_result.metadata.authorization_status.value
                    ),
                    "connector_instance": GMAIL_WORK_INSTANCE,
                    "credential_health": (
                        authorization_result.metadata.credential_health.value
                    ),
                    "granted_scope": authorization_result.metadata.granted_scope,
                    "refresh_health": (
                        None
                        if authorization_result.metadata.refresh_health is None
                        else authorization_result.metadata.refresh_health.value
                    ),
                    "refresh_token_issued": (authorization_result.refresh_token_issued),
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
                    "connector_instance": GMAIL_WORK_INSTANCE,
                    "local_grant_deleted": True,
                    "provider_revocation_requested": (not parsed.without_revocation),
                }
            )
            return 0

        if parsed.command == "trial":
            gmail = _gmail_connector(state_store, keychain, oauth)
            try:
                report = GmailMvpTrialRunner(
                    state_store=state_store,
                    repository_root=REPOSITORY_ROOT,
                    repository_paths=APPROVED_REPOSITORY_PATHS,
                    calendar_connector=_calendar_connector(state_store, keychain),
                    todoist_connector=_todoist_connector(state_store, keychain),
                    jira_connector=_jira_connector(state_store, keychain),
                    gmail_connector=gmail,
                    briefing_directory=BRIEFING_DIRECTORY,
                    review_directory=REVIEW_DIRECTORY,
                    briefing_date_override=parsed.briefing_date,
                ).run()
            except GmailMvpTrialFailure as error:
                _print_json(asdict(error.report))
                return 2
            _print_json(asdict(report))
            return 0
    raise RuntimeError("unsupported Work Gmail command")


def _gmail_connector(
    state_store: StateStore,
    keychain: MacOSKeychain,
    oauth: WorkGmailInstalledAppOAuth,
) -> GmailConnector:
    authorization = state_store.get_connector_authorization(GMAIL_WORK_INSTANCE)
    if authorization is None:
        raise RuntimeError("Work Gmail is not authorized")
    reference = KeychainSecretReference(
        service=authorization.credential_service,
        account=authorization.access_token_account,
    )

    def recurrence(fingerprint: str) -> tuple[str, str | None]:
        decision = state_store.recurrence_decision(fingerprint)
        return decision.action.value, decision.replacement_text

    return GmailConnector(
        account_reference=authorization.account_reference,
        authorization_provider=StoredWorkGmailAuthorizationProvider(
            state_store=state_store,
            keychain=keychain,
            refresher=oauth,
        ),
        transport=WorkGmailHttpTransport(
            keychain=keychain,
            access_token_reference=reference,
        ),
        recurrence_resolver=recurrence,
    )


def _print_status(state_store: StateStore, keychain: MacOSKeychain) -> None:
    client = state_store.get_oauth_client(GMAIL_WORK_INSTANCE)
    authorization = state_store.get_connector_authorization(GMAIL_WORK_INSTANCE)
    if client is None:
        _print_json(
            {"connector_instance": GMAIL_WORK_INSTANCE, "status": "not_configured"}
        )
        return
    payload: dict[str, object] = {
        "connector_instance": GMAIL_WORK_INSTANCE,
        "oauth_project_id": client.oauth_project_id,
        "application_owner": client.application_owner,
        "status": "configured",
    }
    if authorization is not None:
        access_reference = KeychainSecretReference(
            authorization.credential_service,
            authorization.access_token_account,
        )
        access_health = authorization.credential_health.value
        if not keychain.exists(access_reference):
            access_health = "missing"
        elif authorization.token_expires_at <= datetime.now(UTC):
            access_health = "expired"
        refresh_health = None
        refresh_present = False
        if authorization.refresh_token_account is not None:
            refresh_reference = KeychainSecretReference(
                authorization.credential_service,
                authorization.refresh_token_account,
            )
            refresh_present = keychain.exists(refresh_reference)
            refresh_health = (
                authorization.refresh_health.value
                if authorization.refresh_health is not None
                else "error"
            )
            if not refresh_present:
                refresh_health = "missing"
        payload.update(
            {
                "account_confirmed": (
                    authorization.account_identity.casefold()
                    == GMAIL_WORK_ACCOUNT.casefold()
                ),
                "authorization_status": authorization.authorization_status.value,
                "credential_health": access_health,
                "granted_scope": authorization.granted_scope,
                "refresh_health": refresh_health,
                "refresh_token_present": refresh_present,
                "token_expires_at": authorization.token_expires_at,
            }
        )
    _print_json(payload)


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, default=_json_default, indent=2, sort_keys=True))


def _json_default(value: object) -> str:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
