"""Privacy and lifecycle tests for scheduled diagnostic logging."""

from __future__ import annotations

import json
import stat
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from chief_of_staff.auth import MacOSKeychain
from chief_of_staff.domain import ScheduledOutcome
from chief_of_staff.persistence import Database, StateStore
from chief_of_staff.scheduled_cli import _run
from chief_of_staff.scheduled_diagnostics import (
    append_scheduled_run_diagnostic,
    scheduled_diagnostic_snapshot,
)
from chief_of_staff.scheduling import (
    ScheduledExecutionReport,
    create_trial,
)


def _report() -> ScheduledExecutionReport:
    return ScheduledExecutionReport(
        outcome=ScheduledOutcome.CONFIGURATION_FAILURE,
        occurrence_date=date(2026, 8, 3),
        eligibility_decision="trial_policy_mismatch",
        trial_ordinal=None,
        notification_result="delivery_failed",
        briefing_run_id="private-run-id",
        briefing_path="/private/event-title-and-person-name.md",
        source_health=(("Google Calendar", "healthy"),),
        diagnostic_category="trial_policy_mismatch",
    )


def test_log_is_private_bounded_metadata_without_briefing_content(
    tmp_path: Path,
) -> None:
    path = tmp_path / "scheduled" / "diagnostic.jsonl"

    append_scheduled_run_diagnostic(
        path,
        report=_report(),
        recorded_at=datetime(2026, 8, 3, 14, 0, tzinfo=UTC),
        application_version="0.0.0+abcdef123456.clean",
    )

    raw = path.read_text(encoding="utf-8")
    event = json.loads(raw)
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert event == {
        "application_version": "0.0.0+abcdef123456.clean",
        "diagnostic_category": "trial_policy_mismatch",
        "eligibility_decision": "trial_policy_mismatch",
        "event": "scheduled_invocation",
        "notification_result": "delivery_failed",
        "occurrence_date": "2026-08-03",
        "outcome": "configuration_failure",
        "recorded_at": "2026-08-03T14:00:00+00:00",
        "source_health": {"Google Calendar": "healthy"},
        "trial_ordinal": None,
    }
    for prohibited in (
        "private-run-id",
        "event-title",
        "person-name",
        "briefing_path",
        "briefing_run_id",
    ):
        assert prohibited not in raw


def test_log_rejects_unapproved_source_aliases(tmp_path: Path) -> None:
    report = _report()
    unsafe = ScheduledExecutionReport(
        outcome=report.outcome,
        occurrence_date=report.occurrence_date,
        eligibility_decision=report.eligibility_decision,
        trial_ordinal=report.trial_ordinal,
        source_health=(("Private event title", "healthy"),),
        diagnostic_category=report.diagnostic_category,
    )

    with pytest.raises(ValueError, match="not safe to log"):
        append_scheduled_run_diagnostic(
            tmp_path / "diagnostic.jsonl",
            report=unsafe,
            recorded_at=datetime(2026, 8, 3, 14, 0, tzinfo=UTC),
            application_version="0.0.0+abcdef123456.clean",
        )


def test_early_policy_failure_is_written_even_without_an_occurrence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    diagnostic_path = tmp_path / "scheduled" / "diagnostic.jsonl"
    monkeypatch.setattr(
        "chief_of_staff.scheduled_cli.DIAGNOSTIC_LOG_PATH",
        diagnostic_path,
    )
    monkeypatch.setattr(
        "chief_of_staff.scheduled_cli.BRIEFING_LOCK_PATH",
        tmp_path / "briefing.lock",
    )
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        trial = create_trial(datetime(2026, 7, 31, 12, 0, tzinfo=UTC))
        store.save_scheduled_trial(
            replace(trial, application_version="different-reviewed-build")
        )

        exit_code = _run(store, MacOSKeychain())

        assert store.list_scheduled_occurrences(trial.id) == ()
    output = json.loads(capsys.readouterr().out)
    events = scheduled_diagnostic_snapshot(diagnostic_path)["events"]
    assert exit_code == 2
    assert output["diagnostic_log_result"] == "recorded"
    assert isinstance(events, list)
    assert events[-1]["diagnostic_category"] == "trial_policy_mismatch"


def test_log_rotates_to_exactly_two_bounded_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "scheduled" / "diagnostic.jsonl"
    monkeypatch.setattr(
        "chief_of_staff.scheduled_diagnostics.DIAGNOSTIC_MAXIMUM_FILE_BYTES",
        700,
    )

    for minute in range(12):
        append_scheduled_run_diagnostic(
            path,
            report=_report(),
            recorded_at=datetime(2026, 8, 3, 14, minute, tzinfo=UTC),
            application_version="0.0.0+abcdef123456.clean",
        )

    rotated = path.with_suffix(".jsonl.1")
    snapshot = scheduled_diagnostic_snapshot(path)
    assert path.is_file()
    assert rotated.is_file()
    assert path.stat().st_size <= 700
    assert rotated.stat().st_size <= 700
    assert not path.with_suffix(".jsonl.2").exists()
    assert snapshot["maximum_files"] == 2
    assert snapshot["private_content_included"] is False
