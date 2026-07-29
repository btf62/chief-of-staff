"""Tests for the supported on-demand briefing command surface."""

from __future__ import annotations

import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chief_of_staff.gmail_live_cli import (
    _exclusive_briefing_run,
    _print_briefing_success,
)
from chief_of_staff.gmail_mvp_trial import (
    GmailMvpTrialReport,
    GmailStreamTrialReport,
)

NOW = datetime(2026, 7, 29, tzinfo=UTC)


def _stream() -> GmailStreamTrialReport:
    return GmailStreamTrialReport(
        status="partial",
        retrieval_window_start=NOW,
        retrieval_window_end=NOW,
        messages_listed=1,
        pages=1,
        duplicate_message_ids=0,
        metadata_records_inspected=1,
        body_candidates=1,
        body_candidates_selected=1,
        body_candidates_omitted=0,
        body_fetches_attempted=1,
        body_records_retrieved=1,
        bodies_unavailable_or_unsupported=0,
        automated_bulk_exclusions=0,
        opaque_or_unsupported_messages=0,
    )


def _report(tmp_path: Path) -> GmailMvpTrialReport:
    return GmailMvpTrialReport(
        oauth_project_id="safe-project",
        oauth_application_owner="organization",
        account_confirmed=True,
        granted_scope="read-only",
        credential_health="healthy",
        refresh_health="healthy",
        inbound=_stream(),
        sent=_stream(),
        messages_listed=2,
        pages=2,
        metadata_records_inspected=2,
        direct_inbound_candidates=1,
        outbound_candidates=1,
        automated_bulk_exclusions=0,
        body_candidates_eligible=144,
        body_candidates_selected=120,
        body_candidates_omitted=24,
        body_fetches_attempted=117,
        body_records_retrieved=106,
        bodies_unavailable_or_unsupported=14,
        body_candidate_cap_caused_partial_coverage=True,
        extracted_content_limit_caused_partial_coverage=False,
        opaque_or_unsupported_messages=0,
        unique_threads=2,
        explicit_requests_detected=1,
        proposed_people_waiting=1,
        explicit_sent_commitments_detected=1,
        proposed_commitments_at_risk=0,
        records_persisted=2,
        records_displayed=1,
        gmail_coverage="partial",
        source_coverage=(("Work Gmail", "partial", 2),),
        review_path=tmp_path / "review.md",
        briefing_path=tmp_path / "briefing.md",
        briefing_word_count=500,
        displayed_sections=("People Waiting on Brad",),
        retrieval_attempts=1,
        failure_report_paths=(),
    )


def test_supported_briefing_output_is_concise_and_private_safe(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _report(tmp_path)

    _print_briefing_success(report)

    output = capsys.readouterr().out
    assert "Daily Briefing ready." in output
    assert f"Briefing: {report.briefing_path}" in output
    assert f"Private Gmail review: {report.review_path}" in output
    assert "120 of 144 eligible messages selected" in output
    assert "24 omitted without body retrieval" in output
    assert "All external sources remained read-only." in output
    assert "safe-project" not in output
    assert "read-only" not in output.removesuffix(
        "All external sources remained read-only.\n"
    )


def test_briefing_lock_prevents_overlapping_runs_and_is_private(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / ".local" / "briefing.lock"

    with _exclusive_briefing_run(lock_path):
        assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
        with (
            pytest.raises(BlockingIOError),
            _exclusive_briefing_run(lock_path),
        ):
            pass

    with _exclusive_briefing_run(lock_path):
        assert lock_path.exists()


def test_makefile_exposes_supported_briefing_target() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    makefile = (repository_root / "Makefile").read_text(encoding="utf-8")

    assert "briefing:" in makefile
    assert "-m chief_of_staff.gmail_live_cli briefing" in makefile
