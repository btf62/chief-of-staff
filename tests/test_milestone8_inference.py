"""Synthetic trust, privacy, and lifecycle tests for Milestone 8."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from chief_of_staff.auth import KeychainSecretReference
from chief_of_staff.domain import (
    DispositionEvent,
    DispositionKind,
    SourceEvidence,
)
from chief_of_staff.inference.coordinator import ContextualInferenceCoordinator
from chief_of_staff.inference.evaluation import run_synthetic_inference_evaluation
from chief_of_staff.inference.evidence import (
    MAX_CHARACTERS_PER_ITEM,
    MAX_EVIDENCE_ITEMS,
    MAX_TOTAL_CHARACTERS,
    build_evidence_packet,
    stable_evidence_reference,
)
from chief_of_staff.inference.models import (
    ALL_CONTEXTUAL_CLASSIFICATIONS,
    CandidateEvidence,
    CandidateResolution,
    ContextualClassification,
    InclusionRecommendation,
    InferenceCandidate,
    InferenceRequest,
    InferenceResult,
    InferenceStatus,
    ProviderAuditMetadata,
    ReducedModeReason,
    SensitivityTier,
    Uncertainty,
    UsageMetadata,
    ValidationStatus,
)
from chief_of_staff.inference.policy import validate_inference_result
from chief_of_staff.inference.providers.base import (
    InferenceConfigurationError,
    InferenceCredentialError,
    InferenceDisabledError,
    InferenceModelMismatchError,
    InferenceSchemaError,
    InferenceTimeoutError,
)
from chief_of_staff.inference.providers.openai import (
    CONTEXTUAL_ACTION_RESULT_SCHEMA,
    OpenAIAdapterConfiguration,
    OpenAIResponsesAdapter,
    OpenAIRetentionStatus,
)
from chief_of_staff.inference.sensitivity import assess_sensitivity
from chief_of_staff.observability import StructuredJsonFormatter
from chief_of_staff.persistence import Database, StateStore

NOW = datetime(2026, 7, 29, 14, 0, tzinfo=UTC)
MODEL_CONFIGURATION_VERSION = "synthetic-mocked-v1"
PRIVATE_MARKER = "private-example-evidence-48391"
TEST_SECRET = "sk-test-only-secret-123456789"


class _RecordingProvider:
    provider_name = "synthetic_mock"

    def __init__(
        self,
        classification: ContextualClassification = (
            ContextualClassification.CONTEXTUAL_COMMITMENT
        ),
    ) -> None:
        self.classification = classification
        self.requests: list[InferenceRequest] = []

    def infer(self, request: InferenceRequest) -> InferenceResult:
        self.requests.append(request)
        recommendation = (
            InclusionRecommendation.EXCLUDE
            if self.classification
            in {
                ContextualClassification.NOT_ACTIONABLE,
                ContextualClassification.INSUFFICIENT_EVIDENCE,
            }
            else InclusionRecommendation.INCLUDE
        )
        return _result(
            request,
            self.classification,
            request.packet.evidence_reference_ids,
            recommendation=recommendation,
        )


class _TimeoutProvider:
    provider_name = "synthetic_timeout"

    def infer(self, _request: InferenceRequest) -> InferenceResult:
        raise InferenceTimeoutError("synthetic timeout")


class _FakeKeychain:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.read_count = 0

    def exists(self, _reference: KeychainSecretReference) -> bool:
        return self.available

    def read(self, _reference: KeychainSecretReference) -> str:
        self.read_count += 1
        return TEST_SECRET if self.available else ""


class _FakeResponsesTransport:
    def __init__(
        self,
        *,
        returned_model: str = "synthetic-model",
        output: Mapping[str, object] | None = None,
    ) -> None:
        self.returned_model = returned_model
        self.output = output
        self.calls: list[dict[str, object]] = []

    def create_response(
        self,
        *,
        endpoint: str,
        payload: Mapping[str, object],
        api_key: str,
        organization_id: str,
        project_id: str,
        timeout_seconds: float,
    ) -> Mapping[str, object]:
        self.calls.append(
            {
                "endpoint": endpoint,
                "payload": dict(payload),
                "api_key": api_key,
                "organization_id": organization_id,
                "project_id": project_id,
                "timeout_seconds": timeout_seconds,
            }
        )
        structured = self.output or {
            "classification": ContextualClassification.CONTEXTUAL_COMMITMENT.value,
            "evidence_reference_ids": [],
            "explanation": "One supplied reference supports a possible commitment.",
            "uncertainty": Uncertainty.LOW.value,
            "recommendation": InclusionRecommendation.INCLUDE.value,
        }
        return {
            "model": self.returned_model,
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(structured),
                        }
                    ],
                }
            ],
            "usage": {
                "input_tokens": 90,
                "output_tokens": 18,
                "total_tokens": 108,
            },
        }


def _candidate(
    *,
    name: str = "candidate-1",
    text: str = "A project review implies a deliverable.",
    resolution: CandidateResolution = CandidateResolution.UNRESOLVED_CONTEXTUAL,
    allowed: tuple[ContextualClassification, ...] = ALL_CONTEXTUAL_CLASSIFICATIONS,
) -> InferenceCandidate:
    reference = stable_evidence_reference("synthetic", name)
    return InferenceCandidate(
        id=name,
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


def _request(candidate: InferenceCandidate | None = None) -> InferenceRequest:
    selected = candidate or _candidate()
    return InferenceRequest(
        packet=build_evidence_packet(selected),
        created_at=NOW,
        model_configuration_version=MODEL_CONFIGURATION_VERSION,
    )


def _result(
    request: InferenceRequest,
    classification: ContextualClassification,
    references: tuple[str, ...],
    *,
    uncertainty: Uncertainty = Uncertainty.LOW,
    recommendation: InclusionRecommendation = InclusionRecommendation.INCLUDE,
) -> InferenceResult:
    return InferenceResult(
        status=InferenceStatus.COMPLETED,
        classification=classification,
        evidence_reference_ids=references,
        explanation="The supplied evidence supports this bounded classification.",
        uncertainty=uncertainty,
        recommendation=recommendation,
        task_version=request.task_version,
        prompt_version=request.prompt_version,
        schema_version=request.schema_version,
        policy_version=request.policy_version,
        model_configuration_version=request.model_configuration_version,
        provider_audit=ProviderAuditMetadata(
            provider="synthetic_mock",
            model_id="synthetic-model",
            request_count=1,
            latency_ms=1,
        ),
        usage=UsageMetadata(
            input_tokens=90,
            output_tokens=18,
            total_tokens=108,
        ),
    )


def _adapter_configuration(
    *,
    live_use_approved: bool = True,
) -> OpenAIAdapterConfiguration:
    return OpenAIAdapterConfiguration(
        enabled=True,
        live_use_approved=live_use_approved,
        organization_id="org-synthetic",
        project_id="proj-synthetic",
        model_id="synthetic-model",
        model_configuration_version=MODEL_CONFIGURATION_VERSION,
        retention_status=OpenAIRetentionStatus.STANDARD,
        provider_policy_review_owner="synthetic-owner",
        prompt_cache_policy_reviewed=True,
        api_key_reference=KeychainSecretReference(
            service="chief-of-staff/openai-test",
            account="synthetic-evaluation-key",
        ),
        max_requests_per_run=1,
        timeout_seconds=20.0,
        max_output_tokens=500,
    )


def _approved_adapter(
    transport: _FakeResponsesTransport,
    *,
    keychain: _FakeKeychain | None = None,
    configuration: OpenAIAdapterConfiguration | None = None,
) -> OpenAIResponsesAdapter:
    return OpenAIResponsesAdapter(
        configuration or _adapter_configuration(),
        keychain=keychain or _FakeKeychain(),
        transport=transport,
    )


def test_milestone_7_is_recorded_as_complete_and_accepted() -> None:
    root = Path(__file__).parents[1]
    roadmap = (root / "docs/roadmap.md").read_text(encoding="utf-8")
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")

    milestone = roadmap.split(
        "## Milestone 7 — Explicit Commitment and Preparation Detection",
        maxsplit=1,
    )[1].split("## Milestone 8", maxsplit=1)[0]
    normalized_milestone = " ".join(milestone.split())
    assert "**Status:** Complete" in milestone
    assert "Brad reviewed the private evidence and briefing" in normalized_milestone
    assert "accepted the" in normalized_milestone
    assert "completing and accepting Milestone 7" in agents
    assert "did not use hosted inference" in normalized_milestone


def test_only_unresolved_candidates_reach_inference_boundary() -> None:
    provider = _RecordingProvider()
    coordinator = ContextualInferenceCoordinator(
        provider,
        enabled=True,
        model_configuration_version=MODEL_CONFIGURATION_VERSION,
    )

    explicit = coordinator.evaluate(
        _candidate(
            name="explicit",
            resolution=CandidateResolution.EXPLICIT_DETERMINISTIC,
        ),
        created_at=NOW,
    )
    insufficient = coordinator.evaluate(
        _candidate(
            name="insufficient",
            resolution=CandidateResolution.INSUFFICIENT_EVIDENCE,
        ),
        created_at=NOW,
    )
    unresolved = coordinator.evaluate(
        _candidate(name="unresolved"),
        created_at=NOW,
    )

    assert explicit.reduced_mode_reason is ReducedModeReason.DETERMINISTIC_BYPASS
    assert insufficient.reduced_mode_reason is ReducedModeReason.INSUFFICIENT_INPUT
    assert unresolved.briefing_candidate is not None
    assert not explicit.provider_invoked
    assert not insufficient.provider_invoked
    assert len(provider.requests) == 1


def test_evidence_packet_is_minimized_bounded_and_stably_referenced() -> None:
    evidence: list[CandidateEvidence] = []
    for index in range(5):
        record_id = f"record-{index}"
        evidence.append(
            CandidateEvidence(
                reference_id=stable_evidence_reference("gmail", record_id),
                source="gmail",
                source_record_id=record_id,
                content=(
                    "Project review with person@example.com "
                    f"https://example.invalid/?utm_source=test {PRIVATE_MARKER} "
                    + ("x" * 700)
                    + (
                        "\nOn July 1, Example Person wrote:"
                        "\nQuoted private history"
                        "\nThanks,\nSignature detail"
                    )
                ),
                attachment=index == 3,
                relevant=index != 4,
            )
        )
    candidate = InferenceCandidate(
        id="bounded-packet",
        resolution=CandidateResolution.UNRESOLVED_CONTEXTUAL,
        evidence_fingerprint="bounded-fingerprint",
        evidence=tuple(evidence),
    )

    packet = build_evidence_packet(candidate)

    assert 0 < len(packet.evidence) <= MAX_EVIDENCE_ITEMS
    assert packet.total_characters <= MAX_TOTAL_CHARACTERS
    assert all(len(item.content) <= MAX_CHARACTERS_PER_ITEM for item in packet.evidence)
    assert packet.evidence_reference_ids == tuple(
        stable_evidence_reference("gmail", f"record-{index}")
        for index in range(len(packet.evidence))
    )
    assert stable_evidence_reference("gmail", "record-0") == (
        stable_evidence_reference("gmail", "record-0")
    )
    minimized = " ".join(item.content for item in packet.evidence)
    assert "person@example.com" not in minimized
    assert "person_" in minimized
    assert "utm_source" not in minimized
    assert "Quoted private history" not in minimized
    assert "Signature detail" not in minimized


@pytest.mark.parametrize(
    ("text", "expected_tier"),
    [
        ("Pastoral correspondence requiring discretion.", SensitivityTier.TIER_2),
        ("Personnel-adjacent discussion.", SensitivityTier.TIER_2),
        ("A family situation.", SensitivityTier.TIER_2),
        ("A health matter.", SensitivityTier.TIER_2),
        ("A financial matter.", SensitivityTier.TIER_2),
        ("A crisis narrative.", SensitivityTier.TIER_3),
        ("A private matter.", SensitivityTier.UNKNOWN),
        ("An uncategorized observation.", SensitivityTier.UNKNOWN),
        ("A pastoral project meeting.", SensitivityTier.MIXED),
    ],
)
def test_non_tier_1_and_mixed_evidence_is_hosted_ineligible(
    text: str,
    expected_tier: SensitivityTier,
) -> None:
    assessment = assess_sensitivity((text,))

    assert assessment.tier is expected_tier
    assert not assessment.hosted_eligible


def test_ordinary_project_and_meeting_content_is_tier_1() -> None:
    assessment = assess_sensitivity(("Project meeting agenda and release review.",))

    assert assessment.tier is SensitivityTier.TIER_1
    assert assessment.hosted_eligible


@pytest.mark.parametrize(
    "text",
    [
        "api_key=sk-test-only-secret-123456789",
        "password: synthetic-secret",
        "access token abcdefghijklmnop",
        "-----BEGIN PRIVATE KEY-----",
    ],
)
def test_secret_like_material_is_always_prohibited(text: str) -> None:
    assessment = assess_sensitivity((text,))

    assert assessment.tier is SensitivityTier.INELIGIBLE_CREDENTIAL_MATERIAL
    assert not assessment.hosted_eligible


def test_provider_neutral_models_have_no_provider_objects_or_state_fields() -> None:
    domain_types = (
        InferenceCandidate,
        InferenceRequest,
        InferenceResult,
    )
    forbidden = ("openai", "response_id", "sdk", "tool_call", "conversation")

    for model in domain_types:
        field_descriptions = " ".join(
            f"{field.name}:{field.type!s}" for field in fields(model)
        ).casefold()
        assert all(value not in field_descriptions for value in forbidden)


def test_openai_adapter_is_disabled_and_cannot_reach_transport_by_default() -> None:
    transport = _FakeResponsesTransport()
    keychain = _FakeKeychain()
    adapter = OpenAIResponsesAdapter(
        OpenAIAdapterConfiguration(),
        keychain=keychain,
        transport=transport,
    )

    with pytest.raises(InferenceDisabledError):
        adapter.infer(_request())

    assert transport.calls == []
    assert keychain.read_count == 0
    assert adapter.request_count == 0


def test_unapproved_configuration_cannot_reach_transport() -> None:
    transport = _FakeResponsesTransport()
    adapter = _approved_adapter(
        transport,
        configuration=_adapter_configuration(live_use_approved=False),
    )

    with pytest.raises(InferenceConfigurationError, match="not approved"):
        adapter.infer(_request())

    assert transport.calls == []
    assert adapter.request_count == 0


def test_missing_keychain_credential_cannot_reach_transport() -> None:
    transport = _FakeResponsesTransport()
    keychain = _FakeKeychain(available=False)
    adapter = _approved_adapter(transport, keychain=keychain)

    with pytest.raises(InferenceCredentialError, match="unavailable"):
        adapter.infer(_request())

    assert transport.calls == []
    assert keychain.read_count == 0
    assert adapter.request_count == 0


def test_openai_payload_is_strict_stateless_tool_free_and_bounded() -> None:
    adapter = _approved_adapter(_FakeResponsesTransport())
    payload = adapter.build_payload(_request())
    text = cast(dict[str, object], payload["text"])
    format_value = cast(dict[str, object], text["format"])
    schema = cast(dict[str, object], format_value["schema"])
    properties = cast(dict[str, object], schema["properties"])

    assert payload["model"] == "synthetic-model"
    assert payload["store"] is False
    assert payload["background"] is False
    assert payload["tools"] == []
    assert payload["tool_choice"] == "none"
    assert payload["truncation"] == "disabled"
    assert payload["max_output_tokens"] == 500
    assert format_value["type"] == "json_schema"
    assert format_value["strict"] is True
    assert schema == CONTEXTUAL_ACTION_RESULT_SCHEMA
    assert schema["additionalProperties"] is False
    assert set(cast(list[str], schema["required"])) == set(properties)
    forbidden = {
        "previous_response_id",
        "conversation",
        "include",
        "file_ids",
        "vector_store_ids",
        "web_search",
        "mcp",
        "container",
        "memory",
    }
    assert forbidden.isdisjoint(payload)


def test_adapter_rejects_model_substitution_and_request_cap_without_fallback() -> None:
    mismatched = _approved_adapter(
        _FakeResponsesTransport(returned_model="unapproved-model")
    )
    with pytest.raises(InferenceModelMismatchError):
        mismatched.infer(_request())

    candidate = _candidate()
    request = _request(candidate)
    transport = _FakeResponsesTransport(
        output={
            "classification": ContextualClassification.NOT_ACTIONABLE.value,
            "evidence_reference_ids": [request.packet.evidence_reference_ids[0]],
            "explanation": "The supplied material is not actionable.",
            "uncertainty": Uncertainty.LOW.value,
            "recommendation": InclusionRecommendation.EXCLUDE.value,
        }
    )
    adapter = _approved_adapter(transport)
    assert adapter.infer(request).classification is (
        ContextualClassification.NOT_ACTIONABLE
    )
    with pytest.raises(InferenceConfigurationError, match="cap is exhausted"):
        adapter.infer(request)
    assert len(transport.calls) == 1


def test_malformed_adapter_output_is_rejected_without_a_candidate() -> None:
    candidate = _candidate(name="malformed")
    transport = _FakeResponsesTransport(output={"classification": "not_actionable"})
    adapter = _approved_adapter(transport)

    with pytest.raises(InferenceSchemaError):
        adapter.infer(_request(candidate))

    coordinator_transport = _FakeResponsesTransport(
        output={"classification": "not_actionable"}
    )
    outcome = ContextualInferenceCoordinator(
        _approved_adapter(coordinator_transport),
        enabled=True,
        model_configuration_version=MODEL_CONFIGURATION_VERSION,
    ).evaluate(candidate, created_at=NOW)

    assert outcome.reduced_mode_reason is ReducedModeReason.SCHEMA_REJECTED
    assert outcome.briefing_candidate is None
    assert outcome.validation is not None
    assert outcome.validation.status is ValidationStatus.SCHEMA_REJECTED


def test_validation_rejects_invented_references_and_policy_conflicts() -> None:
    request = _request()
    invented = _result(
        request,
        ContextualClassification.PERSON_POSSIBLY_WAITING,
        ("ev_invented",),
    )
    provenance = validate_inference_result(request, invented)

    policy_request = _request(
        _candidate(
            name="policy",
            allowed=(ContextualClassification.NOT_ACTIONABLE,),
        )
    )
    policy_conflict = _result(
        policy_request,
        ContextualClassification.CONTEXTUAL_COMMITMENT,
        policy_request.packet.evidence_reference_ids,
    )
    policy = validate_inference_result(policy_request, policy_conflict)

    assert provenance.status is ValidationStatus.PROVENANCE_REJECTED
    assert policy.status is ValidationStatus.POLICY_REJECTED


def test_provider_timeout_produces_honest_reduced_mode() -> None:
    outcome = ContextualInferenceCoordinator(
        _TimeoutProvider(),
        enabled=True,
        model_configuration_version=MODEL_CONFIGURATION_VERSION,
    ).evaluate(_candidate(), created_at=NOW)

    assert outcome.reduced_mode_reason is ReducedModeReason.PROVIDER_TIMEOUT
    assert outcome.briefing_candidate is None
    assert outcome.provider_invoked


def test_mocked_adapter_validation_persistence_correction_and_logging(
    tmp_path: Path,
) -> None:
    candidate = _candidate(
        name="complete-path",
        text=f"A project review implies a deliverable. {PRIVATE_MARKER}",
    )
    request = _request(candidate)
    transport = _FakeResponsesTransport(
        output={
            "classification": ContextualClassification.CONTEXTUAL_COMMITMENT.value,
            "evidence_reference_ids": list(request.packet.evidence_reference_ids),
            "explanation": "One supplied reference supports a possible commitment.",
            "uncertainty": Uncertainty.LOW.value,
            "recommendation": InclusionRecommendation.INCLUDE.value,
        }
    )
    adapter = _approved_adapter(transport)
    log_path = tmp_path / "inference.log"
    logger = logging.getLogger(f"test.inference.{id(transport)}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(StructuredJsonFormatter())
    logger.addHandler(handler)

    try:
        with Database.open(tmp_path / "state.sqlite3") as database:
            store = StateStore(database)
            reference = candidate.evidence[0].reference_id
            store.add_source_evidence(
                SourceEvidence(
                    id=reference,
                    connector_run_id=None,
                    source="synthetic",
                    source_record_id="complete-path",
                    evidence_fingerprint=candidate.evidence_fingerprint,
                    retrieved_at=NOW,
                    excerpt=None,
                )
            )
            coordinator = ContextualInferenceCoordinator(
                adapter,
                enabled=True,
                state_store=store,
                logger=logger,
                model_configuration_version=MODEL_CONFIGURATION_VERSION,
            )

            outcome = coordinator.evaluate(candidate, created_at=NOW)

            assert outcome.briefing_candidate is not None
            assert outcome.validation is not None
            assert outcome.validation.status is ValidationStatus.ACCEPTED
            assert store.inspect_state().inference_audits == 1
            conclusion_row = database.connection.execute(
                "SELECT id, classification, statement, explanation FROM conclusions"
            ).fetchone()
            assert conclusion_row is not None
            assert conclusion_row["classification"] == "inferred"
            assert PRIVATE_MARKER not in " ".join(
                str(value) for value in conclusion_row
            )

            columns = {
                str(row["name"])
                for row in database.connection.execute(
                    "PRAGMA table_info(inference_audits)"
                )
            }
            assert {
                "prompt",
                "response",
                "excerpt",
                "credential",
                "api_key",
            }.isdisjoint(columns)
            audit_row = database.connection.execute(
                "SELECT * FROM inference_audits"
            ).fetchone()
            assert audit_row is not None
            serialized_audit = " ".join(str(value) for value in audit_row)
            assert PRIVATE_MARKER not in serialized_audit
            assert TEST_SECRET not in serialized_audit

            conclusion_id = str(conclusion_row["id"])
            store.append_disposition(
                DispositionEvent(
                    id="dismiss-complete-path",
                    conclusion_id=conclusion_id,
                    disposition=DispositionKind.DISMISSED,
                    created_at=NOW + timedelta(seconds=1),
                )
            )
            repeated = coordinator.evaluate(
                candidate,
                created_at=NOW + timedelta(seconds=2),
            )
            assert repeated.reduced_mode_reason is (
                ReducedModeReason.CORRECTION_SUPPRESSED
            )
            assert repeated.briefing_candidate is None
            assert adapter.request_count == 1
            assert len(transport.calls) == 1
            assert store.inspect_state().inference_audits == 2
            assert store.prune_inference_audits(NOW + timedelta(days=31)) == 2
            assert store.inspect_state().inference_audits == 0
    finally:
        logger.removeHandler(handler)
        handler.close()

    log_text = log_path.read_text(encoding="utf-8")
    assert PRIVATE_MARKER not in log_text
    assert TEST_SECRET not in log_text
    assert "inference.contextual_action" in log_text


def test_mocked_evaluation_gate_has_no_trust_regressions() -> None:
    report = run_synthetic_inference_evaluation()

    assert report.total_scenarios == 25
    assert report.true_positives == 3
    assert report.false_positives == 0
    assert report.false_negatives == 0
    assert report.correct_exclusions == 5
    assert report.insufficient_evidence_results == 3
    assert report.sensitivity_exclusions == 4
    assert report.schema_failures == 1
    assert report.provenance_failures == 1
    assert report.policy_failures == 1
    assert report.correction_regressions == 0
    assert report.provider_failure_fallbacks == 4
    assert report.deterministic_reduced_results == 2
    assert report.passed
