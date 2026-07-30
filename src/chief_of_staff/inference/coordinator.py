"""Deterministic orchestration around the provider-neutral inference boundary."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from chief_of_staff.domain import (
    Classification,
    Conclusion,
    ConclusionKind,
    RecurrenceAction,
)
from chief_of_staff.inference.evidence import (
    EvidencePacketError,
    build_evidence_packet,
)
from chief_of_staff.inference.models import (
    ACTIONABLE_CLASSIFICATIONS,
    INFERENCE_TASK_NAME,
    INFERENCE_TASK_VERSION,
    MODEL_CONFIGURATION_VERSION,
    POLICY_VERSION,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    BriefingInferenceCandidate,
    CandidateResolution,
    ContextualClassification,
    EvidencePacket,
    InclusionRecommendation,
    InferenceAuditRecord,
    InferenceCandidate,
    InferenceOutcome,
    InferenceRequest,
    InferenceResult,
    InferenceStatus,
    ReducedModeReason,
    SensitivityTier,
    ValidationReport,
    ValidationStatus,
)
from chief_of_staff.inference.policy import validate_inference_result
from chief_of_staff.inference.providers.base import (
    InferenceConfigurationError,
    InferenceCredentialError,
    InferenceDisabledError,
    InferenceModelMismatchError,
    InferenceProvider,
    InferenceProviderPolicyError,
    InferenceRateLimitError,
    InferenceRefusalError,
    InferenceSchemaError,
    InferenceTimeoutError,
    InferenceUnavailableError,
)
from chief_of_staff.observability import log_event
from chief_of_staff.persistence import StateStore


class ContextualInferenceCoordinator:
    """Evaluate only unresolved, eligible, materially new candidates."""

    def __init__(
        self,
        provider: InferenceProvider,
        *,
        enabled: bool = False,
        state_store: StateStore | None = None,
        logger: logging.Logger | None = None,
        briefing_run_id: str | None = None,
        model_configuration_version: str = MODEL_CONFIGURATION_VERSION,
        persist_conclusions: bool = True,
    ) -> None:
        self.provider = provider
        self.enabled = enabled
        self.state_store = state_store
        self.logger = logger
        self.briefing_run_id = briefing_run_id
        self.model_configuration_version = model_configuration_version
        self.persist_conclusions = persist_conclusions

    def evaluate(
        self,
        candidate: InferenceCandidate,
        *,
        created_at: datetime | None = None,
    ) -> InferenceOutcome:
        """Run one complete classification path with deterministic fallback."""

        now = created_at or datetime.now(UTC)
        if candidate.resolution is CandidateResolution.EXPLICIT_DETERMINISTIC:
            return self._skip(
                candidate,
                now,
                ReducedModeReason.DETERMINISTIC_BYPASS,
            )
        if candidate.resolution is CandidateResolution.INSUFFICIENT_EVIDENCE:
            return self._skip(
                candidate,
                now,
                ReducedModeReason.INSUFFICIENT_INPUT,
            )
        if not self.enabled:
            return self._skip(candidate, now, ReducedModeReason.DISABLED)

        if self.state_store is not None:
            recurrence = self.state_store.recurrence_decision(
                candidate.evidence_fingerprint
            )
            if recurrence.action is not RecurrenceAction.SHOW:
                return self._skip(
                    candidate,
                    now,
                    ReducedModeReason.CORRECTION_SUPPRESSED,
                )

        try:
            packet = build_evidence_packet(candidate)
        except EvidencePacketError:
            return self._skip(
                candidate,
                now,
                ReducedModeReason.INSUFFICIENT_INPUT,
            )
        if packet.sensitivity.tier is SensitivityTier.INELIGIBLE_CREDENTIAL_MATERIAL:
            return self._skip(
                candidate,
                now,
                ReducedModeReason.CREDENTIAL_MATERIAL_EXCLUDED,
                packet=packet,
            )
        if not packet.sensitivity.hosted_eligible:
            return self._skip(
                candidate,
                now,
                ReducedModeReason.SENSITIVITY_EXCLUDED,
                packet=packet,
            )

        request = InferenceRequest(
            packet=packet,
            created_at=now,
            model_configuration_version=self.model_configuration_version,
        )
        try:
            result = self.provider.infer(request)
        except InferenceDisabledError:
            return self._failure(
                candidate,
                request,
                now,
                ReducedModeReason.DISABLED,
                provider_invoked=False,
            )
        except InferenceConfigurationError:
            return self._failure(
                candidate,
                request,
                now,
                ReducedModeReason.CONFIGURATION_MISSING,
                provider_invoked=False,
            )
        except InferenceCredentialError:
            return self._failure(
                candidate,
                request,
                now,
                ReducedModeReason.CREDENTIAL_UNAVAILABLE,
                provider_invoked=False,
            )
        except InferenceRefusalError:
            return self._failure(
                candidate,
                request,
                now,
                ReducedModeReason.PROVIDER_REFUSAL,
                provider_invoked=True,
                status=InferenceStatus.REFUSED,
            )
        except InferenceTimeoutError:
            return self._failure(
                candidate,
                request,
                now,
                ReducedModeReason.PROVIDER_TIMEOUT,
                provider_invoked=True,
            )
        except InferenceRateLimitError:
            return self._failure(
                candidate,
                request,
                now,
                ReducedModeReason.RATE_LIMITED,
                provider_invoked=True,
            )
        except InferenceSchemaError:
            validation = ValidationReport(
                status=ValidationStatus.SCHEMA_REJECTED,
                errors=("provider output failed the application-owned schema",),
            )
            return self._failure(
                candidate,
                request,
                now,
                ReducedModeReason.SCHEMA_REJECTED,
                provider_invoked=True,
                validation=validation,
                status=InferenceStatus.REJECTED,
            )
        except InferenceModelMismatchError:
            validation = ValidationReport(
                status=ValidationStatus.POLICY_REJECTED,
                errors=("provider returned an unapproved model",),
            )
            return self._failure(
                candidate,
                request,
                now,
                ReducedModeReason.POLICY_REJECTED,
                provider_invoked=True,
                validation=validation,
                status=InferenceStatus.REJECTED,
            )
        except InferenceProviderPolicyError:
            validation = ValidationReport(
                status=ValidationStatus.POLICY_REJECTED,
                errors=("provider response violated approved request policy",),
            )
            return self._failure(
                candidate,
                request,
                now,
                ReducedModeReason.POLICY_REJECTED,
                provider_invoked=True,
                validation=validation,
                status=InferenceStatus.REJECTED,
            )
        except InferenceUnavailableError:
            return self._failure(
                candidate,
                request,
                now,
                ReducedModeReason.PROVIDER_UNAVAILABLE,
                provider_invoked=True,
            )

        validation = validate_inference_result(request, result)
        if not validation.accepted:
            reason = {
                ValidationStatus.SCHEMA_REJECTED: ReducedModeReason.SCHEMA_REJECTED,
                ValidationStatus.PROVENANCE_REJECTED: (
                    ReducedModeReason.PROVENANCE_REJECTED
                ),
                ValidationStatus.POLICY_REJECTED: ReducedModeReason.POLICY_REJECTED,
            }[validation.status]
            self._record_audit(
                candidate,
                request.packet,
                now,
                result=result,
                validation=validation,
                error_category=reason.value,
            )
            return InferenceOutcome(
                candidate_id=candidate.id,
                result=result,
                validation=validation,
                briefing_candidate=None,
                reduced_mode_reason=reason,
                provider_invoked=True,
            )

        briefing_candidate = _to_briefing_candidate(candidate, result)
        self._record_audit(
            candidate,
            request.packet,
            now,
            result=result,
            validation=validation,
        )
        if briefing_candidate is not None and self.persist_conclusions:
            self._persist_conclusion(candidate, result, briefing_candidate, now)
        return InferenceOutcome(
            candidate_id=candidate.id,
            result=result,
            validation=validation,
            briefing_candidate=briefing_candidate,
            reduced_mode_reason=None,
            provider_invoked=True,
        )

    def _skip(
        self,
        candidate: InferenceCandidate,
        now: datetime,
        reason: ReducedModeReason,
        *,
        packet: EvidencePacket | None = None,
    ) -> InferenceOutcome:
        self._record_audit(
            candidate,
            packet,
            now,
            result=None,
            validation=None,
            error_category=reason.value,
            status=InferenceStatus.SKIPPED,
        )
        return InferenceOutcome(
            candidate_id=candidate.id,
            result=None,
            validation=None,
            briefing_candidate=None,
            reduced_mode_reason=reason,
            provider_invoked=False,
        )

    def _failure(
        self,
        candidate: InferenceCandidate,
        request: InferenceRequest,
        now: datetime,
        reason: ReducedModeReason,
        *,
        provider_invoked: bool,
        validation: ValidationReport | None = None,
        status: InferenceStatus = InferenceStatus.UNAVAILABLE,
    ) -> InferenceOutcome:
        self._record_audit(
            candidate,
            request.packet,
            now,
            result=None,
            validation=validation,
            error_category=reason.value,
            status=status,
            request_count=int(provider_invoked),
        )
        return InferenceOutcome(
            candidate_id=candidate.id,
            result=None,
            validation=validation,
            briefing_candidate=None,
            reduced_mode_reason=reason,
            provider_invoked=provider_invoked,
        )

    def _record_audit(
        self,
        candidate: InferenceCandidate,
        packet: EvidencePacket | None,
        now: datetime,
        *,
        result: InferenceResult | None,
        validation: ValidationReport | None,
        error_category: str | None = None,
        status: InferenceStatus | None = None,
        request_count: int = 0,
    ) -> None:
        audit = _audit_record(
            candidate,
            packet,
            now,
            result=result,
            validation=validation,
            error_category=error_category,
            status=status,
            request_count=request_count,
            provider_name=self.provider.provider_name,
            model_configuration_version=self.model_configuration_version,
            briefing_run_id=self.briefing_run_id,
        )
        if self.state_store is not None:
            self.state_store.add_inference_audit(audit)
        if self.logger is not None:
            log_event(
                self.logger,
                logging.INFO,
                "inference.contextual_action",
                provider=audit.provider,
                model=audit.model_id,
                request_class=audit.task_name,
                status=audit.status.value,
                validation_result=(
                    "not_run"
                    if audit.validation_status is None
                    else audit.validation_status.value
                ),
                sensitivity_tier=audit.sensitivity_tier.value,
                token_count=audit.total_tokens,
                latency_ms=audit.latency_ms,
                error_category=audit.error_category,
            )

    def _persist_conclusion(
        self,
        candidate: InferenceCandidate,
        result: InferenceResult,
        briefing_candidate: BriefingInferenceCandidate,
        now: datetime,
    ) -> None:
        if self.state_store is None:
            return
        recurrence = self.state_store.recurrence_decision(
            candidate.evidence_fingerprint
        )
        if recurrence.prior_conclusion_id is not None:
            return
        digest = hashlib.sha256(
            f"{candidate.id}\0{candidate.evidence_fingerprint}\0{now.isoformat()}".encode()
        ).hexdigest()
        self.state_store.add_conclusion(
            Conclusion(
                id=f"inference:{digest[:24]}",
                kind=_conclusion_kind(result.classification),
                classification=Classification.INFERRED,
                statement=briefing_candidate.statement,
                explanation=briefing_candidate.explanation,
                confidence=None,
                evidence_fingerprint=candidate.evidence_fingerprint,
                processing_version=(
                    f"{result.task_version}/{result.prompt_version}/"
                    f"{result.schema_version}/{result.policy_version}/"
                    f"{result.model_configuration_version}"
                ),
                created_at=now,
                evidence_ids=result.evidence_reference_ids,
            )
        )


def _to_briefing_candidate(
    candidate: InferenceCandidate,
    result: InferenceResult,
) -> BriefingInferenceCandidate | None:
    if (
        result.classification not in ACTIONABLE_CLASSIFICATIONS
        or result.recommendation is InclusionRecommendation.EXCLUDE
    ):
        return None
    statements = {
        ContextualClassification.CONTEXTUAL_COMMITMENT: (
            "Review a possible contextual commitment."
        ),
        ContextualClassification.PERSON_POSSIBLY_WAITING: (
            "Review a person who may be waiting on Brad."
        ),
        ContextualClassification.PREPARATION_POSSIBLY_NEEDED: (
            "Review preparation that may be needed."
        ),
    }
    return BriefingInferenceCandidate(
        key=f"contextual-inference:{candidate.id}",
        classification=result.classification,
        statement=statements[result.classification],
        explanation=result.explanation,
        uncertainty=result.uncertainty,
        evidence_reference_ids=result.evidence_reference_ids,
    )


def _conclusion_kind(classification: ContextualClassification) -> ConclusionKind:
    return {
        ContextualClassification.CONTEXTUAL_COMMITMENT: ConclusionKind.COMMITMENT,
        ContextualClassification.PERSON_POSSIBLY_WAITING: (ConclusionKind.WAITING_ITEM),
        ContextualClassification.PREPARATION_POSSIBLY_NEEDED: (
            ConclusionKind.PREPARATION_ITEM
        ),
    }[classification]


def _audit_record(
    candidate: InferenceCandidate,
    packet: EvidencePacket | None,
    now: datetime,
    *,
    result: InferenceResult | None,
    validation: ValidationReport | None,
    error_category: str | None,
    status: InferenceStatus | None,
    request_count: int,
    provider_name: str,
    model_configuration_version: str,
    briefing_run_id: str | None,
) -> InferenceAuditRecord:
    candidate_hash = hashlib.sha256(candidate.id.encode()).hexdigest()
    audit_hash = hashlib.sha256(
        f"{candidate.id}\0{candidate.evidence_fingerprint}\0{now.isoformat()}".encode()
    ).hexdigest()
    sensitivity = SensitivityTier.UNKNOWN if packet is None else packet.sensitivity.tier
    if result is None:
        provider = provider_name
        model_id = "unselected"
        latency_ms = 0
        input_tokens = output_tokens = total_tokens = 0
        cost = None
        selected_status = status or InferenceStatus.SKIPPED
    else:
        provider = result.provider_audit.provider
        model_id = result.provider_audit.model_id
        request_count = result.provider_audit.request_count
        latency_ms = result.provider_audit.latency_ms
        input_tokens = result.usage.input_tokens
        output_tokens = result.usage.output_tokens
        total_tokens = result.usage.total_tokens
        cost = result.usage.estimated_cost_microusd
        selected_status = result.status
    return InferenceAuditRecord(
        id=f"inference-audit:{audit_hash[:24]}",
        briefing_run_id=briefing_run_id,
        candidate_id_hash=candidate_hash,
        task_name=INFERENCE_TASK_NAME,
        task_version=INFERENCE_TASK_VERSION,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        policy_version=POLICY_VERSION,
        model_configuration_version=model_configuration_version,
        provider=provider,
        model_id=model_id,
        sensitivity_tier=sensitivity,
        status=selected_status,
        validation_status=None if validation is None else validation.status,
        request_count=request_count,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_microusd=cost,
        error_category=error_category,
        created_at=now,
    )
