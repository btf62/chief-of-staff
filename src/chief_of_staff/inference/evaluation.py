"""Privacy-safe synthetic evaluation for contextual inference."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast

from chief_of_staff.domain import RecurrenceAction, RecurrenceDecision
from chief_of_staff.inference.coordinator import ContextualInferenceCoordinator
from chief_of_staff.inference.evidence import stable_evidence_reference
from chief_of_staff.inference.models import (
    ALL_CONTEXTUAL_CLASSIFICATIONS,
    CandidateEvidence,
    CandidateResolution,
    ContextualClassification,
    InclusionRecommendation,
    InferenceAuditRecord,
    InferenceCandidate,
    InferenceOutcome,
    InferenceRequest,
    InferenceResult,
    InferenceStatus,
    ProviderAuditMetadata,
    ReducedModeReason,
    Uncertainty,
    UsageMetadata,
    ValidationStatus,
)
from chief_of_staff.inference.providers.base import (
    InferenceProviderError,
    InferenceRateLimitError,
    InferenceRefusalError,
    InferenceSchemaError,
    InferenceTimeoutError,
    InferenceUnavailableError,
)
from chief_of_staff.persistence import StateStore

SYNTHETIC_MODEL_CONFIGURATION_VERSION = "synthetic-mocked-v1"
_NOW = datetime(2026, 7, 29, 14, 0, tzinfo=UTC)


class ExpectedEvaluationOutcome(StrEnum):
    """Expected behavior category for one synthetic scenario."""

    ACTIONABLE = "actionable"
    EXCLUSION = "exclusion"
    INSUFFICIENT = "insufficient"
    SENSITIVITY = "sensitivity"
    CREDENTIAL_EXCLUSION = "credential_exclusion"
    SCHEMA_FAILURE = "schema_failure"
    PROVENANCE_FAILURE = "provenance_failure"
    POLICY_FAILURE = "policy_failure"
    CORRECTION = "correction"
    REDUCED_MODE = "reduced_mode"
    DETERMINISTIC_BYPASS = "deterministic_bypass"


@dataclass(frozen=True, slots=True)
class EvaluationScenario:
    """One privacy-safe candidate, scripted response, and expected outcome."""

    name: str
    candidate: InferenceCandidate
    provider_result: InferenceResult | InferenceProviderError
    expected: ExpectedEvaluationOutcome
    expected_classification: ContextualClassification | None = None
    enabled: bool = True
    correction_suppressed: bool = False


@dataclass(frozen=True, slots=True)
class InferenceEvaluationReport:
    """Aggregate quality and safety results by required category."""

    total_scenarios: int
    true_positives: int
    false_positives: int
    false_negatives: int
    correct_exclusions: int
    insufficient_evidence_results: int
    sensitivity_exclusions: int
    schema_failures: int
    provenance_failures: int
    policy_failures: int
    correction_regressions: int
    provider_failure_fallbacks: int
    deterministic_reduced_results: int
    classification_counts: tuple[tuple[str, int], ...]

    @property
    def passed(self) -> bool:
        """Return whether the mocked gate has no trust regression."""

        return (
            self.false_positives == 0
            and self.false_negatives == 0
            and self.correction_regressions == 0
        )


class _ScriptedProvider:
    provider_name = "synthetic_mock"

    def __init__(self, result: InferenceResult | InferenceProviderError) -> None:
        self.result = result
        self.call_count = 0

    def infer(self, request: InferenceRequest) -> InferenceResult:
        self.call_count += 1
        if isinstance(self.result, InferenceProviderError):
            raise self.result
        return replace(
            self.result,
            task_version=request.task_version,
            prompt_version=request.prompt_version,
            schema_version=request.schema_version,
            policy_version=request.policy_version,
            model_configuration_version=request.model_configuration_version,
        )


class _SyntheticCorrectionStore:
    """Minimal correction projection for the privacy-safe evaluation."""

    def recurrence_decision(self, _fingerprint: str) -> RecurrenceDecision:
        return RecurrenceDecision(action=RecurrenceAction.SUPPRESS)

    def add_inference_audit(self, _audit: InferenceAuditRecord) -> None:
        return

    def add_conclusion(self, _conclusion: object) -> None:
        raise AssertionError("suppressed evidence must not create a conclusion")


def run_synthetic_inference_evaluation() -> InferenceEvaluationReport:
    """Run the representative mocked Milestone 8 gate without network access."""

    scenarios = _synthetic_scenarios()
    outcomes: list[tuple[EvaluationScenario, InferenceOutcome]] = []
    for scenario in scenarios:
        provider = _ScriptedProvider(scenario.provider_result)
        state_store = (
            cast(StateStore, _SyntheticCorrectionStore())
            if scenario.correction_suppressed
            else None
        )
        outcome = ContextualInferenceCoordinator(
            provider,
            enabled=scenario.enabled,
            state_store=state_store,
            model_configuration_version=SYNTHETIC_MODEL_CONFIGURATION_VERSION,
        ).evaluate(scenario.candidate, created_at=_NOW)
        outcomes.append((scenario, outcome))
    return _score(tuple(outcomes))


def _score(
    outcomes: tuple[tuple[EvaluationScenario, InferenceOutcome], ...],
) -> InferenceEvaluationReport:
    true_positives = false_positives = false_negatives = 0
    correct_exclusions = insufficient = sensitivity = 0
    schema_failures = provenance_failures = policy_failures = 0
    correction_regressions = provider_failures = deterministic_reduced = 0
    classification_counts: dict[str, int] = {}

    for scenario, outcome in outcomes:
        if outcome.result is not None:
            value = outcome.result.classification.value
            classification_counts[value] = classification_counts.get(value, 0) + 1
        if scenario.expected is ExpectedEvaluationOutcome.ACTIONABLE:
            if (
                outcome.briefing_candidate is not None
                and outcome.briefing_candidate.classification
                is scenario.expected_classification
            ):
                true_positives += 1
            elif outcome.briefing_candidate is None:
                false_negatives += 1
            else:
                false_positives += 1
        elif scenario.expected is ExpectedEvaluationOutcome.EXCLUSION:
            if (
                outcome.briefing_candidate is None
                and outcome.result is not None
                and outcome.result.classification
                is ContextualClassification.NOT_ACTIONABLE
            ):
                correct_exclusions += 1
            else:
                false_positives += 1
        elif scenario.expected is ExpectedEvaluationOutcome.INSUFFICIENT:
            if (
                outcome.briefing_candidate is None
                and outcome.result is not None
                and outcome.result.classification
                is ContextualClassification.INSUFFICIENT_EVIDENCE
            ):
                insufficient += 1
            else:
                false_positives += 1
        elif scenario.expected in {
            ExpectedEvaluationOutcome.SENSITIVITY,
            ExpectedEvaluationOutcome.CREDENTIAL_EXCLUSION,
        }:
            expected_reason = (
                ReducedModeReason.CREDENTIAL_MATERIAL_EXCLUDED
                if scenario.expected is ExpectedEvaluationOutcome.CREDENTIAL_EXCLUSION
                else ReducedModeReason.SENSITIVITY_EXCLUDED
            )
            if outcome.reduced_mode_reason is expected_reason:
                sensitivity += 1
            else:
                false_positives += 1
        elif scenario.expected is ExpectedEvaluationOutcome.SCHEMA_FAILURE:
            if (
                outcome.validation is not None
                and outcome.validation.status is ValidationStatus.SCHEMA_REJECTED
            ):
                schema_failures += 1
            else:
                false_positives += 1
        elif scenario.expected is ExpectedEvaluationOutcome.PROVENANCE_FAILURE:
            if (
                outcome.validation is not None
                and outcome.validation.status is ValidationStatus.PROVENANCE_REJECTED
            ):
                provenance_failures += 1
            else:
                false_positives += 1
        elif scenario.expected is ExpectedEvaluationOutcome.POLICY_FAILURE:
            if (
                outcome.validation is not None
                and outcome.validation.status is ValidationStatus.POLICY_REJECTED
            ):
                policy_failures += 1
            else:
                false_positives += 1
        elif scenario.expected is ExpectedEvaluationOutcome.CORRECTION:
            if (
                outcome.reduced_mode_reason
                is not ReducedModeReason.CORRECTION_SUPPRESSED
                or outcome.provider_invoked
                or outcome.briefing_candidate is not None
            ):
                correction_regressions += 1
        elif scenario.expected is ExpectedEvaluationOutcome.REDUCED_MODE:
            if outcome.reduced_mode_reason in {
                ReducedModeReason.PROVIDER_REFUSAL,
                ReducedModeReason.PROVIDER_TIMEOUT,
                ReducedModeReason.RATE_LIMITED,
                ReducedModeReason.PROVIDER_UNAVAILABLE,
            }:
                provider_failures += 1
            elif outcome.reduced_mode_reason is ReducedModeReason.DISABLED:
                deterministic_reduced += 1
            else:
                false_positives += 1
        elif scenario.expected is ExpectedEvaluationOutcome.DETERMINISTIC_BYPASS:
            if (
                outcome.reduced_mode_reason is ReducedModeReason.DETERMINISTIC_BYPASS
                and not outcome.provider_invoked
            ):
                deterministic_reduced += 1
            else:
                false_positives += 1

    return InferenceEvaluationReport(
        total_scenarios=len(outcomes),
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        correct_exclusions=correct_exclusions,
        insufficient_evidence_results=insufficient,
        sensitivity_exclusions=sensitivity,
        schema_failures=schema_failures,
        provenance_failures=provenance_failures,
        policy_failures=policy_failures,
        correction_regressions=correction_regressions,
        provider_failure_fallbacks=provider_failures,
        deterministic_reduced_results=deterministic_reduced,
        classification_counts=tuple(sorted(classification_counts.items())),
    )


def _synthetic_scenarios() -> tuple[EvaluationScenario, ...]:
    promise = _candidate("contextual-promise", "Project delivery language is implied.")
    waiting = _candidate(
        "implied-waiting", "Project review appears to need a response."
    )
    preparation = _candidate(
        "meeting-preparation",
        "The meeting agenda implies a review before the session.",
    )
    scenarios = [
        _positive(
            "contextual promise",
            promise,
            ContextualClassification.CONTEXTUAL_COMMITMENT,
        ),
        _positive(
            "implied response expectation",
            waiting,
            ContextualClassification.PERSON_POSSIBLY_WAITING,
        ),
        _positive(
            "meeting preparation",
            preparation,
            ContextualClassification.PREPARATION_POSSIBLY_NEEDED,
        ),
    ]
    for name, text in (
        ("stale discussion", "An old project discussion has no current action."),
        ("forwarded request", "A quoted project request was forwarded for awareness."),
        ("automated notification", "An automated project status notice was generated."),
        ("addressed elsewhere", "The project request is addressed to another owner."),
        ("later response", "A later project response resolves the earlier request."),
    ):
        candidate = _candidate(name, text)
        scenarios.append(
            EvaluationScenario(
                name=name,
                candidate=candidate,
                provider_result=_result(
                    ContextualClassification.NOT_ACTIONABLE,
                    candidate.evidence[0].reference_id,
                    recommendation=InclusionRecommendation.EXCLUDE,
                ),
                expected=ExpectedEvaluationOutcome.EXCLUSION,
            )
        )
    for name, text in (
        ("tentative language", "The project might perhaps need a future review."),
        (
            "conflicting evidence",
            "Project evidence conflicts about the expected action.",
        ),
        ("insufficient evidence", "A project mention lacks the relevant context."),
    ):
        candidate = _candidate(name, text)
        scenarios.append(
            EvaluationScenario(
                name=name,
                candidate=candidate,
                provider_result=_result(
                    ContextualClassification.INSUFFICIENT_EVIDENCE,
                    candidate.evidence[0].reference_id,
                    uncertainty=Uncertainty.HIGH,
                    recommendation=InclusionRecommendation.EXCLUDE,
                ),
                expected=ExpectedEvaluationOutcome.INSUFFICIENT,
            )
        )
    for name, text in (
        ("heightened sensitivity", "A pastoral health matter mentions a meeting."),
        ("high sensitivity", "A crisis narrative includes a project deadline."),
        ("mixed sensitivity", "A family matter overlaps a project meeting."),
    ):
        scenarios.append(
            EvaluationScenario(
                name=name,
                candidate=_candidate(name, text),
                provider_result=_result(
                    ContextualClassification.NOT_ACTIONABLE,
                    "unused",
                    recommendation=InclusionRecommendation.EXCLUDE,
                ),
                expected=ExpectedEvaluationOutcome.SENSITIVITY,
            )
        )
    scenarios.append(
        EvaluationScenario(
            name="credential exclusion",
            candidate=_candidate(
                "credential-exclusion",
                "Project API key=sk-example123456789 must never leave the host.",
            ),
            provider_result=_result(
                ContextualClassification.NOT_ACTIONABLE,
                "unused",
                recommendation=InclusionRecommendation.EXCLUDE,
            ),
            expected=ExpectedEvaluationOutcome.CREDENTIAL_EXCLUSION,
        )
    )
    malformed = _candidate("malformed-output", "Project review needs classification.")
    scenarios.append(
        EvaluationScenario(
            name="malformed provider output",
            candidate=malformed,
            provider_result=InferenceSchemaError("synthetic schema failure"),
            expected=ExpectedEvaluationOutcome.SCHEMA_FAILURE,
        )
    )
    invented = _candidate("invented-reference", "Project review may need a response.")
    scenarios.append(
        EvaluationScenario(
            name="invented evidence reference",
            candidate=invented,
            provider_result=_result(
                ContextualClassification.PERSON_POSSIBLY_WAITING,
                "ev_invented",
            ),
            expected=ExpectedEvaluationOutcome.PROVENANCE_FAILURE,
        )
    )
    policy = _candidate(
        "resolved-policy-conflict",
        "The project response was already resolved.",
        allowed=(ContextualClassification.NOT_ACTIONABLE,),
    )
    scenarios.append(
        EvaluationScenario(
            name="schema-valid policy conflict",
            candidate=policy,
            provider_result=_result(
                ContextualClassification.CONTEXTUAL_COMMITMENT,
                policy.evidence[0].reference_id,
            ),
            expected=ExpectedEvaluationOutcome.POLICY_FAILURE,
        )
    )
    for name, error in (
        ("provider refusal", InferenceRefusalError("synthetic refusal")),
        ("provider timeout", InferenceTimeoutError("synthetic timeout")),
        ("provider rate limit", InferenceRateLimitError("synthetic rate limit")),
        (
            "provider unavailable",
            InferenceUnavailableError("synthetic unavailable"),
        ),
    ):
        scenarios.append(
            EvaluationScenario(
                name=name,
                candidate=_candidate(name, "A project candidate needs review."),
                provider_result=error,
                expected=ExpectedEvaluationOutcome.REDUCED_MODE,
            )
        )
    disabled = _candidate("disabled", "A project candidate remains deterministic.")
    scenarios.append(
        EvaluationScenario(
            name="deterministic reduced mode",
            candidate=disabled,
            provider_result=_result(
                ContextualClassification.CONTEXTUAL_COMMITMENT,
                disabled.evidence[0].reference_id,
            ),
            expected=ExpectedEvaluationOutcome.REDUCED_MODE,
            enabled=False,
        )
    )
    corrected = _candidate(
        "dismissed-prior-inference",
        "A materially unchanged project candidate was dismissed.",
    )
    scenarios.append(
        EvaluationScenario(
            name="dismissed prior inference",
            candidate=corrected,
            provider_result=_result(
                ContextualClassification.CONTEXTUAL_COMMITMENT,
                corrected.evidence[0].reference_id,
            ),
            expected=ExpectedEvaluationOutcome.CORRECTION,
            correction_suppressed=True,
        )
    )
    explicit = _candidate(
        "explicit-bypass",
        "The project request was deterministically explicit.",
        resolution=CandidateResolution.EXPLICIT_DETERMINISTIC,
    )
    scenarios.append(
        EvaluationScenario(
            name="explicit deterministic bypass",
            candidate=explicit,
            provider_result=_result(
                ContextualClassification.PERSON_POSSIBLY_WAITING,
                explicit.evidence[0].reference_id,
            ),
            expected=ExpectedEvaluationOutcome.DETERMINISTIC_BYPASS,
        )
    )
    return tuple(scenarios)


def _positive(
    name: str,
    candidate: InferenceCandidate,
    classification: ContextualClassification,
) -> EvaluationScenario:
    return EvaluationScenario(
        name=name,
        candidate=candidate,
        provider_result=_result(
            classification,
            candidate.evidence[0].reference_id,
        ),
        expected=ExpectedEvaluationOutcome.ACTIONABLE,
        expected_classification=classification,
    )


def _candidate(
    name: str,
    text: str,
    *,
    allowed: tuple[ContextualClassification, ...] = (ALL_CONTEXTUAL_CLASSIFICATIONS),
    resolution: CandidateResolution = CandidateResolution.UNRESOLVED_CONTEXTUAL,
) -> InferenceCandidate:
    reference = stable_evidence_reference("synthetic", name)
    return InferenceCandidate(
        id=f"candidate-{name}",
        resolution=resolution,
        evidence_fingerprint=f"fingerprint-{name}",
        evidence=(
            CandidateEvidence(
                reference_id=reference,
                source="synthetic",
                source_record_id=name,
                content=text,
            ),
        ),
        allowed_classifications=allowed,
    )


def _result(
    classification: ContextualClassification,
    reference_id: str,
    *,
    uncertainty: Uncertainty = Uncertainty.LOW,
    recommendation: InclusionRecommendation = InclusionRecommendation.INCLUDE,
) -> InferenceResult:
    return InferenceResult(
        status=InferenceStatus.COMPLETED,
        classification=classification,
        evidence_reference_ids=(reference_id,),
        explanation="Synthetic evidence supports this bounded classification.",
        uncertainty=uncertainty,
        recommendation=recommendation,
        task_version="1",
        prompt_version="contextual-action-v1",
        schema_version="contextual-action-result-v1",
        policy_version="contextual-action-policy-v1",
        model_configuration_version=SYNTHETIC_MODEL_CONFIGURATION_VERSION,
        provider_audit=ProviderAuditMetadata(
            provider="synthetic_mock",
            model_id="synthetic-model",
            request_count=1,
            latency_ms=1,
        ),
        usage=UsageMetadata(
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
        ),
    )
