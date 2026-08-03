"""Synthetic tests for bounded Scheduled Morning Generation policy."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from chief_of_staff.auth import MacOSKeychain
from chief_of_staff.auth.keychain import SecurityCommandResult
from chief_of_staff.connector_health import (
    APPROVED_CONNECTORS,
    ConnectorHealth,
    ConnectorHealthReport,
)
from chief_of_staff.domain import (
    AuthorizationStatus,
    BriefingRun,
    BriefingStatus,
    ConnectorAuthorizationMetadata,
    ConnectorResourceMetadata,
    CredentialHealth,
    OAuthClientMetadata,
    ScheduledOccurrence,
    ScheduledOutcome,
)
from chief_of_staff.on_demand import OnDemandBriefingReport
from chief_of_staff.persistence import Database, StateStore
from chief_of_staff.scheduled_cli import _readiness_payload
from chief_of_staff.scheduling import (
    MAXIMUM_ELIGIBLE_DATES,
    TRIAL_ID,
    SafeMacOSNotifier,
    adopt_reviewed_application_version,
    create_trial,
    eligible_dates,
    first_eligible_date_after_installation,
    run_scheduled_once,
)

LOCAL_ZONE = ZoneInfo("America/New_York")


class _ReadinessKeychainRunner:
    def __init__(self) -> None:
        self.items: set[tuple[str, str]] = set()

    def __call__(
        self,
        arguments: tuple[str, ...],
        *,
        input_text: str | None,
        capture_output: bool,
    ) -> SecurityCommandResult:
        del input_text, capture_output
        service = arguments[arguments.index("-s") + 1]
        account = arguments[arguments.index("-a") + 1]
        return SecurityCommandResult(
            returncode=0 if (service, account) in self.items else 44
        )


def _local(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=LOCAL_ZONE)


def _health(
    unavailable: set[str] | None = None,
) -> tuple[ConnectorHealthReport, ...]:
    blocked = unavailable or set()
    return tuple(
        ConnectorHealthReport(
            connector=connector,
            health=(
                ConnectorHealth.EXPIRED
                if connector.instance_id in blocked
                else ConnectorHealth.HEALTHY
            ),
            can_retrieve=connector.instance_id not in blocked,
            detail="Synthetic safe health.",
        )
        for connector in APPROVED_CONNECTORS
    )


def _store_durable_connector_authorizations(
    store: StateStore,
    runner: _ReadinessKeychainRunner,
    *,
    omit_refresh_for: str | None = None,
) -> None:
    now = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    for connector in APPROVED_CONNECTORS:
        provider = connector.instance_id.partition(":")[0]
        access_account = f"{provider}:access"
        refresh_account = f"{provider}:refresh"
        store.save_oauth_client(
            OAuthClientMetadata(
                connector=provider,
                oauth_project_id="synthetic-project",
                oauth_client_id=f"{provider}-client",
                credential_service="test.service",
                client_secret_account=f"{provider}:client-secret",
                configured_at=now,
                connector_instance_id=connector.instance_id,
            )
        )
        refresh_present = connector.instance_id != omit_refresh_for
        store.save_connector_authorization(
            ConnectorAuthorizationMetadata(
                connector=provider,
                account_reference="primary-user",
                account_identity="user@example.invalid",
                granted_scope=connector.expected_scope,
                credential_service="test.service",
                access_token_account=access_account,
                refresh_token_account=(refresh_account if refresh_present else None),
                authorization_status=AuthorizationStatus.AUTHORIZED,
                credential_health=CredentialHealth.HEALTHY,
                refresh_health=(CredentialHealth.HEALTHY if refresh_present else None),
                token_expires_at=now + timedelta(days=3650),
                authorized_at=now,
                updated_at=now,
                connector_instance_id=connector.instance_id,
            )
        )
        runner.items.add(("test.service", access_account))
        if refresh_present:
            runner.items.add(("test.service", refresh_account))
        if connector.resource_required:
            store.save_connector_resource(
                ConnectorResourceMetadata(
                    connector=provider,
                    resource_reference="approved-site",
                    resource_id="synthetic-cloud-id",
                    resource_url="https://example.atlassian.net",
                    resource_type="jira_cloud_site",
                    grant_type="resource_level",
                    selected_at=now,
                    connector_instance_id=connector.instance_id,
                )
            )


def test_scheduled_readiness_requires_durable_continuity_for_every_connector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "chief_of_staff.scheduled_cli.host_readiness",
        lambda **_kwargs: (("synthetic_host", True),),
    )
    monkeypatch.setattr(
        "chief_of_staff.scheduled_cli.application_version",
        lambda: "reviewed.clean",
    )
    runner = _ReadinessKeychainRunner()
    keychain = MacOSKeychain(command_runner=runner)
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        _store_durable_connector_authorizations(
            store,
            runner,
            omit_refresh_for="jira:primary",
        )
        missing_jira = _readiness_payload(store, keychain)
        _store_durable_connector_authorizations(store, runner)
        complete = _readiness_payload(store, keychain)

    assert not missing_jira["ready"]
    assert missing_jira["source_policy"] == {
        "all_approved_connectors_durable": False,
        "calendar_ready": True,
        "gmail_ready": True,
        "jira_ready": False,
        "todoist_ready": True,
        "transient_runtime_failures_may_reduce_coverage": True,
    }
    assert complete["ready"]
    complete_policy = complete["source_policy"]
    assert isinstance(complete_policy, dict)
    assert complete_policy["all_approved_connectors_durable"] is True


def _briefing(
    tmp_path: Path,
    *,
    store: StateStore,
    reduced: bool = False,
) -> OnDemandBriefingReport:
    store.add_briefing_run(
        BriefingRun(
            id="scheduled-morning-synthetic",
            briefing_date=date(2026, 8, 1),
            timezone="America/New_York",
            invocation_mode="scheduled_morning",
            started_at=_local("2026-08-01T06:01:00"),
            completed_at=_local("2026-08-01T06:02:00"),
            status=BriefingStatus.SUCCEEDED,
        )
    )
    return OnDemandBriefingReport(
        briefing_run_id="scheduled-morning-synthetic",
        briefing_path=tmp_path / "briefing.md",
        review_path=None,
        briefing_word_count=500,
        source_coverage=(
            ("Repository", "complete"),
            ("Calendar", "complete"),
            ("Todoist", "complete"),
            ("Jira", "unavailable" if reduced else "complete"),
            ("Work Gmail", "partial" if reduced else "complete"),
        ),
        degraded_sources=(
            ()
            if not reduced
            else (
                ConnectorHealthReport(
                    connector=APPROVED_CONNECTORS[2],
                    health=ConnectorHealth.EXPIRED,
                    can_retrieve=False,
                    detail="Synthetic safe health.",
                ),
            )
        ),
    )


def test_first_date_is_strictly_after_install_and_skips_friday() -> None:
    assert first_eligible_date_after_installation(
        _local("2026-07-31T08:00:00")
    ) == date(2026, 8, 1)
    assert first_eligible_date_after_installation(
        _local("2026-08-03T05:59:00")
    ) == date(2026, 8, 3)
    assert first_eligible_date_after_installation(
        _local("2026-08-03T06:00:00")
    ) == date(2026, 8, 4)


def test_seven_dates_exclude_friday_and_keep_dst_local_trigger() -> None:
    dates = eligible_dates(date(2026, 10, 29))

    assert len(dates) == MAXIMUM_ELIGIBLE_DATES
    assert all(item.weekday() != 4 for item in dates)
    assert date(2026, 11, 1) in dates


def test_dst_transition_keeps_six_am_local_idempotency(
    tmp_path: Path,
) -> None:
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        store.save_scheduled_trial(create_trial(_local("2026-10-28T08:00:00")))
        report = run_scheduled_once(
            state_store=store,
            preflight=_health,
            generate=lambda _health_report: _briefing(
                tmp_path,
                store=store,
            ),
            now=_local("2026-11-01T05:30:00"),
        )
        occurrence = store.get_scheduled_occurrence(
            TRIAL_ID,
            date(2026, 11, 1),
        )

        assert report.outcome is ScheduledOutcome.BEFORE_WINDOW
        assert occurrence is not None
        scheduled_local = occurrence.scheduled_for.astimezone(LOCAL_ZONE)
        assert scheduled_local.hour == 6
        offset = scheduled_local.utcoffset()
        assert offset is not None
        assert offset.total_seconds() == -5 * 3600
        assert occurrence.idempotency_key == "scheduled_morning:2026-11-01"


def test_before_window_can_progress_but_terminal_success_cannot_retry(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    calls = 0
    notifications: list[tuple[str, ...]] = []

    def generate(
        _health_report: tuple[ConnectorHealthReport, ...],
    ) -> OnDemandBriefingReport:
        nonlocal calls
        calls += 1
        return _briefing(tmp_path, store=store)

    def notify(arguments: tuple[str, ...]) -> int:
        notifications.append(arguments)
        return 0

    notifier = SafeMacOSNotifier(command_runner=notify)
    with Database.open(database_path) as database:
        store = StateStore(database)
        store.save_scheduled_trial(create_trial(_local("2026-07-31T08:00:00")))

        early = run_scheduled_once(
            state_store=store,
            preflight=_health,
            generate=generate,
            now=_local("2026-08-01T05:30:00"),
            notifier=notifier,
        )
        success = run_scheduled_once(
            state_store=store,
            preflight=_health,
            generate=generate,
            now=_local("2026-08-01T06:01:00"),
            notifier=notifier,
        )
        repeated = run_scheduled_once(
            state_store=store,
            preflight=_health,
            generate=generate,
            now=_local("2026-08-01T08:00:00"),
            notifier=notifier,
        )

        assert early.outcome is ScheduledOutcome.BEFORE_WINDOW
        assert success.outcome is ScheduledOutcome.FULL_SUCCESS
        assert repeated.outcome is ScheduledOutcome.ALREADY_COMPLETED
        assert calls == 1
        assert len(store.list_scheduled_occurrences(TRIAL_ID)) == 1

    assert len(notifications) == 1
    assert "Morning briefing is ready." in " ".join(notifications[0])


def test_sleep_delayed_wake_runs_once_inside_catch_up_window(
    tmp_path: Path,
) -> None:
    calls = 0

    def generate(
        _health_report: tuple[ConnectorHealthReport, ...],
    ) -> OnDemandBriefingReport:
        nonlocal calls
        calls += 1
        return _briefing(tmp_path, store=store)

    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        store.save_scheduled_trial(create_trial(_local("2026-07-31T08:00:00")))

        delayed = run_scheduled_once(
            state_store=store,
            preflight=_health,
            generate=generate,
            now=_local("2026-08-01T09:30:00"),
        )
        repeated = run_scheduled_once(
            state_store=store,
            preflight=_health,
            generate=generate,
            now=_local("2026-08-01T09:31:00"),
        )

        assert delayed.outcome is ScheduledOutcome.FULL_SUCCESS
        assert delayed.eligibility_decision == "approved_window_execution_completed"
        assert repeated.outcome is ScheduledOutcome.ALREADY_COMPLETED
        assert calls == 1


def test_cutoff_records_miss_without_preflight_or_generation(
    tmp_path: Path,
) -> None:
    touched = False

    def forbidden_preflight() -> tuple[ConnectorHealthReport, ...]:
        nonlocal touched
        touched = True
        return _health()

    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        store.save_scheduled_trial(create_trial(_local("2026-07-31T08:00:00")))
        report = run_scheduled_once(
            state_store=store,
            preflight=forbidden_preflight,
            generate=lambda _health_report: _briefing(tmp_path, store=store),
            now=_local("2026-08-01T11:00:01"),
        )

        occurrence = store.get_scheduled_occurrence(
            TRIAL_ID,
            date(2026, 8, 1),
        )
        assert report.outcome is ScheduledOutcome.MISSED_AFTER_CUTOFF
        assert occurrence is not None
        assert occurrence.source_health_json == "{}"
        assert not touched


def test_application_version_change_stops_before_preflight(
    tmp_path: Path,
) -> None:
    touched = False

    def forbidden_preflight() -> tuple[ConnectorHealthReport, ...]:
        nonlocal touched
        touched = True
        return _health()

    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        trial = create_trial(_local("2026-07-31T08:00:00"))
        store.save_scheduled_trial(
            replace(trial, application_version="different-reviewed-build")
        )
        report = run_scheduled_once(
            state_store=store,
            preflight=forbidden_preflight,
            generate=lambda _health_report: _briefing(
                tmp_path,
                store=store,
            ),
            now=_local("2026-08-01T07:01:00"),
        )

        assert report.outcome is ScheduledOutcome.CONFIGURATION_FAILURE
        assert report.diagnostic_category == "trial_policy_mismatch"
        assert not touched


def test_reviewed_version_adoption_preserves_started_trial_and_occurrences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "chief_of_staff.scheduling.application_version",
        lambda: "0.0.0+oldversion01.clean",
    )
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        original = create_trial(_local("2026-07-31T08:00:00"))
        store.save_scheduled_trial(original)
        report = run_scheduled_once(
            state_store=store,
            preflight=_health,
            generate=lambda _health_report: _briefing(tmp_path, store=store),
            now=_local("2026-08-01T07:01:00"),
        )
        occurrences_before = store.list_scheduled_occurrences(TRIAL_ID)

        monkeypatch.setattr(
            "chief_of_staff.scheduling.application_version",
            lambda: "0.0.0+newversion02.clean",
        )
        updated = adopt_reviewed_application_version(
            store,
            now=_local("2026-08-03T13:00:00"),
        )

        assert report.outcome is ScheduledOutcome.FULL_SUCCESS
        assert updated.application_version == "0.0.0+newversion02.clean"
        assert updated.first_eligible_date == original.first_eligible_date
        assert updated.final_eligible_date == original.final_eligible_date
        assert updated.maximum_eligible_dates == original.maximum_eligible_dates
        assert updated.enabled == original.enabled
        assert store.list_scheduled_occurrences(TRIAL_ID) == occurrences_before


def test_reviewed_version_adoption_rejects_dirty_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "chief_of_staff.scheduling.application_version",
        lambda: "0.0.0+oldversion01.clean",
    )
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        original = create_trial(_local("2026-07-31T08:00:00"))
        store.save_scheduled_trial(original)
        monkeypatch.setattr(
            "chief_of_staff.scheduling.application_version",
            lambda: "0.0.0+newversion02.dirty",
        )

        with pytest.raises(RuntimeError, match="clean repository"):
            adopt_reviewed_application_version(
                store,
                now=_local("2026-08-03T13:00:00"),
            )

        assert store.get_scheduled_trial(TRIAL_ID) == original


def test_mandatory_source_policy_and_optional_jira(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    with Database.open(database_path) as database:
        store = StateStore(database)
        store.save_scheduled_trial(create_trial(_local("2026-07-31T08:00:00")))
        report = run_scheduled_once(
            state_store=store,
            preflight=lambda: _health({"google_calendar:primary", "jira:primary"}),
            generate=lambda _health_report: _briefing(
                tmp_path,
                store=store,
            ),
            now=_local("2026-08-01T07:01:00"),
        )
        assert report.outcome is ScheduledOutcome.CREDENTIAL_ATTENTION_REQUIRED

    with Database.open(tmp_path / "second.sqlite3") as database:
        store = StateStore(database)
        store.save_scheduled_trial(create_trial(_local("2026-07-31T08:00:00")))
        report = run_scheduled_once(
            state_store=store,
            preflight=lambda: _health({"jira:primary"}),
            generate=lambda _health_report: _briefing(
                tmp_path,
                store=store,
                reduced=True,
            ),
            now=_local("2026-08-01T07:01:00"),
        )
        assert report.outcome is ScheduledOutcome.REDUCED_SUCCESS


def test_both_action_sources_unavailable_prevents_generation(
    tmp_path: Path,
) -> None:
    generated = False

    def generate(
        _health_report: tuple[ConnectorHealthReport, ...],
    ) -> OnDemandBriefingReport:
        nonlocal generated
        generated = True
        return _briefing(tmp_path, store=store)

    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        store.save_scheduled_trial(create_trial(_local("2026-07-31T08:00:00")))
        report = run_scheduled_once(
            state_store=store,
            preflight=lambda: _health({"gmail:work", "todoist:primary"}),
            generate=generate,
            now=_local("2026-08-01T07:01:00"),
        )
        assert report.outcome is ScheduledOutcome.CREDENTIAL_ATTENTION_REQUIRED
        assert not generated


def test_failed_date_is_not_retried_and_counts_toward_trial(
    tmp_path: Path,
) -> None:
    calls = 0

    def fail(
        _health_report: tuple[ConnectorHealthReport, ...],
    ) -> OnDemandBriefingReport:
        nonlocal calls
        calls += 1
        raise RuntimeError("synthetic private detail")

    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        store.save_scheduled_trial(create_trial(_local("2026-07-31T08:00:00")))
        first = run_scheduled_once(
            state_store=store,
            preflight=_health,
            generate=fail,
            now=_local("2026-08-01T07:01:00"),
        )
        repeated = run_scheduled_once(
            state_store=store,
            preflight=_health,
            generate=fail,
            now=_local("2026-08-01T08:00:00"),
        )
        occurrence = store.get_scheduled_occurrence(
            TRIAL_ID,
            date(2026, 8, 1),
        )

        assert first.outcome is ScheduledOutcome.CONFIGURATION_FAILURE
        assert repeated.outcome is ScheduledOutcome.CONFIGURATION_FAILURE
        assert calls == 1
        assert occurrence is not None
        assert "synthetic private detail" not in json.dumps(asdict_safe(occurrence))


def test_eighth_date_is_inert_after_seven_missed_or_failed_dates(
    tmp_path: Path,
) -> None:
    called = False
    dates = eligible_dates(date(2026, 8, 1))
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        store.save_scheduled_trial(create_trial(_local("2026-07-31T08:00:00")))
        for eligible_date in dates:
            report = run_scheduled_once(
                state_store=store,
                preflight=_health,
                generate=lambda _health_report: _briefing(
                    tmp_path,
                    store=store,
                ),
                now=datetime(
                    eligible_date.year,
                    eligible_date.month,
                    eligible_date.day,
                    11,
                    1,
                    tzinfo=LOCAL_ZONE,
                ),
            )
            assert report.outcome is ScheduledOutcome.MISSED_AFTER_CUTOFF

        def forbidden() -> tuple[ConnectorHealthReport, ...]:
            nonlocal called
            called = True
            return _health()

        after = run_scheduled_once(
            state_store=store,
            preflight=forbidden,
            generate=lambda _health_report: _briefing(tmp_path, store=store),
            now=datetime(
                2026,
                8,
                9,
                7,
                1,
                tzinfo=LOCAL_ZONE,
            ),
        )
        trial = store.get_scheduled_trial(TRIAL_ID)

        assert after.outcome is ScheduledOutcome.TRIAL_COMPLETE
        assert not called
        assert trial is not None and not trial.enabled
        assert trial.completed_at is not None
        assert len(store.list_scheduled_occurrences(TRIAL_ID)) == 7


def test_notification_contract_has_only_fixed_safe_language() -> None:
    calls: list[tuple[str, ...]] = []

    def notify(arguments: tuple[str, ...]) -> int:
        calls.append(arguments)
        return 0

    notifier = SafeMacOSNotifier(command_runner=notify)

    assert (
        notifier.notify(ScheduledOutcome.CREDENTIAL_ATTENTION_REQUIRED) == "delivered"
    )
    joined = " ".join(calls[0])
    assert "/usr/bin/osascript" in joined
    assert "credential attention" in joined
    for private_marker in ("event title", "message body", "token", "@"):
        assert private_marker not in joined


def test_scheduled_entrypoint_exposes_no_interactive_or_broader_capability() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src" / "chief_of_staff"
    scheduled_source = "\n".join(
        (source_root / name).read_text(encoding="utf-8")
        for name in ("scheduled_cli.py", "scheduling.py", "launchagent.py")
    )

    for prohibited in (
        "authorize_interactively",
        "calendarList",
        "offline_access",
        "openai",
        "insert_event",
        "update_event",
        "delete_event",
        'RunAtLoad": True',
        'KeepAlive": True',
    ):
        assert prohibited not in scheduled_source


def asdict_safe(value: ScheduledOccurrence) -> dict[str, object]:
    """Expose only the dataclass fields needed for redaction assertions."""

    return {
        "eligibility_decision": value.eligibility_decision,
        "diagnostic_category": value.diagnostic_category,
        "source_health_json": value.source_health_json,
    }
