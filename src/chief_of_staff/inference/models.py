"""Provider-neutral models for bounded contextual inference."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

INFERENCE_TASK_NAME = "contextual_action_classification"
INFERENCE_TASK_VERSION = "1"
PROMPT_VERSION = "contextual-action-v1"
SCHEMA_VERSION = "contextual-action-result-v1"
POLICY_VERSION = "contextual-action-policy-v1"
MODEL_CONFIGURATION_VERSION = "unselected-v1"
MAX_EXPLANATION_CHARACTERS = 400


class CandidateResolution(StrEnum):
    """Deterministic state before any model boundary."""

    EXPLICIT_DETERMINISTIC = "explicit_deterministic"
    UNRESOLVED_CONTEXTUAL = "unresolved_contextual"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ContextualClassification(StrEnum):
    """Only classifications permitted for the first Milestone 8 task."""

    CONTEXTUAL_COMMITMENT = "contextual_commitment"
    PERSON_POSSIBLY_WAITING = "person_possibly_waiting_on_brad"
    PREPARATION_POSSIBLY_NEEDED = "preparation_possibly_needed"
    NOT_ACTIONABLE = "not_actionable"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


ACTIONABLE_CLASSIFICATIONS = frozenset(
    {
        ContextualClassification.CONTEXTUAL_COMMITMENT,
        ContextualClassification.PERSON_POSSIBLY_WAITING,
        ContextualClassification.PREPARATION_POSSIBLY_NEEDED,
    }
)
ALL_CONTEXTUAL_CLASSIFICATIONS = tuple(ContextualClassification)


class SensitivityTier(StrEnum):
    """Conservative deterministic sensitivity result."""

    TIER_1 = "tier_1_ordinary_operational"
    TIER_2 = "tier_2_heightened"
    TIER_3 = "tier_3_highly_sensitive"
    UNKNOWN = "unknown_or_ambiguous"
    MIXED = "mixed_sensitivity"
    INELIGIBLE_CREDENTIAL_MATERIAL = "prohibited_secret"


class Uncertainty(StrEnum):
    """Categorical uncertainty carried into policy validation."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    UNKNOWN = "unknown"


class InclusionRecommendation(StrEnum):
    """Whether a validated result should become a briefing candidate."""

    INCLUDE = "include"
    EXCLUDE = "exclude"


class InferenceStatus(StrEnum):
    """Provider-neutral completion and inability states."""

    COMPLETED = "completed"
    REFUSED = "refused"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class ValidationStatus(StrEnum):
    """Deterministic result-validation outcome."""

    ACCEPTED = "accepted"
    SCHEMA_REJECTED = "schema_rejected"
    PROVENANCE_REJECTED = "provenance_rejected"
    POLICY_REJECTED = "policy_rejected"


class ReducedModeReason(StrEnum):
    """Why contextual inference did not produce a briefing candidate."""

    DISABLED = "hosted_inference_disabled"
    DETERMINISTIC_BYPASS = "deterministic_result_authoritative"
    INSUFFICIENT_INPUT = "insufficient_deterministic_evidence"
    SENSITIVITY_EXCLUDED = "sensitivity_excluded"
    CREDENTIAL_MATERIAL_EXCLUDED = "secret_prohibited"
    CORRECTION_SUPPRESSED = "local_correction_suppressed"
    CONFIGURATION_MISSING = "approved_configuration_missing"
    CREDENTIAL_UNAVAILABLE = "keychain_credential_unavailable"
    PROVIDER_REFUSAL = "provider_refusal"
    PROVIDER_TIMEOUT = "provider_timeout"
    RATE_LIMITED = "provider_rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    SCHEMA_REJECTED = "provider_schema_rejected"
    PROVENANCE_REJECTED = "provider_provenance_rejected"
    POLICY_REJECTED = "provider_policy_rejected"


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    """One local evidence fragment before deterministic minimization."""

    reference_id: str
    source: str
    source_record_id: str
    content: str = field(repr=False)
    relevant: bool = True
    attachment: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("evidence reference", self.reference_id),
            ("source", self.source),
            ("source record ID", self.source_record_id),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be empty")


@dataclass(frozen=True, slots=True)
class InferenceCandidate:
    """One deterministic candidate offered to the inference coordinator."""

    id: str
    resolution: CandidateResolution
    evidence_fingerprint: str
    evidence: tuple[CandidateEvidence, ...]
    allowed_classifications: tuple[ContextualClassification, ...] = (
        ALL_CONTEXTUAL_CLASSIFICATIONS
    )

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.evidence_fingerprint.strip():
            raise ValueError("candidate ID and evidence fingerprint are required")
        if not self.allowed_classifications:
            raise ValueError("candidate must allow at least one classification")


@dataclass(frozen=True, slots=True)
class MinimizedEvidence:
    """One bounded evidence fragment safe for an eligible provider request."""

    reference_id: str
    source: str
    content: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class SensitivityAssessment:
    """Inspectable eligibility decision without private content."""

    tier: SensitivityTier
    hosted_eligible: bool
    reason: str


@dataclass(frozen=True, slots=True)
class EvidencePacket:
    """Application-owned, one-candidate provider input."""

    candidate_id: str
    evidence_fingerprint: str
    evidence: tuple[MinimizedEvidence, ...]
    sensitivity: SensitivityAssessment
    total_characters: int
    allowed_classifications: tuple[ContextualClassification, ...]

    @property
    def evidence_reference_ids(self) -> tuple[str, ...]:
        """Return stable local references supplied to the model."""

        return tuple(item.reference_id for item in self.evidence)


@dataclass(frozen=True, slots=True)
class InferenceRequest:
    """Provider-neutral request with all behavior-affecting versions."""

    packet: EvidencePacket
    created_at: datetime
    task_name: str = INFERENCE_TASK_NAME
    task_version: str = INFERENCE_TASK_VERSION
    prompt_version: str = PROMPT_VERSION
    schema_version: str = SCHEMA_VERSION
    policy_version: str = POLICY_VERSION
    model_configuration_version: str = MODEL_CONFIGURATION_VERSION


@dataclass(frozen=True, slots=True)
class ProviderAuditMetadata:
    """Provider audit fields that contain no prompt or response content."""

    provider: str
    model_id: str
    request_count: int
    latency_ms: int


@dataclass(frozen=True, slots=True)
class UsageMetadata:
    """Provider usage and cost metadata without private content."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_microusd: int | None = None
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass(frozen=True, slots=True)
class InferenceResult:
    """Application-owned structured result after provider translation."""

    status: InferenceStatus
    classification: ContextualClassification
    evidence_reference_ids: tuple[str, ...]
    explanation: str
    uncertainty: Uncertainty
    recommendation: InclusionRecommendation
    task_version: str
    prompt_version: str
    schema_version: str
    policy_version: str
    model_configuration_version: str
    provider_audit: ProviderAuditMetadata
    usage: UsageMetadata


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Deterministic schema, provenance, and policy decision."""

    status: ValidationStatus
    errors: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        """Return whether every deterministic validator accepted the result."""

        return self.status is ValidationStatus.ACCEPTED


@dataclass(frozen=True, slots=True)
class BriefingInferenceCandidate:
    """Validated inferred content ready for a future briefing composer."""

    key: str
    classification: ContextualClassification
    statement: str
    explanation: str
    uncertainty: Uncertainty
    evidence_reference_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InferenceOutcome:
    """Complete path outcome, including honest deterministic fallback."""

    candidate_id: str
    result: InferenceResult | None
    validation: ValidationReport | None
    briefing_candidate: BriefingInferenceCandidate | None
    reduced_mode_reason: ReducedModeReason | None
    provider_invoked: bool


@dataclass(frozen=True, slots=True)
class InferenceAuditRecord:
    """Persistable non-content metadata for one attempted or skipped task."""

    id: str
    candidate_id_hash: str
    task_name: str
    task_version: str
    prompt_version: str
    schema_version: str
    policy_version: str
    model_configuration_version: str
    provider: str
    model_id: str
    sensitivity_tier: SensitivityTier
    status: InferenceStatus
    validation_status: ValidationStatus | None
    request_count: int
    latency_ms: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_microusd: int | None
    error_category: str | None
    created_at: datetime
    briefing_run_id: str | None = None
