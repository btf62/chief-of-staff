"""Synthetic ranking, plan, and composition tests for Milestone 9."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from chief_of_staff.connectors import ReadOnlyConnector, SourceItem, StaticConnector
from chief_of_staff.domain import CoverageStatus
from chief_of_staff.inference.providers.openai import OpenAISDKResponsesTransport
from chief_of_staff.pipeline import (
    BriefingContentKind,
    BriefingSectionName,
    PriorityBand,
    RankingFactorKind,
)
from chief_of_staff.pipeline.context import resolve_context
from chief_of_staff.pipeline.evaluation import (
    RankingEvaluationReport,
    run_synthetic_ranking_evaluation,
    synthetic_ranking_scenarios,
)
from chief_of_staff.pipeline.ranking import RankedCandidate
from chief_of_staff.pipeline.runner import DeterministicBriefingPipeline, PipelineResult


@lru_cache(maxsize=1)
def _evaluation() -> tuple[
    RankingEvaluationReport,
    tuple[tuple[str, PipelineResult], ...],
]:
    return run_synthetic_ranking_evaluation()


def _outputs() -> dict[str, PipelineResult]:
    return dict(_evaluation()[1])


def test_representative_corpus_passes_without_false_positive_actions() -> None:
    report, _ = _evaluation()

    assert report.scenario_count >= 25
    assert report.passed
    assert report.failed_count == 0
    assert report.false_positive_actionable_recommendations == 0
    assert report.unsupported_claims == 0


def test_milestone_9_spec_is_accepted_and_human_review_remains_the_gate() -> None:
    root = Path(__file__).parents[1]
    specification = (
        root / "docs/product/features/ranking-and-briefing-composition-v1.md"
    ).read_text(encoding="utf-8")
    roadmap = (root / "docs/roadmap.md").read_text(encoding="utf-8")

    assert "**Status:** Accepted" in specification
    milestone = roadmap.split(
        "## Milestone 9 — Ranking and Briefing Composition",
        maxsplit=1,
    )[1].split("## Milestone 10", maxsplit=1)[0]
    assert "Implementation complete — Brad review pending" in milestone
    assert "Brad's review" in milestone


def test_every_applied_ranking_factor_is_inspectable_and_source_backed() -> None:
    candidates = tuple(
        candidate
        for result in _outputs().values()
        for candidate in result.plan.ordered_eligible_candidates
    )

    assert candidates
    assert all(candidate.factors for candidate in candidates)
    assert all(
        factor.rationale
        and factor.sources
        and all(
            source.source
            and source.source_record_id
            and source.fact_name
            and source.fact_value
            for source in factor.sources
        )
        for candidate in candidates
        for factor in candidate.factors
    )


def test_weak_source_signals_cannot_force_a_top_outcome() -> None:
    outputs = _outputs()
    no_outcome = outputs["no-supported-outcome"]
    adversarial = outputs["adversarial-manufactured-priority"]
    assignment_only = outputs["assignment-alone-cannot-top-rank"]

    assert no_outcome.plan.selected_outcome_ids == ()
    assert adversarial.plan.selected_outcome_ids == ("todoist:today-outcome",)
    assert assignment_only.plan.selected_outcome_ids == ("todoist:today-outcome",)
    weak = next(
        candidate
        for candidate in no_outcome.plan.ordered_eligible_candidates
        if candidate.record.id == "todoist:priority-only"
    )
    assert weak.band is PriorityBand.BACKGROUND
    assert all(
        candidate.record.id != "todoist:adversarial"
        for candidate in adversarial.plan.ordered_eligible_candidates
    )


def test_correction_state_is_applied_before_visible_ranking() -> None:
    result = _outputs()["corrected-or-dismissed-conclusion"]

    assert len(result.plan.suppressed_by_correction) == 1
    assert result.plan.suppressed_by_correction[0].record_id == "todoist:dismiss-me"
    assert all(
        candidate.record.id != "todoist:dismiss-me"
        for candidate in result.plan.ordered_eligible_candidates
    )
    assert "Dismissed unchanged recommendation" not in result.rendered.text


def test_supported_effort_is_preserved_and_unsupported_effort_is_not_invented() -> None:
    result = _outputs()["supported-versus-unsupported-effort"]
    candidates = {
        candidate.record.id: candidate
        for candidate in result.plan.ordered_eligible_candidates
    }

    supported = candidates["todoist:supported-effort"]
    unsupported = candidates["todoist:unsupported-effort"]
    assert RankingFactorKind.SUPPORTED_EFFORT in _factor_kinds(supported)
    assert RankingFactorKind.SUPPORTED_EFFORT not in _factor_kinds(unsupported)
    assert unsupported.record.effort_minutes is None


def test_briefing_plan_separates_semantic_content_roles_from_note_inputs() -> None:
    outputs = _outputs()
    normal = outputs["normal-full-workday"]
    inferred = outputs["accepted-contextual-inference"]

    assert normal.plan.note_inputs is not None
    assert normal.plan.note_inputs.primary_outcome_id == "todoist:today-outcome"
    assert any(
        item.content_kind is BriefingContentKind.RECOMMENDATION
        for section in normal.plan.sections
        for item in section.items
    )
    inferred_items = tuple(
        item
        for section in inferred.plan.sections
        for item in section.items
        if item.content_kind is BriefingContentKind.INFERRED_CONCLUSION
    )
    assert len(inferred_items) == 1
    assert inferred_items[0].inference_explanation
    assert inferred_items[0].uncertainty == "low"


def test_outcome_and_section_budgets_allow_fewer_without_manufacturing() -> None:
    outputs = _outputs()

    assert (
        len(outputs["long-candidate-set-with-budgets"].plan.selected_outcome_ids) == 3
    )
    assert len(outputs["only-one-supported-outcome"].plan.selected_outcome_ids) == 1
    assert outputs["no-supported-outcome"].plan.selected_outcome_ids == ()
    assert all(
        len(section.items) <= 3
        for result in outputs.values()
        for section in result.plan.sections
        if section.name
        in {
            BriefingSectionName.TODAYS_OUTCOMES,
            BriefingSectionName.UP_NEXT,
            BriefingSectionName.PEOPLE_WAITING,
            BriefingSectionName.COMMITMENTS_AT_RISK,
            BriefingSectionName.IMPORTANT_TASKS,
        }
    )


def test_empty_sections_are_omitted_and_order_is_canonical() -> None:
    result = _outputs()["empty-or-immaterial-sections"]
    names = tuple(section.name for section in result.plan.sections)

    assert BriefingSectionName.TODAYS_OUTCOMES not in names
    assert BriefingSectionName.IMPORTANT_TASKS not in names
    assert names == tuple(
        sorted(names, key=lambda name: tuple(BriefingSectionName).index(name))
    )
    assert names[-1] is BriefingSectionName.SOURCE_COVERAGE


def test_calendar_items_remain_chronological() -> None:
    result = _outputs()["meeting-heavy-day"]
    section = next(
        section
        for section in result.plan.sections
        if section.name is BriefingSectionName.TODAYS_CALENDAR
    )

    times = tuple(item.sort_at for item in section.items)
    assert all(value is not None for value in times)
    assert times == tuple(sorted(times))  # type: ignore[type-var]


def test_duplicate_suppression_preserves_all_links_and_conflicts() -> None:
    outputs = _outputs()
    duplicate = outputs["cross-source-duplicate"].plan
    conflict = outputs["conflicting-source-dates"].plan

    assert duplicate.suppressed_duplicates
    assert all(
        len(suppression.sources) >= 2 for suppression in duplicate.suppressed_duplicates
    )
    assert "jira/NRC-101" in outputs["cross-source-duplicate"].rendered.text
    assert (
        "todoist/todoist-duplicate" in outputs["cross-source-duplicate"].rendered.text
    )
    assert conflict.unresolved_conflicts
    text = outputs["conflicting-source-dates"].rendered.text
    assert "Jira reports the due date as today" in text
    assert "Todoist reports the due date as Thursday, July 30" in text
    assert "Each source remains authoritative for its own record" in text


def test_unconflicted_due_date_is_direct_but_conflicting_dates_are_qualified() -> None:
    outputs = _outputs()
    direct = outputs["normal-full-workday"].rendered.text
    conflicting = outputs["conflicting-source-dates"]
    conflict_text = conflicting.rendered.text

    assert "The deadline is today at 5:00 PM." in direct
    assert "The deadline is today" not in conflict_text
    assert "The due date is today" not in conflict_text
    assert "one authoritative source reports an immediate deadline" in conflict_text
    assert "verify the conflict before planning the work" in conflict_text
    assert "newer source fact" not in conflict_text

    due_factors = tuple(
        factor
        for candidate in conflicting.plan.ordered_eligible_candidates
        for factor in candidate.factors
        if factor.kind is RankingFactorKind.DUE_DATE
    )
    assert due_factors
    assert all(len(factor.sources) == 2 for factor in due_factors)
    assert all(
        "One authoritative source reports" in factor.rationale for factor in due_factors
    )
    outcome = next(
        section
        for section in conflicting.plan.sections
        if section.name is BriefingSectionName.TODAYS_OUTCOMES
    )
    assert len(outcome.items[0].sources) == 2


def test_owner_status_priority_and_completion_conflicts_are_source_attributed() -> None:
    result = _multi_field_conflict_result()
    text = result.rendered.text

    assert "Jira reports the owner as team-a" in text
    assert "Todoist reports the owner as team-b" in text
    assert "Jira reports the status as in progress" in text
    assert "Todoist reports the status as done" in text
    assert "Jira reports the priority as High" in text
    assert "Todoist reports the priority as Low" in text
    assert "Jira reports the item as not completed" in text
    assert "Todoist reports the item as completed" in text
    assert "Jira provides the newer source fact" in text
    assert "more authoritative" not in text
    assert all(
        len(conflict.sources) == 2 and conflict.claims
        for conflict in result.plan.unresolved_conflicts
    )


def test_ranking_prose_is_natural_for_one_two_and_multiple_visible_factors() -> None:
    outputs = _outputs()
    one_factor = outputs["long-candidate-set-with-budgets"].rendered.text
    two_factors = outputs["normal-full-workday"].rendered.text
    multiple_factors = outputs["open-deep-work-morning"].rendered.text
    combined = "\n".join((one_factor, two_factors, multiple_factors))

    assert "This deserves attention today because it has a hard deadline." in one_factor
    assert (
        "This deserves attention today because it has a hard deadline and it falls "
        "within Brad's primary stewardship."
    ) in two_factors
    assert "the source supplies an effort estimate" in multiple_factors
    assert "fits the available Calendar window" in multiple_factors
    assert "fits the morning" in multiple_factors
    assert "source-marked" not in combined
    assert "current source due date" not in combined
    assert "Critical priority" not in combined
    assert "freshness" not in one_factor
    assert "provider priority" not in one_factor


def test_calendar_and_count_prose_preserves_blocks_and_grammar() -> None:
    outputs = _outputs()
    meeting_note = outputs["meeting-heavy-day"].plan.sections[0].summary or ""
    normal_note = outputs["normal-full-workday"].plan.sections[0].summary or ""
    single_coverage = (
        outputs["only-one-supported-outcome"].plan.sections[-1].summary or ""
    )

    assert (
        "3 separate Calendar commitments occupy 7 hours 15 minutes between "
        "8:00 a.m. and 4:30 p.m."
    ) in meeting_note
    assert "2 gaps totaling 1 hour 15 minutes" in meeting_note
    assert "1 tight transition has 15 minutes or less" in meeting_note
    assert "across" not in meeting_note
    assert "through" not in meeting_note
    assert (
        "1 Calendar commitment occupies 1 hour from 1:00\N{EN DASH}2:00 p.m."
        in normal_note
    )
    assert "p.m.." not in normal_note
    assert "1 candidate" in single_coverage
    assert "1 candidates" not in single_coverage


def test_word_note_and_focus_budgets_remain_enforced() -> None:
    outputs = _outputs()
    assert max(result.rendered.word_count for result in outputs.values()) <= 1000
    assert BriefingSectionName.RECOMMENDED_FOCUS_BLOCK in {
        section.name for section in outputs["open-deep-work-morning"].plan.sections
    }
    assert BriefingSectionName.RECOMMENDED_FOCUS_BLOCK not in {
        section.name for section in outputs["meeting-heavy-day"].plan.sections
    }


def test_partial_and_unavailable_coverage_is_disclosed_only_in_appendix() -> None:
    outputs = _outputs()
    partial = outputs["partial-gmail-coverage"]
    unavailable = outputs["one-unavailable-source"]

    assert partial.plan.coverage_warnings
    assert unavailable.plan.coverage_warnings
    assert "partial" in partial.rendered.text
    assert "unavailable" in unavailable.rendered.text
    for result in (partial, unavailable):
        note = result.plan.sections[0]
        assert "source coverage" not in (note.summary or "").casefold()
        assert result.plan.sections[-1].name is BriefingSectionName.SOURCE_COVERAGE


def test_sensitive_or_policy_rejected_inference_is_not_presented() -> None:
    outputs = _outputs()
    assert (
        "Questionable inferred request"
        not in outputs["contextual-inference-rejected-by-policy"].rendered.text
    )
    assert (
        "Sensitive ambiguous situation"
        not in outputs["sensitive-item-excluded-from-hosted-inference"].rendered.text
    )


def test_evaluation_uses_only_static_read_only_connectors_and_no_provider() -> None:
    scenarios = synthetic_ranking_scenarios()
    report, _ = _evaluation()

    assert all(
        isinstance(connector, StaticConnector)
        and isinstance(connector, ReadOnlyConnector)
        for scenario in scenarios
        for connector in scenario.connectors
    )
    assert report.provider_calls == 0
    assert report.live_connector_calls == 0
    assert report.external_writes == 0
    assert all(
        not any(
            hasattr(connector, name)
            for name in ("create", "update", "delete", "send", "mutate")
        )
        for scenario in scenarios
        for connector in scenario.connectors
    )


def test_synthetic_gate_does_not_invoke_the_openai_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Milestone 9 must not make an OpenAI request")

    monkeypatch.setattr(
        OpenAISDKResponsesTransport,
        "create_response",
        fail_if_called,
    )

    report, _ = run_synthetic_ranking_evaluation()
    assert report.passed
    assert report.provider_calls == 0


def test_qualitative_ties_use_a_documented_deterministic_fallback() -> None:
    candidates = _outputs()[
        "long-candidate-set-with-budgets"
    ].plan.ordered_eligible_candidates
    tied = tuple(
        candidate
        for candidate in candidates
        if candidate.qualitative_comparison_would_help
    )

    assert tied
    assert all("Deterministic fallback" in candidate.tie_breaker for candidate in tied)


def _multi_field_conflict_result() -> PipelineResult:
    zone = ZoneInfo("America/New_York")
    now = datetime(2026, 7, 29, 8, 0, tzinfo=zone)
    due_at = datetime(2026, 7, 29, 17, 0, tzinfo=zone).isoformat()
    jira = SourceItem(
        id="jira-multi-conflict",
        source_record_id="NRC-303",
        item_type="task",
        facts={
            "title": "Resolve the delivery record",
            "status": "open",
            "status_category": "in progress",
            "assignee_reference": "team-a",
            "source_priority": "High",
            "due_at": due_at,
            "explicit_commitment": True,
        },
        display_url="https://example.invalid/tasks/jira-multi-conflict",
        retrieved_at=now,
        freshness_at=now,
    )
    todoist = SourceItem(
        id="todoist-multi-conflict",
        source_record_id="todoist-multi-conflict",
        item_type="task",
        facts={
            "title": "Resolve NRC-303 delivery record",
            "status": "completed",
            "status_category": "done",
            "assignee_reference": "team-b",
            "source_priority": "Low",
            "due_at": due_at,
            "explicit_commitment": True,
        },
        display_url="https://example.invalid/tasks/todoist-multi-conflict",
        retrieved_at=now,
        freshness_at=now - timedelta(days=1),
    )
    connectors = (
        StaticConnector(
            source_name="jira",
            approved_scope="synthetic conflict regression",
            items=(jira,),
            status=CoverageStatus.COMPLETE,
        ),
        StaticConnector(
            source_name="todoist",
            approved_scope="synthetic conflict regression",
            items=(todoist,),
            status=CoverageStatus.COMPLETE,
        ),
    )
    context = resolve_context(
        run_id="m9-multi-field-conflict",
        briefing_date=date(2026, 7, 29),
        timezone="America/New_York",
    )
    return DeterministicBriefingPipeline().run(context, connectors)


def _factor_kinds(candidate: RankedCandidate) -> set[RankingFactorKind]:
    return {factor.kind for factor in candidate.factors}
