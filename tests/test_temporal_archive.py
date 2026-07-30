"""Milestone 11 temporal, title-safety, and historical-lineage tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from chief_of_staff.archive import (
    HistoricalBriefingService,
    archive_pipeline_facts,
    deserialize_normalized_record,
    serialize_normalized_record,
)
from chief_of_staff.connectors import SourceCoverage, SourceItem, StaticConnector
from chief_of_staff.domain import (
    BriefingRun,
    BriefingStatus,
    Classification,
    Conclusion,
    ConclusionKind,
    ConnectorDomain,
    ConnectorRun,
    ConnectorStatus,
    CoverageStatus,
    SourceEvidence,
)
from chief_of_staff.persistence import Database, StateStore
from chief_of_staff.pipeline import (
    BriefingSectionName,
    DeterministicBriefingPipeline,
    HistoricalMode,
    NormalizedRecord,
    PipelineResult,
    Provenance,
    RecordKind,
    TemporalState,
    resolve_context,
    safe_source_title,
)
from chief_of_staff.web import presentation_from_plan

DAY = date(2026, 7, 30)
ZONE = "America/New_York"
LOCAL = timezone(timedelta(hours=-4))


def _source_item(
    item_id: str,
    *,
    start_hour: int,
    end_hour: int,
) -> SourceItem:
    start = datetime(2026, 7, 30, start_hour, tzinfo=LOCAL)
    end = datetime(2026, 7, 30, end_hour, tzinfo=LOCAL)
    return SourceItem(
        id=item_id,
        source_record_id=item_id,
        item_type="calendar_event",
        facts={
            "title": f"Synthetic event {item_id}",
            "status": "confirmed",
            "event_type": "default",
            "importance": 3,
            "explicit_commitment": True,
            "all_day": False,
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
        },
        retrieved_at=start - timedelta(days=1),
        freshness_at=start - timedelta(days=1),
        display_url=f"https://example.invalid/calendar/{item_id}",
    )


def _calendar_pipeline(as_of: datetime) -> PipelineResult:
    calendar = StaticConnector(
        source_name="google_calendar",
        approved_scope="synthetic read-only calendar",
        items=(
            _source_item("earlier", start_hour=9, end_hour=10),
            _source_item("current", start_hour=11, end_hour=12),
            _source_item("upcoming", start_hour=14, end_hour=15),
        ),
        status=CoverageStatus.COMPLETE,
    )
    context = resolve_context(
        run_id=f"temporal-{as_of.hour}",
        briefing_date=DAY,
        timezone=ZONE,
        generated_at=as_of,
        as_of=as_of,
    )
    return DeterministicBriefingPipeline().run(context, (calendar,))


def _normalized(
    title: str,
    *,
    source: str = "todoist",
    freshness_at: datetime | None = None,
) -> NormalizedRecord:
    fresh = freshness_at or datetime(2026, 7, 30, 12, tzinfo=UTC)
    return NormalizedRecord(
        id=f"{source}:{title}",
        kind=RecordKind.TASK,
        title=title,
        summary=None,
        status="open",
        event_type=None,
        importance=5,
        explicit_commitment=True,
        preparation=None,
        all_day=True,
        start_at=None,
        end_at=None,
        due_at=datetime(2026, 7, 30, tzinfo=UTC),
        provenance=Provenance(
            source=source,
            source_record_id=f"{source}-{title}",
            display_url=f"https://example.invalid/{source}/record",
            retrieved_at=fresh,
            freshness_at=fresh,
            connector_instance_id=f"{source}:primary",
            account_alias="Synthetic source",
            domain_classification=ConnectorDomain.WORK,
        ),
        source_updated_at=fresh,
        evidence_fingerprint=f"fingerprint-{source}-{title}",
    )


def _coverage(
    source: str = "todoist",
    status: CoverageStatus = CoverageStatus.COMPLETE,
) -> tuple[SourceCoverage, ...]:
    return (
        SourceCoverage(
            source=source,
            approved_scope="synthetic archived facts",
            status=status,
            retrieved_at=datetime(2026, 7, 30, 12, tzinfo=UTC),
            freshness_at=datetime(2026, 7, 30, 12, tzinfo=UTC),
            record_count=1,
        ),
    )


def _persist_recorded_result(
    store: StateStore,
    result: PipelineResult,
    *,
    run_id: str,
    generated_at: datetime,
    as_of: datetime,
) -> None:
    store.add_briefing_run(
        BriefingRun(
            id=run_id,
            briefing_date=DAY,
            timezone=ZONE,
            invocation_mode="synthetic_recorded_test",
            started_at=generated_at,
            completed_at=generated_at,
            status=BriefingStatus.SUCCEEDED,
            generated_at=generated_at,
            as_of=as_of,
            historical_mode=HistoricalMode.RECORDED.value,
        )
    )
    for ordinal, coverage in enumerate(result.plan.coverage):
        connector_run_id = f"{run_id}:coverage:{ordinal}"
        store.add_connector_run(
            ConnectorRun(
                id=connector_run_id,
                source=coverage.source,
                approved_scope=coverage.approved_scope,
                started_at=generated_at,
                completed_at=generated_at,
                status=ConnectorStatus.SUCCEEDED,
                coverage_status=coverage.status,
                freshness_at=coverage.freshness_at,
                record_count=coverage.record_count,
            )
        )
        store.link_connector_run(run_id, connector_run_id)
    store.save_briefing_presentation(
        presentation_from_plan(
            result.plan,
            briefing_run_id=run_id,
            created_at=generated_at,
            state_store=store,
        )
    )
    archive_pipeline_facts(
        store,
        briefing_run_id=run_id,
        result=result,
    )


def test_calendar_items_preserve_whole_day_with_written_temporal_states() -> None:
    result = _calendar_pipeline(datetime(2026, 7, 30, 11, 30, tzinfo=LOCAL))
    section = next(
        item
        for item in result.plan.sections
        if item.name is BriefingSectionName.TODAYS_CALENDAR
    )

    assert tuple(item.temporal_state for item in section.items) == (
        TemporalState.EARLIER_TODAY,
        TemporalState.IN_PROGRESS,
        TemporalState.UPCOMING,
    )
    assert all(item.headline in result.rendered.text for item in section.items)
    assert "Earlier today · Synthetic event earlier" in result.rendered.text
    assert "In progress · Synthetic event current" in result.rendered.text
    assert "Upcoming · Synthetic event upcoming" in result.rendered.text
    assert "Generated Thursday, July 30 at 11:30 a.m." in result.rendered.text


@pytest.mark.parametrize(
    ("as_of", "expected"),
    (
        (datetime(2026, 7, 30, 7, tzinfo=LOCAL), TemporalState.UPCOMING),
        (datetime(2026, 7, 30, 8, 55, tzinfo=LOCAL), TemporalState.IN_PROGRESS),
        (datetime(2026, 7, 30, 9, 45, tzinfo=LOCAL), TemporalState.EARLIER_TODAY),
    ),
)
def test_whole_day_focus_window_is_not_replaced_after_elapsed(
    as_of: datetime,
    expected: TemporalState,
) -> None:
    calendar = StaticConnector(
        source_name="google_calendar",
        approved_scope="synthetic calendar",
        items=(_source_item("fixed", start_hour=10, end_hour=11),),
        status=CoverageStatus.COMPLETE,
    )
    task = StaticConnector(
        source_name="todoist",
        approved_scope="synthetic tasks",
        items=(
            SourceItem(
                id="priority",
                source_record_id="priority",
                item_type="task",
                facts={
                    "title": "Synthetic focus objective",
                    "status": "open",
                    "importance": 5,
                    "explicit_commitment": True,
                    "all_day": True,
                    "due_at": "2026-07-30T00:00:00-04:00",
                    "provider_priority": 4,
                },
                retrieved_at=as_of - timedelta(days=1),
                freshness_at=as_of - timedelta(days=1),
                display_url="https://example.invalid/task/priority",
            ),
        ),
        status=CoverageStatus.COMPLETE,
    )
    context = resolve_context(
        run_id=f"focus-{as_of.hour}-{as_of.minute}",
        briefing_date=DAY,
        timezone=ZONE,
        generated_at=as_of,
        as_of=as_of,
    )

    result = DeterministicBriefingPipeline().run(context, (calendar, task))
    focus = next(
        section
        for section in result.plan.sections
        if section.name is BriefingSectionName.RECOMMENDED_FOCUS_BLOCK
    ).items[0]

    assert focus.headline.startswith("8:00\N{EN DASH}9:30 a.m.")
    assert focus.temporal_state is expected
    if expected is TemporalState.IN_PROGRESS:
        assert "approximately 35 minutes remained" in focus.detail
    if expected is TemporalState.EARLIER_TODAY:
        assert "elapsed before this briefing was generated" in focus.detail


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("Review [draft] notes", "Review [draft] notes"),
        (
            "Fix [northridgeleaders.com](https://northridgeleaders.com) billing",
            "Fix northridgeleaders.com billing",
        ),
        (
            "[Fix [nested] label](https://example.invalid)",
            "Fix [nested] label",
        ),
        (
            "Keep [malformed](https://example.invalid",
            "Keep [malformed](https://example.invalid",
        ),
        ("[unsafe](javascript:alert(1))", "unsafe"),
    ),
)
def test_source_title_markdown_like_text_is_readable_not_interpreted(
    raw: str,
    expected: str,
) -> None:
    assert safe_source_title(raw) == expected


def test_source_title_neutralizes_html_scripts_and_bounds_length() -> None:
    cleaned = safe_source_title("<script>alert('x')</script>" + "x" * 600)

    assert "<" not in cleaned
    assert ">" not in cleaned
    assert len(cleaned) == 500
    assert cleaned.endswith("…")


def test_normalized_fact_archive_round_trips_without_provider_payload() -> None:
    record = _normalized("Archived task")

    serialized = serialize_normalized_record(record)
    restored = deserialize_normalized_record(serialized)

    assert restored == record
    assert "access_token" not in serialized
    assert "raw_payload" not in serialized
    assert "mime" not in serialized.casefold()


def test_two_recorded_runs_replay_lineage_and_synthetic_separation(
    tmp_path: Path,
) -> None:
    generated = datetime(2026, 7, 31, 13, tzinfo=UTC)
    as_of = datetime(2026, 7, 30, 14, tzinfo=UTC)
    with Database.open(tmp_path / "history.sqlite3") as database:
        store = StateStore(database)
        service = HistoricalBriefingService(store)
        first = service.synthetic(
            records=(_normalized("First archived task"),),
            coverage=_coverage(),
            briefing_date=DAY,
            timezone=ZONE,
            generated_at=generated,
            as_of=as_of,
        )
        second = service.synthetic(
            records=(_normalized("Second archived task"),),
            coverage=_coverage(),
            briefing_date=DAY,
            timezone=ZONE,
            generated_at=generated + timedelta(minutes=5),
            as_of=as_of,
        )
        assert first.result is not None
        assert second.result is not None
        _persist_recorded_result(
            store,
            first.result,
            run_id="recorded-first",
            generated_at=generated,
            as_of=as_of,
        )
        _persist_recorded_result(
            store,
            second.result,
            run_id="recorded-second",
            generated_at=generated + timedelta(minutes=5),
            as_of=as_of,
        )
        recorded = service.recorded_for_date(DAY)
        assert len(recorded) == 2
        assert all(
            item.run.historical_mode == HistoricalMode.RECORDED.value
            for item in recorded
        )

        replay = service.replay(
            "recorded-first",
            generated_at=generated + timedelta(days=1),
        )
        assert replay.result is not None
        assert replay.run_id is not None
        replay_state = store.get_briefing_presentation(replay.run_id)
        assert replay_state is not None
        assert replay_state.run.historical_mode == HistoricalMode.REPLAY.value
        assert replay_state.run.originating_recorded_run_id == "recorded-first"
        assert "not the briefing originally shown" in replay.result.rendered.text
        assert store.get_briefing_presentation("recorded-first") is not None

        before_synthetic = store.inspect_state().briefing_runs
        synthetic = service.synthetic(
            records=(_normalized("Synthetic-only task", source="synthetic"),),
            coverage=_coverage("synthetic"),
            briefing_date=DAY,
            timezone=ZONE,
            generated_at=generated,
            as_of=as_of,
        )
        assert synthetic.result is not None
        assert synthetic.run_id is None
        assert store.inspect_state().briefing_runs == before_synthetic


def test_reconstruction_prevents_future_information_leakage_and_can_refuse(
    tmp_path: Path,
) -> None:
    as_of = datetime(2026, 7, 30, 14, tzinfo=UTC)
    before = _normalized(
        "Known before as-of",
        source="gmail",
        freshness_at=as_of - timedelta(minutes=5),
    )
    after = _normalized(
        "Arrived after as-of",
        source="gmail",
        freshness_at=as_of + timedelta(minutes=5),
    )
    with Database.open(tmp_path / "reconstruction.sqlite3") as database:
        service = HistoricalBriefingService(StateStore(database))
        reconstruction = service.reconstruct(
            records=(before, after),
            coverage=_coverage("gmail"),
            briefing_date=DAY,
            timezone=ZONE,
            generated_at=as_of + timedelta(days=1),
            as_of=as_of,
        )

        assert reconstruction.result is not None
        assert "Known before as-of" in reconstruction.result.rendered.text
        assert "Arrived after as-of" not in reconstruction.result.rendered.text
        assert reconstruction.result.plan.coverage[0].status is CoverageStatus.PARTIAL
        assert "Reconstructed on" in reconstruction.result.rendered.text

        unavailable = service.reconstruct(
            records=(),
            coverage=(),
            briefing_date=DAY,
            timezone=ZONE,
            generated_at=as_of + timedelta(days=1),
            as_of=as_of,
        )
        assert unavailable.result is None
        assert unavailable.run_id is None
        assert "No reliable historical briefing" in unavailable.disclosure


def test_recorded_presentation_is_immutable_and_deletion_removes_replay_fact(
    tmp_path: Path,
) -> None:
    generated = datetime(2026, 7, 31, 13, tzinfo=UTC)
    as_of = datetime(2026, 7, 30, 14, tzinfo=UTC)
    record = _normalized("Delete archived task")
    with Database.open(tmp_path / "archive-deletion.sqlite3") as database:
        store = StateStore(database)
        generated_result = HistoricalBriefingService(store).reconstruct(
            records=(record,),
            coverage=_coverage(),
            briefing_date=DAY,
            timezone=ZONE,
            generated_at=generated,
            as_of=as_of,
        )
        assert generated_result.run_id is not None
        presentation = store.get_briefing_presentation(generated_result.run_id)
        assert presentation is not None
        with pytest.raises(sqlite3.IntegrityError):
            store.save_briefing_presentation(presentation.presentation)

        evidence_id = "archived-delete-evidence"
        store.add_source_evidence(
            SourceEvidence(
                id=evidence_id,
                connector_run_id=None,
                source=record.provenance.source,
                source_record_id=record.provenance.source_record_id,
                evidence_fingerprint=record.evidence_fingerprint or "missing",
                retrieved_at=generated,
            )
        )
        store.add_conclusion(
            Conclusion(
                id="archived-delete-conclusion",
                kind=ConclusionKind.COMMITMENT,
                classification=Classification.EXPLICIT,
                statement=record.title,
                explanation="Synthetic archived deletion evidence.",
                confidence=1.0,
                evidence_fingerprint=record.evidence_fingerprint or "missing",
                processing_version="synthetic-v1",
                created_at=generated,
                evidence_ids=(evidence_id,),
            )
        )
        assert store.inspect_state().briefing_archived_facts == 1

        deleted = store.delete_local_conclusion(
            conclusion_id="archived-delete-conclusion",
            expected_version=0,
            idempotency_key="archive-delete-idempotency-key",
            deleted_at=generated + timedelta(minutes=1),
        )

        assert deleted
        assert store.inspect_state().briefing_archived_facts == 0
        assert (
            store.recurrence_decision(
                record.evidence_fingerprint or "missing"
            ).action.value
            == "suppress"
        )
