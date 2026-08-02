"""Private operator commands for bounded Scheduled Morning Generation v1."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

from chief_of_staff.auth import (
    KeychainSecretReference,
    MacOSKeychain,
    WorkGmailInstalledAppOAuth,
)
from chief_of_staff.connector_health import (
    APPROVED_CONNECTORS,
    ConnectorHealthReport,
    inspect_approved_connectors,
)
from chief_of_staff.connectors import (
    GMAIL_WORK_INSTANCE,
    GOOGLE_CALENDAR_PRIMARY_INSTANCE,
    TODOIST_PRIMARY_INSTANCE,
)
from chief_of_staff.domain import CredentialHealth, ScheduledOutcome
from chief_of_staff.gmail_live_cli import (
    APPROVED_REPOSITORY_PATHS,
    BRIEFING_DIRECTORY,
    BRIEFING_LOCK_PATH,
    DATABASE_PATH,
    LOCAL_ROOT,
    REPOSITORY_ROOT,
    REVIEW_DIRECTORY,
    _exclusive_briefing_run,
    _gmail_connector,
)
from chief_of_staff.jira_issue_live_cli import (
    _calendar_connector,
    _jira_connector,
    _todoist_connector,
)
from chief_of_staff.launchagent import (
    LAUNCH_AGENT_LABEL,
    LaunchAgentManager,
    default_plist_path,
    host_readiness,
    launch_agent_payload,
)
from chief_of_staff.on_demand import (
    OnDemandBriefingReport,
    OnDemandBriefingRunner,
)
from chief_of_staff.persistence import Database, StateStore
from chief_of_staff.scheduling import (
    ELIGIBLE_WEEKDAYS,
    MAXIMUM_ELIGIBLE_DATES,
    SCHEDULE_TIMEZONE,
    TRIAL_ID,
    TRIGGER_HOUR,
    TRIGGER_MINUTE,
    SafeMacOSNotifier,
    application_version,
    create_trial,
    reconfigure_unstarted_trial,
    run_scheduled_once,
    set_trial_enabled,
)


def main(arguments: list[str] | None = None) -> int:
    """Inspect or operate the exact accepted user-level schedule."""

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("readiness")
    subparsers.add_parser("dry-run")
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("--confirm-primary-host", action="store_true")
    update_parser = subparsers.add_parser("update-schedule")
    update_parser.add_argument("--confirm-trigger-hour", type=int, required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("disable")
    subparsers.add_parser("enable")
    subparsers.add_parser("remove")
    subparsers.add_parser("notify-test")
    subparsers.add_parser("run")
    parsed = parser.parse_args(arguments)

    if parsed.command == "dry-run":
        return _dry_run()

    LOCAL_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    LOCAL_ROOT.chmod(0o700)
    with Database.open(DATABASE_PATH) as database:
        store = StateStore(database)
        keychain = MacOSKeychain()
        manager = LaunchAgentManager(
            repository_root=REPOSITORY_ROOT,
            python_executable=Path(sys.executable),
        )
        if parsed.command == "readiness":
            _print_json(_readiness_payload(store, keychain))
            return 0
        if parsed.command == "install":
            if not parsed.confirm_primary_host:
                raise RuntimeError(
                    "installation requires explicit primary-host confirmation"
                )
            readiness = _readiness_payload(store, keychain)
            if not readiness["ready"]:
                raise RuntimeError("host or connector readiness is incomplete")
            if store.get_scheduled_trial(TRIAL_ID) is not None:
                raise RuntimeError("the bounded scheduled trial already exists")
            now = datetime.now(UTC)
            trial = create_trial(now)
            store.save_scheduled_trial(trial)
            try:
                manager.install_and_load()
            except BaseException:
                store.delete_empty_scheduled_trial(trial.id)
                raise
            _print_json(
                {
                    "first_eligible_date": trial.first_eligible_date,
                    "final_eligible_date": trial.final_eligible_date,
                    "label": LAUNCH_AGENT_LABEL,
                    "loaded": manager.loaded(),
                    "maximum_eligible_dates": trial.maximum_eligible_dates,
                    "status": "installed",
                }
            )
            return 0
        if parsed.command == "update-schedule":
            if parsed.confirm_trigger_hour != TRIGGER_HOUR:
                raise RuntimeError("trigger-hour confirmation does not match policy")
            readiness = _readiness_payload(store, keychain)
            if not readiness["ready"]:
                raise RuntimeError("host or connector readiness is incomplete")
            existing_trial = store.get_scheduled_trial(TRIAL_ID)
            if existing_trial is None:
                raise RuntimeError("Scheduled Morning Generation is not installed")
            if store.list_scheduled_occurrences(TRIAL_ID):
                raise RuntimeError("a started scheduled trial cannot be reconfigured")
            manager.disable()
            trial = reconfigure_unstarted_trial(store, now=datetime.now(UTC))
            manager.install_and_load()
            trial = set_trial_enabled(
                store,
                enabled=True,
                now=datetime.now(UTC),
            )
            _print_json(
                {
                    "enabled": trial.enabled,
                    "final_eligible_date": trial.final_eligible_date,
                    "first_eligible_date": trial.first_eligible_date,
                    "label": LAUNCH_AGENT_LABEL,
                    "loaded": manager.loaded(),
                    "status": "schedule_updated",
                    "trigger_hour": trial.trigger_hour,
                    "trigger_minute": trial.trigger_minute,
                }
            )
            return 0
        if parsed.command == "status":
            _print_json(_status_payload(store, keychain, manager))
            return 0
        if parsed.command == "disable":
            manager.disable()
            trial = set_trial_enabled(
                store,
                enabled=False,
                now=datetime.now(UTC),
            )
            _print_json(
                {
                    "enabled": trial.enabled,
                    "label": LAUNCH_AGENT_LABEL,
                    "loaded": manager.loaded(),
                }
            )
            return 0
        if parsed.command == "enable":
            existing_trial = store.get_scheduled_trial(TRIAL_ID)
            if existing_trial is None:
                raise RuntimeError("Scheduled Morning Generation is not installed")
            if existing_trial.completed_at is not None:
                raise RuntimeError("the bounded scheduled trial is complete")
            manager.enable()
            trial = set_trial_enabled(
                store,
                enabled=True,
                now=datetime.now(UTC),
            )
            _print_json(
                {
                    "enabled": trial.enabled,
                    "label": LAUNCH_AGENT_LABEL,
                    "loaded": manager.loaded(),
                }
            )
            return 0
        if parsed.command == "remove":
            manager.remove()
            existing_trial = store.get_scheduled_trial(TRIAL_ID)
            if existing_trial is not None:
                set_trial_enabled(
                    store,
                    enabled=False,
                    now=datetime.now(UTC),
                )
            _print_json(
                {
                    "history_preserved": True,
                    "label": LAUNCH_AGENT_LABEL,
                    "plist_present": default_plist_path().exists(),
                    "status": "removed",
                }
            )
            return 0
        if parsed.command == "notify-test":
            result = SafeMacOSNotifier().notify(ScheduledOutcome.FULL_SUCCESS)
            _print_json(
                {
                    "notification_result": result,
                    "private_content_included": False,
                }
            )
            return 0
        if parsed.command == "run":
            return _run(store, keychain)
    raise RuntimeError("unsupported scheduled command")


def _run(store: StateStore, keychain: MacOSKeychain) -> int:
    def preflight() -> tuple[ConnectorHealthReport, ...]:
        return inspect_approved_connectors(store, keychain)

    def generate(
        health: tuple[ConnectorHealthReport, ...],
    ) -> OnDemandBriefingReport:
        typed_health = health
        by_instance = {report.connector.instance_id: report for report in typed_health}
        gmail_oauth = WorkGmailInstalledAppOAuth(
            keychain=keychain,
            state_store=store,
        )
        return OnDemandBriefingRunner(
            state_store=store,
            repository_root=REPOSITORY_ROOT,
            repository_paths=APPROVED_REPOSITORY_PATHS,
            approved_connectors=APPROVED_CONNECTORS,
            preflight=typed_health,
            calendar_connector=(
                _calendar_connector(store, keychain)
                if by_instance[GOOGLE_CALENDAR_PRIMARY_INSTANCE].can_retrieve
                else None
            ),
            todoist_connector=(
                _todoist_connector(store, keychain)
                if by_instance[TODOIST_PRIMARY_INSTANCE].can_retrieve
                else None
            ),
            jira_connector=(
                _jira_connector(store, keychain)
                if by_instance["jira:primary"].can_retrieve
                else None
            ),
            gmail_connector=(
                _gmail_connector(store, keychain, gmail_oauth)
                if by_instance[GMAIL_WORK_INSTANCE].can_retrieve
                else None
            ),
            briefing_directory=BRIEFING_DIRECTORY,
            review_directory=REVIEW_DIRECTORY,
            invocation_mode="scheduled_morning",
            run_id_prefix="scheduled-morning",
            require_calendar_and_action_source=True,
        ).run()

    try:
        with _exclusive_briefing_run(BRIEFING_LOCK_PATH):
            report = run_scheduled_once(
                state_store=store,
                preflight=preflight,
                generate=generate,
                now=datetime.now(UTC),
                notifier=SafeMacOSNotifier(),
            )
    except BlockingIOError:
        _print_json(
            {
                "diagnostic_category": "briefing_process_lock_held",
                "outcome": ScheduledOutcome.TRANSIENT_FAILURE.value,
            }
        )
        return 3
    _print_json(asdict(report))
    return (
        0
        if report.outcome
        in {
            ScheduledOutcome.FULL_SUCCESS,
            ScheduledOutcome.REDUCED_SUCCESS,
            ScheduledOutcome.ALREADY_COMPLETED,
            ScheduledOutcome.INELIGIBLE_DAY,
            ScheduledOutcome.BEFORE_WINDOW,
            ScheduledOutcome.TRIAL_COMPLETE,
        }
        else 2
    )


def _dry_run() -> int:
    now = datetime(2026, 7, 31, 16, 0, tzinfo=UTC)
    trial = create_trial(now)
    payload = launch_agent_payload(
        repository_root=REPOSITORY_ROOT,
        python_executable=Path(sys.executable),
    )
    _print_json(
        {
            "connector_access": False,
            "eligible_weekdays": list(ELIGIBLE_WEEKDAYS),
            "first_eligible_date": trial.first_eligible_date,
            "final_eligible_date": trial.final_eligible_date,
            "launch_agent_label": payload["Label"],
            "maximum_eligible_dates": MAXIMUM_ELIGIBLE_DATES,
            "persistent_state_changed": False,
            "timezone": SCHEDULE_TIMEZONE,
            "trigger_hour": TRIGGER_HOUR,
            "trigger_minute": TRIGGER_MINUTE,
        }
    )
    return 0


def _readiness_payload(
    store: StateStore,
    keychain: MacOSKeychain,
) -> dict[str, object]:
    host = host_readiness(
        repository_root=REPOSITORY_ROOT,
        python_executable=Path(sys.executable),
    )
    clean_application = application_version().endswith(".clean")
    health = inspect_approved_connectors(store, keychain)
    by_instance = {item.connector.instance_id: item for item in health}
    calendar_ready = by_instance[
        GOOGLE_CALENDAR_PRIMARY_INSTANCE
    ].can_retrieve and _refresh_ready(
        store,
        keychain,
        GOOGLE_CALENDAR_PRIMARY_INSTANCE,
    )
    action_ready = (
        by_instance[GMAIL_WORK_INSTANCE].can_retrieve
        and _refresh_ready(store, keychain, GMAIL_WORK_INSTANCE)
    ) or (
        by_instance[TODOIST_PRIMARY_INSTANCE].can_retrieve
        and _refresh_ready(store, keychain, TODOIST_PRIMARY_INSTANCE)
    )
    return {
        "connectors": {
            item.connector.display_name: item.health.value for item in health
        },
        "host": dict(host),
        "ready": all(value for _name, value in host)
        and clean_application
        and calendar_ready
        and action_ready,
        "reviewed_application_tree": clean_application,
        "source_policy": {
            "calendar_ready": calendar_ready,
            "gmail_or_todoist_ready": action_ready,
            "jira_optional": True,
        },
    }


def _refresh_ready(
    store: StateStore,
    keychain: MacOSKeychain,
    connector_instance: str,
) -> bool:
    authorization = store.get_connector_authorization(connector_instance)
    if (
        authorization is None
        or authorization.refresh_token_account is None
        or authorization.refresh_health is not CredentialHealth.HEALTHY
    ):
        return False
    return keychain.exists(
        KeychainSecretReference(
            service=authorization.credential_service,
            account=authorization.refresh_token_account,
        )
    )


def _status_payload(
    store: StateStore,
    keychain: MacOSKeychain,
    manager: LaunchAgentManager,
) -> dict[str, object]:
    trial = store.get_scheduled_trial(TRIAL_ID)
    occurrences = () if trial is None else store.list_scheduled_occurrences(TRIAL_ID)
    health = inspect_approved_connectors(store, keychain)
    return {
        "connector_health": {
            item.connector.display_name: item.health.value for item in health
        },
        "refresh_continuity": {
            "Google Calendar": _refresh_ready(
                store,
                keychain,
                GOOGLE_CALENDAR_PRIMARY_INSTANCE,
            ),
            "Todoist": _refresh_ready(
                store,
                keychain,
                TODOIST_PRIMARY_INSTANCE,
            ),
            "Work Gmail": _refresh_ready(
                store,
                keychain,
                GMAIL_WORK_INSTANCE,
            ),
        },
        "launch_agent": {
            "installed": manager.plist_path.is_file(),
            "label": LAUNCH_AGENT_LABEL,
            "loaded": manager.loaded(),
        },
        "latest_outcome": (None if not occurrences else occurrences[-1].outcome.value),
        "recorded_eligible_dates": len(
            {
                item.occurrence_date
                for item in occurrences
                if item.trial_ordinal is not None
                and item.outcome
                not in {
                    ScheduledOutcome.BEFORE_WINDOW,
                    ScheduledOutcome.INELIGIBLE_DAY,
                }
            }
        ),
        "trial": (
            None
            if trial is None
            else {
                "completed": trial.completed_at is not None,
                "enabled": trial.enabled,
                "final_eligible_date": trial.final_eligible_date,
                "first_eligible_date": trial.first_eligible_date,
                "maximum_eligible_dates": trial.maximum_eligible_dates,
                "timezone": trial.timezone,
                "trigger_hour": trial.trigger_hour,
                "trigger_minute": trial.trigger_minute,
            }
        ),
    }


def _print_json(payload: object) -> None:
    print(
        json.dumps(
            payload,
            default=_json_default,
            indent=2,
            sort_keys=True,
        )
    )


def _json_default(value: object) -> str:
    if isinstance(value, date | datetime | Path):
        return str(value)
    if isinstance(value, ScheduledOutcome):
        return value.value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
