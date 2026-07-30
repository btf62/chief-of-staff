"""Deterministic validation after provider translation."""

from __future__ import annotations

from chief_of_staff.inference.models import (
    ACTIONABLE_CLASSIFICATIONS,
    MAX_EXPLANATION_CHARACTERS,
    InclusionRecommendation,
    InferenceRequest,
    InferenceResult,
    InferenceStatus,
    Uncertainty,
    ValidationReport,
    ValidationStatus,
)


def validate_inference_result(
    request: InferenceRequest,
    result: InferenceResult,
) -> ValidationReport:
    """Apply independent schema, provenance, and semantic policy checks."""

    schema_errors = _schema_errors(request, result)
    if schema_errors:
        return ValidationReport(
            status=ValidationStatus.SCHEMA_REJECTED,
            errors=tuple(schema_errors),
        )

    supplied = set(request.packet.evidence_reference_ids)
    returned = set(result.evidence_reference_ids)
    provenance_errors: list[str] = []
    if not returned.issubset(supplied):
        provenance_errors.append("result invented an evidence reference")
    if result.classification in ACTIONABLE_CLASSIFICATIONS and not returned:
        provenance_errors.append("actionable result omitted evidence references")
    if provenance_errors:
        return ValidationReport(
            status=ValidationStatus.PROVENANCE_REJECTED,
            errors=tuple(provenance_errors),
        )

    policy_errors: list[str] = []
    if result.classification not in request.packet.allowed_classifications:
        policy_errors.append("classification conflicts with deterministic policy")
    if result.classification in ACTIONABLE_CLASSIFICATIONS:
        if (
            result.recommendation is InclusionRecommendation.INCLUDE
            and result.uncertainty is not Uncertainty.LOW
        ):
            policy_errors.append("precision-first inclusion requires low uncertainty")
    elif result.recommendation is not InclusionRecommendation.EXCLUDE:
        policy_errors.append("non-actionable result cannot be included")
    if policy_errors:
        return ValidationReport(
            status=ValidationStatus.POLICY_REJECTED,
            errors=tuple(policy_errors),
        )
    return ValidationReport(status=ValidationStatus.ACCEPTED)


def _schema_errors(
    request: InferenceRequest,
    result: InferenceResult,
) -> list[str]:
    errors: list[str] = []
    if result.status is not InferenceStatus.COMPLETED:
        errors.append("result did not complete")
    if not result.explanation.strip() or len(result.explanation) > (
        MAX_EXPLANATION_CHARACTERS
    ):
        errors.append("result explanation is invalid")
    expected_versions = (
        (result.task_version, request.task_version),
        (result.prompt_version, request.prompt_version),
        (result.schema_version, request.schema_version),
        (result.policy_version, request.policy_version),
        (
            result.model_configuration_version,
            request.model_configuration_version,
        ),
    )
    if any(actual != expected for actual, expected in expected_versions):
        errors.append("result behavior versions do not match the request")
    usage = result.usage
    if min(usage.input_tokens, usage.output_tokens, usage.total_tokens) < 0:
        errors.append("provider usage contains a negative value")
    return errors
