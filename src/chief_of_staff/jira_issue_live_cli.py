"""Private local command for the one approved live Jira issue trial."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from chief_of_staff.auth import (
    KeychainSecretReference,
    MacOSKeychain,
    TodoistInstalledAppOAuth,
)
from chief_of_staff.connectors import (
    JIRA_APPROVED_PROJECT_KEY,
    GoogleCalendarConnector,
    GoogleCalendarHttpTransport,
    JiraConnector,
    JiraEnhancedSearchHttpTransport,
    StoredGoogleCalendarAuthorizationProvider,
    StoredJiraAuthorizationProvider,
    StoredTodoistAuthorizationProvider,
    TodoistConnector,
    TodoistHttpTransport,
)
from chief_of_staff.live_trial import LiveJiraIssueTrialRunner
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
    """Run the sole exact-project, exact-JQL live issue retrieval."""

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    trial_parser = subparsers.add_parser("trial")
    trial_parser.add_argument("--briefing-date", type=date.fromisoformat)
    parsed = parser.parse_args(arguments)

    LOCAL_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    LOCAL_ROOT.chmod(0o700)
    with Database.open(DATABASE_PATH) as database:
        state_store = StateStore(database)
        keychain = MacOSKeychain()
        report = LiveJiraIssueTrialRunner(
            state_store=state_store,
            repository_root=REPOSITORY_ROOT,
            repository_paths=APPROVED_REPOSITORY_PATHS,
            calendar_connector=_calendar_connector(state_store, keychain),
            todoist_connector=_todoist_connector(state_store, keychain),
            jira_connector=_jira_connector(state_store, keychain),
            output_directory=BRIEFING_DIRECTORY,
            briefing_date_override=parsed.briefing_date,
        ).run()
        _print_json(asdict(report))
        return 0


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
) -> TodoistConnector:
    authorization = state_store.get_connector_authorization("todoist")
    if authorization is None:
        raise RuntimeError("Todoist is not authorized")
    oauth = TodoistInstalledAppOAuth(
        keychain=keychain,
        state_store=state_store,
    )
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


def _jira_connector(
    state_store: StateStore,
    keychain: MacOSKeychain,
) -> JiraConnector:
    authorization = state_store.get_connector_authorization("jira")
    resource = state_store.get_connector_resource("jira")
    if authorization is None or resource is None:
        raise RuntimeError("Jira is not authorized for an approved site")
    reference = KeychainSecretReference(
        service=authorization.credential_service,
        account=authorization.access_token_account,
    )
    return JiraConnector(
        account_reference=authorization.account_reference,
        site_reference=resource.resource_reference,
        approved_project_keys=(JIRA_APPROVED_PROJECT_KEY,),
        authorization_provider=StoredJiraAuthorizationProvider(
            state_store=state_store,
            keychain=keychain,
        ),
        transport=JiraEnhancedSearchHttpTransport(
            keychain=keychain,
            access_token_reference=reference,
            approved_cloud_id=resource.resource_id,
            approved_site_url=resource.resource_url,
        ),
    )


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
