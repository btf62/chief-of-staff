"""Bounded, deterministic policy for Scheduled Morning Generation v1."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Final, Protocol
from zoneinfo import ZoneInfo

from chief_of_staff.connector_health import (
    ConnectorHealth,
    ConnectorHealthReport,
)
from chief_of_staff.connectors import (
    GMAIL_WORK_INSTANCE,
    GOOGLE_CALENDAR_PRIMARY_INSTANCE,
    TODOIST_PRIMARY_INSTANCE,
)
from chief_of_staff.domain import (
    ScheduledOccurrence,
    ScheduledOutcome,
    ScheduledTrial,
)
from chief_of_staff.on_demand import (
    InsufficientBriefingEvidence,
    OnDemandBriefingReport,
)
from chief_of_staff.persistence import StateStore

TRIAL_ID: Final = "scheduled-morning-v1"
SCHEDULE_TIMEZONE: Final = "America/New_York"
ELIGIBLE_WEEKDAYS: Final = (0, 1, 2, 3, 5, 6)
TRIGGER_HOUR: Final = 6
TRIGGER_MINUTE: Final = 0
CUTOFF_HOUR: Final = 11
CUTOFF_MINUTE: Final = 0
MAXIMUM_ELIGIBLE_DATES: Final = 7
INVOCATION_MODE: Final = "scheduled_morning"

_TERMINAL_OUTCOMES: Final = frozenset(
    {
        ScheduledOutcome.FULL_SUCCESS,
        ScheduledOutcome.REDUCED_SUCCESS,
        ScheduledOutcome.MISSED_AFTER_CUTOFF,
        ScheduledOutcome.INSUFFICIENT_SOURCES,
        ScheduledOutcome.CREDENTIAL_ATTENTION_REQUIRED,
        ScheduledOutcome.TRANSIENT_FAILURE,
        ScheduledOutcome.CONFIGURATION_FAILURE,
    }
)


class NotificationRunner(Protocol):
    """Execute one fixed, private-safe local notification command."""

    def __call__(self, arguments: tuple[str, ...]) -> int:
        """Return the local command exit code."""


def _run_notification(arguments: tuple[str, ...]) -> int:
    completed = subprocess.run(  # noqa: S603 - fixed osascript executable
        arguments,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode


@dataclass(frozen=True, slots=True)
class SafeMacOSNotifier:
    """Send fixed non-content notifications through the local macOS UI."""

    command_runner: NotificationRunner = field(
        default=_run_notification,
        repr=False,
        compare=False,
    )

    def notify(self, outcome: ScheduledOutcome) -> str | None:
        message = _notification_message(outcome)
        if message is None:
            return None
        script = f'display notification "{message}" with title "Chief of Staff"'
        try:
            result = self.command_runner(("/usr/bin/osascript", "-e", script))
        except OSError:
            return "delivery_failed"
        return "delivered" if result == 0 else "delivery_failed"


@dataclass(frozen=True, slots=True)
class ScheduledExecutionReport:
    """Private-safe result of one scheduler invocation."""

    outcome: ScheduledOutcome
    occurrence_date: date
    eligibility_decision: str
    trial_ordinal: int | None
    notification_result: str | None = None
    briefing_run_id: str | None = None
    briefing_path: str | None = None
    source_health: tuple[tuple[str, str], ...] = ()
    diagnostic_category: str | None = None


def application_version() -> str:
    """Return package plus repository state without network access."""

    try:
        package_version = version("chief-of-staff")
    except PackageNotFoundError:
        package_version = "0.0.0"
    repository_root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(  # noqa: S603 - fixed local git executable
        (
            "/usr/bin/git",
            "-C",
            str(repository_root),
            "rev-parse",
            "--verify",
            "HEAD",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if completed.returncode != 0:
        return package_version
    revision = completed.stdout.strip()
    if len(revision) != 40 or any(
        character not in "0123456789abcdef" for character in revision
    ):
        return package_version
    dirty = subprocess.run(  # noqa: S603 - fixed local git executable
        (
            "/usr/bin/git",
            "-C",
            str(repository_root),
            "status",
            "--porcelain",
            "--untracked-files=normal",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    state = "dirty" if dirty.returncode != 0 or dirty.stdout else "clean"
    return f"{package_version}+{revision[:12]}.{state}"


def eligible_dates(
    first_date: date,
    *,
    count: int = MAXIMUM_ELIGIBLE_DATES,
) -> tuple[date, ...]:
    """Return the next bounded set of accepted local scheduled dates."""

    if count <= 0:
        raise ValueError("eligible date count must be positive")
    result: list[date] = []
    candidate = first_date
    while len(result) < count:
        if candidate.weekday() in ELIGIBLE_WEEKDAYS:
            result.append(candidate)
        candidate += timedelta(days=1)
    return tuple(result)


def first_eligible_date_after_installation(installed_at: datetime) -> date:
    """Choose the first 6 a.m. occurrence strictly after installation."""

    local = _as_local(installed_at)
    candidate = local.date()
    while True:
        if candidate.weekday() in ELIGIBLE_WEEKDAYS:
            trigger = _scheduled_for(candidate)
            if trigger > local:
                return candidate
        candidate += timedelta(days=1)


def create_trial(installed_at: datetime) -> ScheduledTrial:
    """Create the accepted self-limiting seven-date trial configuration."""

    local = _as_local(installed_at)
    first_date = first_eligible_date_after_installation(local)
    dates = eligible_dates(first_date)
    return ScheduledTrial(
        id=TRIAL_ID,
        timezone=SCHEDULE_TIMEZONE,
        eligible_weekdays=ELIGIBLE_WEEKDAYS,
        trigger_hour=TRIGGER_HOUR,
        trigger_minute=TRIGGER_MINUTE,
        cutoff_hour=CUTOFF_HOUR,
        cutoff_minute=CUTOFF_MINUTE,
        first_eligible_date=dates[0],
        final_eligible_date=dates[-1],
        maximum_eligible_dates=len(dates),
        enabled=True,
        application_version=application_version(),
        created_at=local,
        updated_at=local,
    )


def set_trial_enabled(
    state_store: StateStore,
    *,
    enabled: bool,
    now: datetime,
) -> ScheduledTrial:
    """Toggle the bounded trial without altering its accepted date boundary."""

    trial = state_store.get_scheduled_trial(TRIAL_ID)
    if trial is None:
        raise RuntimeError("Scheduled Morning Generation is not installed")
    if enabled and trial.completed_at is not None:
        raise RuntimeError("the bounded scheduled trial is complete")
    local = _as_local(now)
    updated = replace(
        trial,
        enabled=enabled,
        updated_at=local,
    )
    state_store.save_scheduled_trial(updated)
    return updated


def reconfigure_unstarted_trial(
    state_store: StateStore,
    *,
    now: datetime,
) -> ScheduledTrial:
    """Adopt the current accepted time without resetting the trial boundary."""

    trial = state_store.get_scheduled_trial(TRIAL_ID)
    if trial is None:
        raise RuntimeError("Scheduled Morning Generation is not installed")
    if trial.completed_at is not None:
        raise RuntimeError("the bounded scheduled trial is complete")
    if state_store.list_scheduled_occurrences(TRIAL_ID):
        raise RuntimeError("a started scheduled trial cannot be reconfigured")
    local = _as_local(now)
    updated = replace(
        trial,
        trigger_hour=TRIGGER_HOUR,
        trigger_minute=TRIGGER_MINUTE,
        enabled=False,
        application_version=application_version(),
        updated_at=local,
    )
    state_store.reconfigure_unstarted_scheduled_trial(updated)
    return updated


def adopt_reviewed_application_version(
    state_store: StateStore,
    *,
    now: datetime,
) -> ScheduledTrial:
    """Adopt one clean reviewed version without changing a started trial."""

    trial = state_store.get_scheduled_trial(TRIAL_ID)
    if trial is None:
        raise RuntimeError("Scheduled Morning Generation is not installed")
    if trial.completed_at is not None:
        raise RuntimeError("the bounded scheduled trial is complete")
    _validate_trial_structure(trial)
    reviewed_version = application_version()
    if not reviewed_version.endswith(".clean"):
        raise RuntimeError("application version adoption requires a clean repository")
    local = _as_local(now)
    updated = replace(
        trial,
        application_version=reviewed_version,
        updated_at=local,
    )
    state_store.save_scheduled_trial(updated)
    return updated


def run_scheduled_once(
    *,
    state_store: StateStore,
    preflight: Callable[[], tuple[ConnectorHealthReport, ...]],
    generate: Callable[
        [tuple[ConnectorHealthReport, ...]],
        OnDemandBriefingReport,
    ],
    now: datetime,
    notifier: SafeMacOSNotifier | None = None,
) -> ScheduledExecutionReport:
    """Execute one policy-gated run with no automatic whole-run retry."""

    local = _as_local(now)
    trial = state_store.get_scheduled_trial(TRIAL_ID)
    if trial is None:
        return _unrecorded_report(
            ScheduledOutcome.CONFIGURATION_FAILURE,
            local.date(),
            "trial_not_installed",
        )
    try:
        _validate_trial_policy(trial)
    except RuntimeError:
        return _unrecorded_report(
            ScheduledOutcome.CONFIGURATION_FAILURE,
            local.date(),
            "trial_policy_mismatch",
        )
    _record_prior_misses(state_store, trial, local)
    dates = _trial_dates(trial)
    today = local.date()
    if today > trial.final_eligible_date:
        _complete_trial(state_store, trial, local)
        return _unrecorded_report(
            ScheduledOutcome.TRIAL_COMPLETE,
            today,
            "trial_date_boundary_complete",
        )
    if today not in dates:
        return _unrecorded_report(
            ScheduledOutcome.INELIGIBLE_DAY,
            today,
            "weekday_not_eligible",
        )

    ordinal = dates.index(today) + 1
    existing = state_store.get_scheduled_occurrence(TRIAL_ID, today)
    if existing is not None and existing.outcome in _TERMINAL_OUTCOMES:
        if existing.outcome in {
            ScheduledOutcome.FULL_SUCCESS,
            ScheduledOutcome.REDUCED_SUCCESS,
        }:
            return ScheduledExecutionReport(
                outcome=ScheduledOutcome.ALREADY_COMPLETED,
                occurrence_date=today,
                eligibility_decision="terminal_success_already_recorded",
                trial_ordinal=existing.trial_ordinal,
                notification_result=existing.notification_result,
                briefing_run_id=existing.briefing_run_id,
            )
        return _report_from_occurrence(existing)
    if not trial.enabled:
        return _unrecorded_report(
            ScheduledOutcome.CONFIGURATION_FAILURE,
            today,
            "trial_disabled",
        )

    trigger = _scheduled_for(today)
    cutoff = _cutoff_for(today)
    if local < trigger:
        return _record_result(
            state_store=state_store,
            trial=trial,
            now=local,
            outcome=ScheduledOutcome.BEFORE_WINDOW,
            decision="before_approved_trigger",
            ordinal=ordinal,
            notifier=None,
        )
    if local > cutoff:
        report = _record_result(
            state_store=state_store,
            trial=trial,
            now=local,
            outcome=ScheduledOutcome.MISSED_AFTER_CUTOFF,
            decision="after_approved_catch_up_cutoff",
            ordinal=ordinal,
            notifier=notifier,
        )
        _complete_if_final(state_store, trial, local, today)
        return report

    started_monotonic = time.monotonic()
    try:
        health = preflight()
    except Exception:
        report = _record_result(
            state_store=state_store,
            trial=trial,
            now=local,
            outcome=ScheduledOutcome.CONFIGURATION_FAILURE,
            decision="connector_preflight_failed",
            ordinal=ordinal,
            notifier=notifier,
            diagnostic="preflight_inspection_failure",
        )
        _complete_if_final(state_store, trial, local, today)
        return report
    source_health = tuple(
        (item.connector.display_name, item.health.value) for item in health
    )
    preflight_failure = _preflight_failure(health)
    if preflight_failure is not None:
        outcome, preflight_diagnostic = preflight_failure
        report = _record_result(
            state_store=state_store,
            trial=trial,
            now=local,
            outcome=outcome,
            decision="mandatory_source_preflight_failed",
            ordinal=ordinal,
            notifier=notifier,
            source_health=source_health,
            diagnostic=preflight_diagnostic,
        )
        _complete_if_final(state_store, trial, local, today)
        return report

    briefing: OnDemandBriefingReport | None
    diagnostic: str | None
    try:
        generated_briefing = generate(health)
    except InsufficientBriefingEvidence:
        outcome = ScheduledOutcome.INSUFFICIENT_SOURCES
        diagnostic = "pipeline_evidence_requirement"
        briefing = None
    except ConnectionError, TimeoutError, OSError:
        outcome = ScheduledOutcome.TRANSIENT_FAILURE
        diagnostic = "local_or_provider_transport"
        briefing = None
    except Exception:
        outcome = ScheduledOutcome.CONFIGURATION_FAILURE
        diagnostic = "unexpected_application_failure"
        briefing = None
    else:
        briefing = generated_briefing
        outcome = _success_outcome(generated_briefing)
        diagnostic = None

    duration_ms = max(
        0,
        int((time.monotonic() - started_monotonic) * 1000),
    )
    report = _record_result(
        state_store=state_store,
        trial=trial,
        now=local,
        outcome=outcome,
        decision="approved_window_execution_completed",
        ordinal=ordinal,
        notifier=notifier,
        source_health=source_health,
        diagnostic=diagnostic,
        briefing=briefing,
        duration_ms=duration_ms,
    )
    _complete_if_final(state_store, trial, local, today)
    return report


def _preflight_failure(
    health: tuple[ConnectorHealthReport, ...],
) -> tuple[ScheduledOutcome, str] | None:
    by_instance = {item.connector.instance_id: item for item in health}
    calendar = by_instance.get(GOOGLE_CALENDAR_PRIMARY_INSTANCE)
    gmail = by_instance.get(GMAIL_WORK_INSTANCE)
    todoist = by_instance.get(TODOIST_PRIMARY_INSTANCE)
    if calendar is None or gmail is None or todoist is None:
        return ScheduledOutcome.CONFIGURATION_FAILURE, "preflight_incomplete"
    if calendar.can_retrieve and (gmail.can_retrieve or todoist.can_retrieve):
        return None
    mandatory_failures = ((calendar,) if not calendar.can_retrieve else ()) + (
        tuple(item for item in (gmail, todoist) if not item.can_retrieve)
        if not gmail.can_retrieve and not todoist.can_retrieve
        else ()
    )
    credential_states = {
        ConnectorHealth.EXPIRED,
        ConnectorHealth.MISSING,
        ConnectorHealth.UNAUTHORIZED,
        ConnectorHealth.BOUNDARY_EXCEEDED,
    }
    if any(item.health in credential_states for item in mandatory_failures):
        return (
            ScheduledOutcome.CREDENTIAL_ATTENTION_REQUIRED,
            "mandatory_credential_unavailable",
        )
    return ScheduledOutcome.INSUFFICIENT_SOURCES, "mandatory_source_unavailable"


def _success_outcome(report: OnDemandBriefingReport) -> ScheduledOutcome:
    statuses = tuple(status for _source, status in report.source_coverage)
    if (
        not report.degraded_sources
        and statuses
        and all(status == "complete" for status in statuses)
    ):
        return ScheduledOutcome.FULL_SUCCESS
    return ScheduledOutcome.REDUCED_SUCCESS


def _record_prior_misses(
    state_store: StateStore,
    trial: ScheduledTrial,
    now: datetime,
) -> None:
    for ordinal, eligible_date in enumerate(_trial_dates(trial), start=1):
        if eligible_date >= now.date():
            break
        existing = state_store.get_scheduled_occurrence(TRIAL_ID, eligible_date)
        if existing is not None and existing.outcome in _TERMINAL_OUTCOMES:
            continue
        _save_occurrence(
            state_store=state_store,
            trial=trial,
            now=now,
            occurrence_date=eligible_date,
            outcome=ScheduledOutcome.MISSED_AFTER_CUTOFF,
            decision="eligible_date_passed_without_terminal_run",
            ordinal=ordinal,
            notification_result=None,
            diagnostic="host_or_trigger_unavailable",
        )


def _record_result(
    *,
    state_store: StateStore,
    trial: ScheduledTrial,
    now: datetime,
    outcome: ScheduledOutcome,
    decision: str,
    ordinal: int,
    notifier: SafeMacOSNotifier | None,
    source_health: tuple[tuple[str, str], ...] = (),
    diagnostic: str | None = None,
    briefing: OnDemandBriefingReport | None = None,
    duration_ms: int | None = None,
) -> ScheduledExecutionReport:
    notification_result = None if notifier is None else notifier.notify(outcome)
    _save_occurrence(
        state_store=state_store,
        trial=trial,
        now=now,
        occurrence_date=now.date(),
        outcome=outcome,
        decision=decision,
        ordinal=ordinal,
        notification_result=notification_result,
        source_health=source_health,
        diagnostic=diagnostic,
        briefing=briefing,
        duration_ms=duration_ms,
    )
    return ScheduledExecutionReport(
        outcome=outcome,
        occurrence_date=now.date(),
        eligibility_decision=decision,
        trial_ordinal=ordinal,
        notification_result=notification_result,
        briefing_run_id=(None if briefing is None else briefing.briefing_run_id),
        briefing_path=(None if briefing is None else str(briefing.briefing_path)),
        source_health=source_health,
        diagnostic_category=diagnostic,
    )


def _save_occurrence(
    *,
    state_store: StateStore,
    trial: ScheduledTrial,
    now: datetime,
    occurrence_date: date,
    outcome: ScheduledOutcome,
    decision: str,
    ordinal: int,
    notification_result: str | None,
    source_health: tuple[tuple[str, str], ...] = (),
    diagnostic: str | None = None,
    briefing: OnDemandBriefingReport | None = None,
    duration_ms: int | None = None,
) -> None:
    counts = (
        {}
        if briefing is None
        else {
            "briefing_words": briefing.briefing_word_count,
            "degraded_sources": len(briefing.degraded_sources),
        }
    )
    state_store.save_scheduled_occurrence(
        ScheduledOccurrence(
            trial_id=trial.id,
            occurrence_date=occurrence_date,
            idempotency_key=f"{INVOCATION_MODE}:{occurrence_date.isoformat()}",
            scheduled_for=_scheduled_for(occurrence_date),
            actual_start_at=now,
            eligibility_decision=decision,
            outcome=outcome,
            trial_ordinal=ordinal,
            application_version=application_version(),
            updated_at=now,
            briefing_run_id=(None if briefing is None else briefing.briefing_run_id),
            source_health_json=json.dumps(
                dict(source_health),
                separators=(",", ":"),
                sort_keys=True,
            ),
            aggregate_counts_json=json.dumps(
                counts,
                separators=(",", ":"),
                sort_keys=True,
            ),
            duration_ms=duration_ms,
            notification_result=notification_result,
            diagnostic_category=diagnostic,
        )
    )


def _complete_if_final(
    state_store: StateStore,
    trial: ScheduledTrial,
    now: datetime,
    occurrence_date: date,
) -> None:
    if occurrence_date == trial.final_eligible_date:
        _complete_trial(state_store, trial, now)


def _complete_trial(
    state_store: StateStore,
    trial: ScheduledTrial,
    now: datetime,
) -> None:
    if trial.completed_at is not None and not trial.enabled:
        return
    state_store.save_scheduled_trial(
        replace(
            trial,
            enabled=False,
            updated_at=now,
            completed_at=now,
        )
    )


def _trial_dates(trial: ScheduledTrial) -> tuple[date, ...]:
    return eligible_dates(
        trial.first_eligible_date,
        count=trial.maximum_eligible_dates,
    )


def _validate_trial_policy(trial: ScheduledTrial) -> None:
    _validate_trial_structure(trial)
    if trial.application_version != application_version():
        raise RuntimeError("stored scheduled trial does not match accepted policy")


def _validate_trial_structure(trial: ScheduledTrial) -> None:
    dates = _trial_dates(trial)
    if (
        trial.id != TRIAL_ID
        or trial.timezone != SCHEDULE_TIMEZONE
        or trial.eligible_weekdays != ELIGIBLE_WEEKDAYS
        or trial.trigger_hour != TRIGGER_HOUR
        or trial.trigger_minute != TRIGGER_MINUTE
        or trial.cutoff_hour != CUTOFF_HOUR
        or trial.cutoff_minute != CUTOFF_MINUTE
        or trial.maximum_eligible_dates != MAXIMUM_ELIGIBLE_DATES
        or trial.final_eligible_date != dates[-1]
    ):
        raise RuntimeError("stored scheduled trial does not match accepted policy")


def _scheduled_for(value: date) -> datetime:
    return datetime(
        value.year,
        value.month,
        value.day,
        TRIGGER_HOUR,
        TRIGGER_MINUTE,
        tzinfo=ZoneInfo(SCHEDULE_TIMEZONE),
    )


def _cutoff_for(value: date) -> datetime:
    return datetime(
        value.year,
        value.month,
        value.day,
        CUTOFF_HOUR,
        CUTOFF_MINUTE,
        tzinfo=ZoneInfo(SCHEDULE_TIMEZONE),
    )


def _as_local(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("scheduler time must be timezone-aware")
    return value.astimezone(ZoneInfo(SCHEDULE_TIMEZONE))


def _unrecorded_report(
    outcome: ScheduledOutcome,
    occurrence_date: date,
    decision: str,
) -> ScheduledExecutionReport:
    return ScheduledExecutionReport(
        outcome=outcome,
        occurrence_date=occurrence_date,
        eligibility_decision=decision,
        trial_ordinal=None,
        diagnostic_category=decision,
    )


def _report_from_occurrence(
    occurrence: ScheduledOccurrence,
) -> ScheduledExecutionReport:
    source_health = json.loads(occurrence.source_health_json)
    return ScheduledExecutionReport(
        outcome=occurrence.outcome,
        occurrence_date=occurrence.occurrence_date,
        eligibility_decision=occurrence.eligibility_decision,
        trial_ordinal=occurrence.trial_ordinal,
        notification_result=occurrence.notification_result,
        briefing_run_id=occurrence.briefing_run_id,
        source_health=tuple(sorted(source_health.items())),
        diagnostic_category=occurrence.diagnostic_category,
    )


def _notification_message(outcome: ScheduledOutcome) -> str | None:
    messages = {
        ScheduledOutcome.FULL_SUCCESS: "Morning briefing is ready.",
        ScheduledOutcome.REDUCED_SUCCESS: (
            "Morning briefing is ready with reduced source coverage."
        ),
        ScheduledOutcome.MISSED_AFTER_CUTOFF: (
            "Morning briefing was missed after the approved cutoff."
        ),
        ScheduledOutcome.INSUFFICIENT_SOURCES: (
            "Morning briefing needs attention: required sources were unavailable."
        ),
        ScheduledOutcome.CREDENTIAL_ATTENTION_REQUIRED: (
            "Morning briefing needs credential attention."
        ),
        ScheduledOutcome.TRANSIENT_FAILURE: (
            "Morning briefing needs attention after a temporary failure."
        ),
        ScheduledOutcome.CONFIGURATION_FAILURE: (
            "Morning briefing needs configuration attention."
        ),
    }
    return messages.get(outcome)
