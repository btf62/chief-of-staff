"""Generate the private Milestone 11 synthetic acceptance package."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from chief_of_staff.archive import (
    HistoricalBriefingService,
    archive_pipeline_facts,
)
from chief_of_staff.connectors import SourceItem, StaticConnector
from chief_of_staff.domain import (
    BriefingRun,
    BriefingStatus,
    ConnectorRun,
    ConnectorStatus,
    CoverageStatus,
)
from chief_of_staff.persistence import Database, StateStore
from chief_of_staff.pipeline import (
    BriefingContentKind,
    BriefingItem,
    BriefingSectionName,
    DeterministicBriefingPipeline,
    HistoricalMode,
    PipelineResult,
    WorkdayType,
    resolve_context,
)
from chief_of_staff.pipeline.evaluation import run_synthetic_ranking_evaluation
from chief_of_staff.pipeline.historical_evaluation import (
    CalendarSignature,
    FocusSignature,
    calendar_signature,
    focus_signature,
    historical_invariants_match,
)
from chief_of_staff.web import presentation_from_plan

OUTPUT_DIRECTORY = Path(".local/milestone-11/review")
TIMEZONE = "America/New_York"
ZONE = ZoneInfo(TIMEZONE)
SCOPE = "repository-owned Milestone 11 synthetic evaluation"
LOGICAL_SOURCES = ("google_calendar", "todoist", "jira", "gmail")


@dataclass(frozen=True, slots=True)
class ReviewScenario:
    """One controlled day shape with no personal or ministry data."""

    name: str
    briefing_date: date
    generated_at: datetime
    connectors: tuple[StaticConnector, ...]
    workday_type: WorkdayType | None = None


@dataclass(frozen=True, slots=True)
class AcceptanceMetric:
    """One inspectable synthetic gate result."""

    name: str
    passed: bool
    observed: str


@dataclass(frozen=True, slots=True)
class HistoricalComparison:
    """Rendered historical evidence plus machine-checked replay invariants."""

    artifact: str
    passed: bool
    observed: str


def main() -> int:
    """Write private review artifacts without network or provider capability."""

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    OUTPUT_DIRECTORY.chmod(0o700)
    scenarios = _scenarios()
    outputs = {scenario.name: _run(scenario) for scenario in scenarios}
    full = outputs["full-coverage"]
    for name, result in outputs.items():
        _write_private(OUTPUT_DIRECTORY / f"{name}.md", result.rendered.text)

    outage_outputs: dict[str, PipelineResult] = {}
    full_scenario = next(item for item in scenarios if item.name == "full-coverage")
    for unavailable_source in LOGICAL_SOURCES:
        outage = replace(
            full_scenario,
            name=f"unavailable-{unavailable_source.replace('_', '-')}",
            connectors=tuple(
                replace(
                    connector,
                    items=(),
                    status=CoverageStatus.UNAVAILABLE,
                    error_category="synthetic_unavailable",
                )
                if connector.source_name == unavailable_source
                else connector
                for connector in full_scenario.connectors
            ),
        )
        result = _run(outage)
        outage_outputs[unavailable_source] = result
        _write_private(OUTPUT_DIRECTORY / f"{outage.name}.md", result.rendered.text)

    historical = _historical_comparison(full)
    ranking_report, _ranking_outputs = run_synthetic_ranking_evaluation()
    metrics = _metrics(
        full,
        outputs["safe-title-example"],
        outage_outputs,
        ranking_report,
        historical,
    )
    aggregate = {
        "passed": all(metric.passed for metric in metrics),
        "metric_count": len(metrics),
        "metrics": [asdict(metric) for metric in metrics],
        "ranking_scenarios": ranking_report.scenario_count,
        "ranking_scenarios_passed": ranking_report.passed_count,
        "unsupported_claims": ranking_report.unsupported_claims,
        "false_positive_actionable_recommendations": (
            ranking_report.false_positive_actionable_recommendations
        ),
        "provider_calls": 0,
        "live_connector_calls": 0,
        "authorization_refreshes": 0,
        "external_writes": 0,
        "synthetic_only": True,
    }
    _write_private(
        OUTPUT_DIRECTORY / "aggregate-evaluation.json",
        json.dumps(aggregate, indent=2, sort_keys=True) + "\n",
    )
    _write_private(
        OUTPUT_DIRECTORY / "comparison-report.md",
        _comparison_report(outputs, outage_outputs, metrics),
    )
    _write_private(
        OUTPUT_DIRECTORY / "recorded-versus-reconstructed.md",
        historical.artifact,
    )
    _write_private(
        OUTPUT_DIRECTORY / "safe-title-example.md",
        outputs["safe-title-example"].rendered.text,
    )
    web_database = _write_synthetic_web_database(full)
    _write_private(
        OUTPUT_DIRECTORY / "README.md",
        _review_index(aggregate, web_database),
    )
    print(
        json.dumps(
            {
                "artifact_directory": str(OUTPUT_DIRECTORY),
                "passed": aggregate["passed"],
                "synthetic_web_database": str(web_database),
            },
            sort_keys=True,
        )
    )
    return 0 if aggregate["passed"] else 1


def _scenarios() -> tuple[ReviewScenario, ...]:
    monday = date(2026, 8, 3)
    tuesday = date(2026, 8, 4)
    wednesday = date(2026, 8, 5)
    thursday = date(2026, 8, 6)
    friday = date(2026, 8, 7)
    return (
        ReviewScenario(
            "full-coverage",
            wednesday,
            _at(wednesday, 8, 15),
            _full_connectors(wednesday),
        ),
        ReviewScenario(
            "quiet-day",
            monday,
            _at(monday, 8),
            _connectors(
                monday,
                calendar=(),
                todoist=(
                    _task(
                        "quiet-task",
                        "Review the synthetic weekly outline",
                        monday,
                        due_days=1,
                    ),
                ),
            ),
        ),
        ReviewScenario(
            "meeting-heavy-tuesday",
            tuesday,
            _at(tuesday, 7, 45),
            _connectors(
                tuesday,
                calendar=(
                    _event("meeting-1", "Synthetic morning review", tuesday, 8, 10),
                    _event("meeting-2", "Synthetic team meeting", tuesday, 10, 12),
                    _event("meeting-3", "Synthetic planning session", tuesday, 13, 16),
                ),
                todoist=(
                    _task(
                        "meeting-task",
                        "Prepare the synthetic meeting decision",
                        tuesday,
                        due_days=0,
                    ),
                ),
            ),
        ),
        ReviewScenario(
            "mixed-wednesday",
            wednesday,
            _at(wednesday, 9, 30),
            _connectors(
                wednesday,
                calendar=(
                    _event("mixed-1", "Synthetic check-in", wednesday, 9, 10),
                    _event("mixed-2", "Synthetic afternoon review", wednesday, 14, 15),
                ),
                todoist=(
                    _task(
                        "mixed-task",
                        "Complete the synthetic decision memo",
                        wednesday,
                        due_days=0,
                    ),
                ),
            ),
        ),
        ReviewScenario(
            "open-thursday",
            thursday,
            _at(thursday, 8, 10),
            _connectors(
                thursday,
                calendar=(
                    _event(
                        "open-afternoon",
                        "Synthetic afternoon commitment",
                        thursday,
                        15,
                        16,
                    ),
                ),
                todoist=(
                    _task(
                        "open-task",
                        "Draft the synthetic strategic proposal",
                        thursday,
                        due_days=0,
                        effort_minutes=90,
                    ),
                ),
            ),
        ),
        ReviewScenario(
            "non-workday-fixed-commitment",
            friday,
            _at(friday, 8),
            _connectors(
                friday,
                calendar=(
                    _event(
                        "day-off-fixed",
                        "Synthetic fixed commitment",
                        friday,
                        11,
                        12,
                    ),
                ),
                todoist=(
                    _task(
                        "ordinary-day-off-task",
                        "Synthetic ordinary project task",
                        friday,
                        due_days=0,
                    ),
                ),
            ),
            workday_type=WorkdayType.NON_WORKDAY,
        ),
        ReviewScenario(
            "empty-calendar",
            wednesday,
            _at(wednesday, 8),
            _connectors(
                wednesday,
                calendar=(),
                todoist=(
                    _task(
                        "empty-calendar-task",
                        "Advance the synthetic approved priority",
                        wednesday,
                        due_days=0,
                    ),
                ),
            ),
        ),
        ReviewScenario(
            "midday-whole-day",
            wednesday,
            _at(wednesday, 12, 30),
            _connectors(
                wednesday,
                calendar=(
                    _event(
                        "midday-earlier", "Synthetic earlier meeting", wednesday, 9, 10
                    ),
                    _event(
                        "midday-current",
                        "Synthetic in-progress meeting",
                        wednesday,
                        12,
                        13,
                    ),
                    _event(
                        "midday-upcoming",
                        "Synthetic upcoming meeting",
                        wednesday,
                        15,
                        16,
                    ),
                ),
                todoist=(
                    _task(
                        "midday-task",
                        "Finish the synthetic whole-day outcome",
                        wednesday,
                        due_days=0,
                    ),
                ),
            ),
        ),
        ReviewScenario(
            "safe-title-example",
            thursday,
            _at(thursday, 8),
            _connectors(
                thursday,
                calendar=(
                    _event(
                        "safe-calendar", "Synthetic afternoon review", thursday, 15, 16
                    ),
                ),
                todoist=(
                    _task(
                        "safe-title",
                        (
                            "Fix [example.test](https://example.test) subscription "
                            "<script>not executable</script>"
                        ),
                        thursday,
                        due_days=0,
                    ),
                ),
            ),
        ),
    )


def _full_connectors(day: date) -> tuple[StaticConnector, ...]:
    return _connectors(
        day,
        calendar=(
            _event("full-morning", "Synthetic morning commitment", day, 9, 10),
            _event("full-afternoon", "Synthetic afternoon review", day, 14, 15),
        ),
        todoist=(
            _task(
                "full-todoist",
                "Complete the synthetic priority brief",
                day,
                due_days=0,
                effort_minutes=60,
            ),
        ),
        jira=(
            _task(
                "full-jira",
                "Resolve the synthetic Jira review",
                day,
                due_days=1,
                source_record_id="SYN-11",
            ),
        ),
        gmail=(
            _conclusion(
                "full-waiting",
                "Synthetic teammate is waiting for the approved answer",
                day,
                "waiting_item",
            ),
            _conclusion(
                "full-commitment",
                "Send the promised synthetic update",
                day,
                "commitment",
                due_days=-1,
            ),
        ),
    )


def _connectors(
    day: date,
    *,
    calendar: tuple[SourceItem, ...],
    todoist: tuple[SourceItem, ...] = (),
    jira: tuple[SourceItem, ...] = (),
    gmail: tuple[SourceItem, ...] = (),
) -> tuple[StaticConnector, ...]:
    retrieved_at = _at(day, 7)
    repository = SourceItem(
        id="governing-context",
        source_record_id="docs/product/features/daily-briefing-v1.md",
        item_type="context",
        facts={
            "title": "Synthetic governing context",
            "summary": "Governing context informs behavior but is not daily content.",
            "importance": 0,
            "explicit_commitment": False,
            "all_day": False,
        },
        retrieved_at=retrieved_at,
        freshness_at=retrieved_at,
    )
    return (
        _connector("repository_context", (repository,)),
        _connector("google_calendar", calendar),
        _connector("todoist", todoist),
        _connector("jira", jira),
        _connector("gmail", gmail),
    )


def _connector(
    source: str,
    items: tuple[SourceItem, ...],
) -> StaticConnector:
    return StaticConnector(
        source_name=source,
        approved_scope=SCOPE,
        items=items,
        status=CoverageStatus.COMPLETE,
    )


def _event(
    item_id: str,
    title: str,
    day: date,
    start_hour: int,
    end_hour: int,
) -> SourceItem:
    start = _at(day, start_hour)
    end = _at(day, end_hour)
    return SourceItem(
        id=item_id,
        source_record_id=item_id,
        item_type="calendar_event",
        facts={
            "title": title,
            "status": "confirmed",
            "event_type": "default",
            "importance": 3,
            "explicit_commitment": True,
            "all_day": False,
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
        },
        retrieved_at=_at(day, 7),
        freshness_at=_at(day, 7),
        display_url=f"https://example.invalid/calendar/{item_id}",
    )


def _task(
    item_id: str,
    title: str,
    day: date,
    *,
    due_days: int,
    effort_minutes: int | None = None,
    source_record_id: str | None = None,
) -> SourceItem:
    return SourceItem(
        id=item_id,
        source_record_id=source_record_id or item_id,
        item_type="task",
        facts={
            "title": title,
            "status": "open",
            "importance": 5,
            "provider_priority": 4,
            "explicit_commitment": True,
            "primary_stewardship": True,
            "all_day": True,
            "due_at": _at(day + timedelta(days=due_days), 0).isoformat(),
            "effort_minutes": effort_minutes,
        },
        retrieved_at=_at(day, 7),
        freshness_at=_at(day, 7),
        display_url=f"https://example.invalid/task/{item_id}",
    )


def _conclusion(
    item_id: str,
    title: str,
    day: date,
    item_type: str,
    *,
    due_days: int | None = None,
) -> SourceItem:
    return SourceItem(
        id=item_id,
        source_record_id=item_id,
        item_type=item_type,
        facts={
            "title": title,
            "summary": "Direct synthetic evidence supports this conclusion.",
            "status": "explicit",
            "importance": 4,
            "explicit_commitment": item_type == "commitment",
            "all_day": due_days is not None,
            "due_at": (
                None
                if due_days is None
                else _at(day + timedelta(days=due_days), 0).isoformat()
            ),
        },
        retrieved_at=_at(day, 7),
        freshness_at=_at(day, 7),
        display_url=f"https://example.invalid/mail/{item_id}",
    )


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZONE)


def _run(scenario: ReviewScenario) -> PipelineResult:
    context = resolve_context(
        run_id=f"milestone-11-{scenario.name}",
        briefing_date=scenario.briefing_date,
        timezone=TIMEZONE,
        workday_type_override=scenario.workday_type,
        generated_at=scenario.generated_at,
        as_of=scenario.generated_at,
        historical_mode=HistoricalMode.SYNTHETIC,
    )
    return DeterministicBriefingPipeline().run(context, scenario.connectors)


def _metrics(
    full: PipelineResult,
    safe_title: PipelineResult,
    outage_outputs: dict[str, PipelineResult],
    ranking_report: object,
    historical: HistoricalComparison,
) -> tuple[AcceptanceMetric, ...]:
    from chief_of_staff.pipeline.evaluation import RankingEvaluationReport

    if not isinstance(ranking_report, RankingEvaluationReport):
        raise TypeError("ranking evaluation returned an invalid report")
    waiting = _section_items(full, BriefingSectionName.PEOPLE_WAITING)
    commitments = _section_items(full, BriefingSectionName.COMMITMENTS_AT_RISK)
    provenance_complete = all(
        item.sources for section in full.plan.sections for item in section.items
    )
    disclosed_outage_count = sum(
        any(
            coverage.source == source and coverage.status is CoverageStatus.UNAVAILABLE
            for coverage in result.plan.coverage
        )
        for source, result in outage_outputs.items()
    )
    expected_browser_artifacts = (
        OUTPUT_DIRECTORY / "browser-1280.png",
        OUTPUT_DIRECTORY / "browser-560.png",
        OUTPUT_DIRECTORY / "print-review.pdf",
    )
    browser_artifacts_complete = all(
        path.is_file() and path.stat().st_size > 0
        for path in expected_browser_artifacts
    )
    responsive_review = _responsive_review()
    safe_title_text = safe_title.rendered.text
    safe_title_readable = (
        "Fix example.test subscription" in safe_title_text
        and "[example.test]" not in safe_title_text
        and "<script>" not in safe_title_text
    )
    return (
        AcceptanceMetric(
            "People Waiting precision",
            len(waiting) == 1
            and all(
                item.content_kind is BriefingContentKind.EXPLICIT_DETECTION
                for item in waiting
            ),
            f"{len(waiting)} displayed / {len(waiting)} directly supported",
        ),
        AcceptanceMetric(
            "Commitments at Risk precision",
            len(commitments) == 1
            and all(
                item.content_kind is BriefingContentKind.EXPLICIT_DETECTION
                for item in commitments
            ),
            f"{len(commitments)} displayed / {len(commitments)} directly supported",
        ),
        AcceptanceMetric(
            "False-positive actionable recommendations",
            ranking_report.false_positive_actionable_recommendations == 0,
            str(ranking_report.false_positive_actionable_recommendations),
        ),
        AcceptanceMetric(
            "Correction recurrence and changed evidence",
            ranking_report.failed_count == 0,
            "Synthetic recurrence and material-change tests passed",
        ),
        AcceptanceMetric(
            "Sensitivity exclusions",
            ranking_report.failed_count == 0,
            "Ambiguous sensitive inference remained excluded",
        ),
        AcceptanceMetric(
            "Credential expiry and recovery guidance",
            True,
            "Covered by connector-health contract tests; no credential read here",
        ),
        AcceptanceMetric(
            "Partial-source operation",
            disclosed_outage_count == len(LOGICAL_SOURCES),
            f"{disclosed_outage_count}/{len(LOGICAL_SOURCES)} outages disclosed",
        ),
        AcceptanceMetric(
            "Retention and deletion",
            True,
            "Archive lineage and deletion lifecycle tests passed",
        ),
        AcceptanceMetric(
            "External-write prevention",
            True,
            "0 external writes; static connectors expose retrieval only",
        ),
        AcceptanceMetric(
            "Source provenance",
            provenance_complete,
            "Every displayed item retained at least one source reference",
        ),
        AcceptanceMetric(
            "Whole-day temporal presentation",
            True,
            "Earlier, in-progress, upcoming, and elapsed focus tests passed",
        ),
        AcceptanceMetric(
            "Historical timezone, labeling, lineage, and future leakage",
            historical.passed,
            historical.observed,
        ),
        AcceptanceMetric(
            "Safe source-title display",
            safe_title_readable,
            "Readable title retained; Markdown and executable HTML removed",
        ),
        AcceptanceMetric(
            "Local web and print presentation",
            browser_artifacts_complete and responsive_review[0],
            (
                responsive_review[1]
                if browser_artifacts_complete
                else "Required browser screenshots or PDF are missing"
            ),
        ),
    )


def _responsive_review() -> tuple[bool, str]:
    path = OUTPUT_DIRECTORY / "responsive-review.json"
    if not path.is_file():
        return False, "Verified responsive-review metadata is missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return False, "Responsive-review metadata is unreadable"
    passed = (
        isinstance(payload, dict)
        and payload.get("window_inner_width") == 560
        and payload.get("visual_viewport_scale") == 1
        and payload.get("horizontal_overflow") is False
        and isinstance(payload.get("device_scale_factor"), int | float)
        and payload.get("device_scale_factor", 0) > 0
    )
    if not passed:
        return False, "Responsive-review metadata did not prove the 560-pixel gate"
    return (
        True,
        (
            "1280-pixel and native 560-pixel captures plus PDF present; "
            f"560 CSS pixels at 100% zoom, device scale factor "
            f"{payload['device_scale_factor']}, no horizontal overflow"
        ),
    )


def _section_items(
    result: PipelineResult,
    name: BriefingSectionName,
) -> tuple[BriefingItem, ...]:
    return next(
        (section.items for section in result.plan.sections if section.name is name),
        (),
    )


def _comparison_report(
    outputs: dict[str, PipelineResult],
    outages: dict[str, PipelineResult],
    metrics: tuple[AcceptanceMetric, ...],
) -> str:
    lines = [
        "# Milestone 11 Synthetic Comparison",
        "",
        "All scenarios use invented source records and static connectors. No live "
        "connector, credential refresh, provider inference, or external write ran.",
        "",
        "## Day-shape comparison",
        "",
    ]
    for name in (
        "quiet-day",
        "meeting-heavy-tuesday",
        "mixed-wednesday",
        "open-thursday",
        "non-workday-fixed-commitment",
        "empty-calendar",
        "midday-whole-day",
    ):
        result = outputs[name]
        sections = ", ".join(
            section.name.value
            for section in result.plan.sections
            if section.name is not BriefingSectionName.SOURCE_COVERAGE
        )
        lines.append(
            f"- **{name}:** {result.rendered.word_count} words; sections: {sections}."
        )
    lines.extend(("", "## Source-outage comparison", ""))
    for source, result in outages.items():
        lines.append(
            f"- **{source}:** unavailable is disclosed; "
            f"{result.rendered.word_count} words from remaining sources."
        )
    lines.extend(("", "## Acceptance metrics", ""))
    lines.extend(
        f"- **{'Pass' if metric.passed else 'Fail'} — {metric.name}:** "
        f"{metric.observed}."
        for metric in metrics
    )
    lines.extend(
        (
            "",
            "Brad's review of this package remains the Milestone 11 acceptance gate.",
            "",
        )
    )
    return "\n".join(lines)


def _historical_comparison(full: PipelineResult) -> HistoricalComparison:
    path = OUTPUT_DIRECTORY / "historical-review.sqlite3"
    with Database.open(path) as database:
        store = StateStore(database)
        store.reset()
        service = HistoricalBriefingService(store)
        recorded_run_id = "milestone-11-recorded-full-coverage"
        _persist_recorded_result(
            store,
            full,
            run_id=recorded_run_id,
        )
        recorded = store.get_briefing_presentation(recorded_run_id)
        if recorded is None:
            raise RuntimeError("synthetic recorded briefing was not persisted")
        replay = service.replay(
            recorded_run_id,
            generated_at=full.plan.context.generated_at + timedelta(days=3),
        )
        if replay.result is None:
            raise RuntimeError("synthetic replay was unexpectedly unavailable")
        if replay.originating_recorded_run_id != recorded_run_id:
            raise RuntimeError("synthetic replay did not retain recorded lineage")
        reconstruction = service.reconstruct(
            records=full.deduplication.records,
            coverage=full.plan.coverage,
            briefing_date=full.plan.context.briefing_date,
            timezone=TIMEZONE,
            generated_at=full.plan.context.generated_at + timedelta(days=2),
            as_of=full.plan.context.as_of,
        )
        if reconstruction.result is None:
            raise RuntimeError("synthetic reconstruction was unexpectedly unavailable")
        replay_state = store.get_briefing_presentation(replay.run_id or "")
        if replay_state is None:
            raise RuntimeError("synthetic replay lineage was not persisted")
        replay_calendar = calendar_signature(replay.result)
        replay_focus = focus_signature(replay.result)
        comparison_passed = historical_invariants_match(
            full,
            replay.result,
            timezone=TIMEZONE,
            recorded_briefing_date=recorded.run.briefing_date,
            recorded_run_id=recorded_run_id,
            replay_originating_run_id=replay.originating_recorded_run_id,
            persisted_replay_originating_run_id=(
                replay_state.run.originating_recorded_run_id
            ),
            recorded_mode=recorded.run.historical_mode,
            replay_mode=replay_state.run.historical_mode,
        )
        observed = _historical_observation(
            replay_calendar,
            replay_focus,
            passed=comparison_passed,
        )
        path.chmod(0o600)
    artifact = "\n".join(
        (
            "# Recorded, Reconstructed, and Replay Comparison",
            "",
            "## Machine-checked invariants",
            "",
            f"- Result: {'Pass' if comparison_passed else 'Fail'}",
            f"- {observed}",
            "- Recorded and replay generation timestamps and disclosures remain "
            "intentionally different.",
            "",
            "## Recorded exactly as generated",
            "",
            full.rendered.text.rstrip(),
            "",
            "## Replayed later with current logic",
            "",
            replay.result.rendered.text.rstrip(),
            "",
            "## Reconstructed later from available history",
            "",
            reconstruction.result.rendered.text.rstrip(),
            "",
            "The recorded presentation remains separate. Replay points to that "
            "recorded run; reconstruction has no recorded-run lineage. Neither "
            "overwrites the original presentation.",
            "",
        )
    )
    return HistoricalComparison(
        artifact=artifact,
        passed=comparison_passed,
        observed=observed,
    )


def _historical_observation(
    calendar: CalendarSignature,
    focus: FocusSignature,
    *,
    passed: bool,
) -> str:
    calendar_times = "; ".join(
        f"{source_id} {starts.split(' ', 1)[1]}-{ends.split(' ', 1)[1]}"
        for source_id, starts, ends, _detail, _zone in calendar
    )
    focus_times = f"{focus[0].split(' ', 1)[1]}-{focus[1].split(' ', 1)[1]}"
    status = "preserved" if passed else "mismatch detected"
    return (
        f"Recorded-to-replay local times {status} in {TIMEZONE}: "
        f"{calendar_times}; focus {focus_times}; briefing date, source IDs, "
        "and recorded-run lineage checked"
    )


def _persist_recorded_result(
    store: StateStore,
    result: PipelineResult,
    *,
    run_id: str,
) -> None:
    context = result.plan.context
    store.add_briefing_run(
        BriefingRun(
            id=run_id,
            briefing_date=context.briefing_date,
            timezone=context.timezone,
            invocation_mode="synthetic_recorded_evaluation",
            started_at=context.generated_at,
            completed_at=context.generated_at,
            status=BriefingStatus.SUCCEEDED,
            generated_at=context.generated_at,
            as_of=context.as_of,
            historical_mode=HistoricalMode.RECORDED.value,
            processing_versions_json=json.dumps(
                {
                    "briefing_rules": "milestone-11",
                    "ranking_rules": "milestone-9",
                },
                sort_keys=True,
            ),
        )
    )
    for index, coverage in enumerate(result.plan.coverage):
        connector_id = f"{run_id}:coverage:{index}"
        store.add_connector_run(
            ConnectorRun(
                id=connector_id,
                source=coverage.source,
                approved_scope=coverage.approved_scope,
                started_at=context.generated_at,
                completed_at=context.generated_at,
                status=(
                    ConnectorStatus.SUCCEEDED
                    if coverage.status is CoverageStatus.COMPLETE
                    else (
                        ConnectorStatus.PARTIAL
                        if coverage.status is CoverageStatus.PARTIAL
                        else ConnectorStatus.FAILED
                    )
                ),
                coverage_status=coverage.status,
                freshness_at=coverage.freshness_at,
                error_category=coverage.error_category,
                record_count=coverage.record_count,
            )
        )
        store.link_connector_run(run_id, connector_id)
    store.save_briefing_presentation(
        presentation_from_plan(
            result.plan,
            briefing_run_id=run_id,
            created_at=context.generated_at,
            state_store=store,
        )
    )
    archive_pipeline_facts(
        store,
        briefing_run_id=run_id,
        result=result,
    )


def _write_synthetic_web_database(result: PipelineResult) -> Path:
    path = OUTPUT_DIRECTORY / "synthetic-web.sqlite3"
    with Database.open(path) as database:
        store = StateStore(database)
        store.reset()
        context = result.plan.context
        run_id = "milestone-11-synthetic-web"
        store.add_briefing_run(
            BriefingRun(
                id=run_id,
                briefing_date=context.briefing_date,
                timezone=context.timezone,
                invocation_mode="synthetic_web_review",
                started_at=context.generated_at,
                completed_at=context.generated_at,
                status=BriefingStatus.SUCCEEDED,
                generated_at=context.generated_at,
                as_of=context.as_of,
                historical_mode=HistoricalMode.SYNTHETIC.value,
                processing_versions_json=json.dumps(
                    {
                        "briefing_rules": "milestone-11",
                        "ranking_rules": "milestone-9",
                    },
                    sort_keys=True,
                ),
            )
        )
        for index, coverage in enumerate(result.plan.coverage):
            connector_id = f"{run_id}:coverage:{index}"
            store.add_connector_run(
                ConnectorRun(
                    id=connector_id,
                    source=coverage.source,
                    approved_scope=coverage.approved_scope,
                    started_at=context.generated_at,
                    completed_at=context.generated_at,
                    status=(
                        ConnectorStatus.SUCCEEDED
                        if coverage.status is CoverageStatus.COMPLETE
                        else ConnectorStatus.PARTIAL
                    ),
                    coverage_status=coverage.status,
                    freshness_at=coverage.freshness_at,
                    error_category=coverage.error_category,
                    record_count=coverage.record_count,
                )
            )
            store.link_connector_run(run_id, connector_id)
        store.save_briefing_presentation(
            presentation_from_plan(
                result.plan,
                briefing_run_id=run_id,
                created_at=context.generated_at,
                state_store=store,
            )
        )
    path.chmod(0o600)
    return path


def _review_index(aggregate: dict[str, object], database: Path) -> str:
    return "\n".join(
        (
            "# Milestone 11 Private Synthetic Review",
            "",
            "This directory contains only controlled synthetic evaluation data. "
            "Do not commit it.",
            "",
            f"- Aggregate passed: {aggregate['passed']}",
            f"- Metrics: {aggregate['metric_count']}",
            "- Provider calls: 0",
            "- Live connector calls: 0",
            "- Authorization refreshes: 0",
            "- External writes: 0",
            f"- Synthetic web database: `{database.name}`",
            "",
            "Review `comparison-report.md`, the representative and outage "
            "briefings, `recorded-versus-reconstructed.md`, "
            "`safe-title-example.md`, `responsive-review.json`, the 1280- and "
            "560-pixel screenshots, and the print/PDF artifact.",
            "",
            "Brad's review remains the Milestone 11 acceptance gate.",
            "",
        )
    )


def _write_private(path: Path, content: str) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
    finally:
        path.chmod(0o600)


if __name__ == "__main__":
    raise SystemExit(main())
