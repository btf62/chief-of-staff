"""Bounded live-transport and synthetic-comparison tests for Milestone 8."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

import chief_of_staff.inference.providers.openai as openai_provider
from chief_of_staff.auth import KeychainSecretReference
from chief_of_staff.inference.evidence import build_evidence_packet
from chief_of_staff.inference.live_evaluation import (
    APPROVED_PROJECT_NAME,
    LIVE_CALL_CAP,
    TRIAL_COST_CAP_MICROUSD,
    LiveEvaluationScenario,
    TrialBoundaryError,
    TrialCostBoundary,
    live_evaluation_scenarios,
    maximum_request_cost_microusd,
    run_live_comparison,
    validate_live_scenario,
    write_private_report,
)
from chief_of_staff.inference.models import (
    ContextualClassification,
    InclusionRecommendation,
    InferenceRequest,
    SensitivityTier,
    Uncertainty,
)
from chief_of_staff.inference.providers.base import (
    InferenceConfigurationError,
    InferenceProviderPolicyError,
)
from chief_of_staff.inference.providers.openai import (
    OPENAI_API_KEY_REFERENCE,
    OPENAI_EVALUATION_MODELS,
    OPENAI_MAX_OUTPUT_TOKENS,
    OPENAI_RESPONSES_ENDPOINT,
    OpenAIAdapterConfiguration,
    OpenAIResponsesAdapter,
    OpenAIRetentionStatus,
    OpenAISDKResponsesTransport,
)
from chief_of_staff.openai_evaluation_cli import (
    PrivateProviderConfiguration,
    comparison_passed,
    store_key_from_clipboard,
)
from chief_of_staff.persistence import Database

TEST_SECRET = "sk-proj-synthetic-only-credential"
ORGANIZATION_ID = "org-synthetic"
PROJECT_ID = "proj-synthetic"


class _FakeKeychain:
    def __init__(self) -> None:
        self.references: list[KeychainSecretReference] = []
        self.stored: tuple[KeychainSecretReference, str] | None = None

    def exists(self, reference: KeychainSecretReference) -> bool:
        self.references.append(reference)
        return True

    def read(self, reference: KeychainSecretReference) -> str:
        self.references.append(reference)
        return TEST_SECRET

    def store(self, reference: KeychainSecretReference, secret: str) -> None:
        self.stored = (reference, secret)


class _SyntheticLiveTransport:
    def __init__(self, *, cache_write_tokens: int = 0) -> None:
        self.cache_write_tokens = cache_write_tokens
        self.calls: list[dict[str, object]] = []
        self.expected = {
            scenario.candidate.id: scenario.expected_classification
            for scenario in live_evaluation_scenarios()
        }

    def create_response(
        self,
        *,
        endpoint: str,
        payload: Mapping[str, object],
        api_key: str,
        organization_id: str,
        project_id: str,
        timeout_seconds: float,
    ) -> dict[str, object]:
        selected = dict(payload)
        self.calls.append(
            {
                "endpoint": endpoint,
                "payload": selected,
                "credential_matches": api_key == TEST_SECRET,
                "organization_matches": organization_id == ORGANIZATION_ID,
                "project_matches": project_id == PROJECT_ID,
                "timeout_seconds": timeout_seconds,
            }
        )
        task_input = json.loads(cast(str, selected["input"]))
        candidate_id = cast(str, task_input["candidate_id"])
        classification = self.expected[candidate_id]
        evidence = cast(list[dict[str, str]], task_input["evidence"])
        references = [item["reference_id"] for item in evidence]
        recommendation = (
            InclusionRecommendation.INCLUDE
            if classification
            in {
                ContextualClassification.CONTEXTUAL_COMMITMENT,
                ContextualClassification.PERSON_POSSIBLY_WAITING,
                ContextualClassification.PREPARATION_POSSIBLY_NEEDED,
            }
            else InclusionRecommendation.EXCLUDE
        )
        return {
            "status": "completed",
            "model": selected["model"],
            "output": [
                {
                    "id": "provider-message-id-must-not-persist",
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "classification": classification.value,
                                    "evidence_reference_ids": references,
                                    "explanation": (
                                        "The supplied synthetic evidence supports "
                                        "this bounded classification."
                                    ),
                                    "uncertainty": Uncertainty.LOW.value,
                                    "recommendation": recommendation.value,
                                }
                            ),
                        }
                    ],
                }
            ],
            "usage": {
                "input_tokens": 220,
                "output_tokens": 48,
                "total_tokens": 268,
                "input_tokens_details": {
                    "cached_tokens": 0,
                    "cache_write_tokens": self.cache_write_tokens,
                },
                "output_tokens_details": {"reasoning_tokens": 12},
            },
            "service_tier": "default",
            "store": False,
            "background": False,
        }


class _SDKResponse:
    def __init__(self, raw: dict[str, object]) -> None:
        self.raw = raw

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return self.raw


class _SDKClient:
    def __init__(self, response: _SDKResponse) -> None:
        self.response = response
        self.responses = self
        self.payloads: list[dict[str, object]] = []

    def __enter__(self) -> _SDKClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return

    def create(self, **payload: object) -> _SDKResponse:
        self.payloads.append(payload)
        return self.response


class _SDKFactory:
    def __init__(self, client: _SDKClient) -> None:
        self.client = client
        self.arguments: list[dict[str, object]] = []

    def __call__(self, **arguments: object) -> _SDKClient:
        self.arguments.append(arguments)
        return self.client


def _configuration(
    *,
    model: str = "gpt-5.6-terra",
    reference: KeychainSecretReference = OPENAI_API_KEY_REFERENCE,
) -> OpenAIAdapterConfiguration:
    return OpenAIAdapterConfiguration(
        enabled=True,
        live_use_approved=True,
        organization_id=ORGANIZATION_ID,
        project_id=PROJECT_ID,
        model_id=model,
        model_configuration_version=f"m8-live-comparison-v1:{model}:low",
        retention_status=OpenAIRetentionStatus.STANDARD,
        provider_policy_review_owner="Brad",
        prompt_cache_policy_reviewed=True,
        api_key_reference=reference,
        max_requests_per_run=10,
        timeout_seconds=20.0,
        max_output_tokens=OPENAI_MAX_OUTPUT_TOKENS,
    )


def _request(
    scenario: LiveEvaluationScenario,
    model: str = "gpt-5.6-terra",
) -> InferenceRequest:
    return InferenceRequest(
        packet=build_evidence_packet(scenario.candidate),
        created_at=datetime.now(UTC),
        model_configuration_version=f"m8-live-comparison-v1:{model}:low",
    )


def test_official_sdk_transport_uses_exact_client_safety_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = {
        "status": "completed",
        "model": "gpt-5.6-terra",
        "output": [
            {
                "id": "provider-id",
                "type": "message",
                "content": [{"type": "output_text", "text": "{}"}],
            }
        ],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        "service_tier": "default",
        "store": False,
        "background": False,
        "id": "response-id",
    }
    client = _SDKClient(_SDKResponse(raw))
    factory = _SDKFactory(client)
    monkeypatch.setattr(openai_provider, "OpenAI", factory)
    payload = {"model": "gpt-5.6-terra", "input": "synthetic"}

    projected = OpenAISDKResponsesTransport().create_response(
        endpoint=OPENAI_RESPONSES_ENDPOINT,
        payload=payload,
        api_key=TEST_SECRET,
        organization_id=ORGANIZATION_ID,
        project_id=PROJECT_ID,
        timeout_seconds=20.0,
    )

    assert factory.arguments == [
        {
            "api_key": TEST_SECRET,
            "organization": ORGANIZATION_ID,
            "project": PROJECT_ID,
            "max_retries": 0,
            "timeout": 20.0,
        }
    ]
    assert client.payloads == [payload]
    assert "id" not in projected
    assert "provider-id" not in json.dumps(projected)


def test_payload_is_strict_stateless_non_pro_and_cache_write_free() -> None:
    scenario = live_evaluation_scenarios()[0]
    adapter = OpenAIResponsesAdapter(
        _configuration(),
        keychain=_FakeKeychain(),
        transport=_SyntheticLiveTransport(),
    )
    payload = adapter.build_payload(_request(scenario))

    assert payload["store"] is False
    assert payload["background"] is False
    assert payload["stream"] is False
    assert payload["tools"] == []
    assert payload["tool_choice"] == "none"
    assert payload["service_tier"] == "default"
    assert payload["reasoning"] == {
        "effort": "low",
        "context": "current_turn",
        "mode": "standard",
    }
    assert payload["prompt_cache_options"] == {"mode": "explicit"}
    assert "previous_response_id" not in payload
    assert "conversation" not in payload
    assert "include" not in payload
    text = cast(dict[str, object], payload["text"])
    output_format = cast(dict[str, object], text["format"])
    assert output_format["type"] == "json_schema"
    assert output_format["strict"] is True


@pytest.mark.parametrize("model", OPENAI_EVALUATION_MODELS)
def test_only_approved_models_and_explicit_project_configuration_reach_transport(
    model: str,
) -> None:
    scenario = live_evaluation_scenarios()[0]
    transport = _SyntheticLiveTransport()
    keychain = _FakeKeychain()
    adapter = OpenAIResponsesAdapter(
        _configuration(model=model),
        keychain=keychain,
        transport=transport,
    )

    result = adapter.infer(_request(scenario, model))

    assert result.provider_audit.model_id == model
    assert transport.calls[0]["organization_matches"] is True
    assert transport.calls[0]["project_matches"] is True
    assert all(
        reference == OPENAI_API_KEY_REFERENCE for reference in keychain.references
    )


def test_unapproved_model_and_keychain_reference_fail_before_transport() -> None:
    scenario = live_evaluation_scenarios()[0]
    transport = _SyntheticLiveTransport()
    wrong_reference = KeychainSecretReference("wrong-service", "wrong-account")

    for configuration in (
        _configuration(model="gpt-5.6-sol"),
        _configuration(reference=wrong_reference),
    ):
        adapter = OpenAIResponsesAdapter(
            configuration,
            keychain=_FakeKeychain(),
            transport=transport,
        )
        with pytest.raises(InferenceConfigurationError):
            adapter.infer(
                _request(
                    scenario,
                    cast(str, configuration.model_id),
                )
            )

    assert transport.calls == []


def test_provider_cache_activity_is_rejected_as_policy_violation() -> None:
    scenario = live_evaluation_scenarios()[0]
    adapter = OpenAIResponsesAdapter(
        _configuration(),
        keychain=_FakeKeychain(),
        transport=_SyntheticLiveTransport(cache_write_tokens=1),
    )

    with pytest.raises(InferenceProviderPolicyError):
        adapter.infer(_request(scenario))


def test_models_receive_identical_non_model_payloads_and_exactly_twenty_calls(
    tmp_path: Path,
) -> None:
    transport = _SyntheticLiveTransport()
    keychain = _FakeKeychain()

    report = run_live_comparison(
        organization_id=ORGANIZATION_ID,
        project_id=PROJECT_ID,
        retention_status=OpenAIRetentionStatus.STANDARD,
        audit_database_path=tmp_path / "audits.sqlite3",
        keychain=keychain,
        transport=transport,
    )

    assert len(transport.calls) == LIVE_CALL_CAP
    models = [
        cast(dict[str, object], call["payload"])["model"] for call in transport.calls
    ]
    assert models[:10] == ["gpt-5.6-terra"] * 10
    assert models[10:] == ["gpt-5.6-luna"] * 10
    for index in range(10):
        terra = dict(cast(dict[str, object], transport.calls[index]["payload"]))
        luna = dict(cast(dict[str, object], transport.calls[index + 10]["payload"]))
        terra.pop("model")
        luna.pop("model")
        assert terra == luna
    assert all(item.metrics.attempted_calls == 10 for item in report.evaluations)
    assert all(item.metrics.completed_calls == 10 for item in report.evaluations)
    assert all(item.metrics.false_positives == 0 for item in report.evaluations)
    assert all(item.metrics.cache_write_tokens == 0 for item in report.evaluations)
    assert not report.production_model_selected
    assert comparison_passed(report)


def test_fail_closed_policy_rejections_do_not_fail_the_live_trust_gate(
    tmp_path: Path,
) -> None:
    report = run_live_comparison(
        organization_id=ORGANIZATION_ID,
        project_id=PROJECT_ID,
        retention_status=OpenAIRetentionStatus.STANDARD,
        audit_database_path=tmp_path / "audits.sqlite3",
        keychain=_FakeKeychain(),
        transport=_SyntheticLiveTransport(),
    )
    first_evaluation = report.evaluations[0]
    first_scenario = first_evaluation.scenarios[0]
    safely_rejected = replace(
        first_scenario,
        validation_status="policy_rejected",
        reduced_mode_reason="provider_policy_rejected",
    )
    safe_report = replace(
        report,
        evaluations=(
            replace(
                first_evaluation,
                metrics=replace(first_evaluation.metrics, policy_failures=1),
                scenarios=(safely_rejected, *first_evaluation.scenarios[1:]),
            ),
            report.evaluations[1],
        ),
    )

    assert comparison_passed(safe_report)

    incorrectly_accepted = replace(safely_rejected, validation_status="accepted")
    unsafe_report = replace(
        safe_report,
        evaluations=(
            replace(
                safe_report.evaluations[0],
                scenarios=(
                    incorrectly_accepted,
                    *safe_report.evaluations[0].scenarios[1:],
                ),
            ),
            safe_report.evaluations[1],
        ),
    )
    assert not comparison_passed(unsafe_report)


def test_only_tier_1_synthetic_evidence_is_live_eligible() -> None:
    scenarios = live_evaluation_scenarios()

    assert len(scenarios) == 10
    for scenario in scenarios:
        validate_live_scenario(scenario)
        assert build_evidence_packet(scenario.candidate).sensitivity.tier is (
            SensitivityTier.TIER_1
        )


@pytest.mark.parametrize(
    "text",
    [
        "A pastoral project review.",
        "A crisis narrative about a project.",
        "A private matter involving a project.",
        "A family project meeting.",
        "Project api_key=sk-synthetic123456789.",
    ],
)
def test_ineligible_or_secret_evidence_fails_before_live_transport(text: str) -> None:
    baseline = live_evaluation_scenarios()[0]
    evidence = replace(baseline.candidate.evidence[0], content=text)
    scenario = replace(
        baseline,
        candidate=replace(baseline.candidate, evidence=(evidence,)),
    )

    with pytest.raises(TrialBoundaryError):
        validate_live_scenario(scenario)


def test_gmail_live_identifiers_email_addresses_and_attachments_are_rejected() -> None:
    baseline = live_evaluation_scenarios()[0]
    variants = (
        replace(
            baseline.candidate.evidence[0],
            source="gmail",
            source_record_id="gmail-live-message",
        ),
        replace(
            baseline.candidate.evidence[0],
            content="Project review requested from person@example.com.",
        ),
        replace(baseline.candidate.evidence[0], attachment=True),
        replace(
            baseline.candidate.evidence[0],
            content="Project review.\n> Quoted history",
        ),
    )

    for evidence in variants:
        scenario = replace(
            baseline,
            candidate=replace(baseline.candidate, evidence=(evidence,)),
        )
        with pytest.raises(TrialBoundaryError):
            validate_live_scenario(scenario)


def test_application_call_and_cost_boundaries_fail_closed() -> None:
    boundary = TrialCostBoundary(
        call_cap=2,
        cost_cap_microusd=100,
    )
    boundary.approve_next(60)
    boundary.record_result(maximum_cost_microusd=60, actual_cost_microusd=40)
    boundary.approve_next(60)
    boundary.record_result(maximum_cost_microusd=60, actual_cost_microusd=None)

    with pytest.raises(TrialBoundaryError, match="twenty-call"):
        boundary.approve_next(1)

    cost_boundary = TrialCostBoundary(call_cap=20, cost_cap_microusd=100)
    cost_boundary.approve_next(80)
    cost_boundary.record_result(maximum_cost_microusd=80, actual_cost_microusd=80)
    with pytest.raises(TrialBoundaryError, match="one-dollar"):
        cost_boundary.approve_next(21)


def test_preflight_twenty_call_maximum_is_below_one_dollar() -> None:
    maximum = 0
    for model in OPENAI_EVALUATION_MODELS:
        adapter = OpenAIResponsesAdapter(
            _configuration(model=model),
            keychain=_FakeKeychain(),
            transport=_SyntheticLiveTransport(),
        )
        for scenario in live_evaluation_scenarios():
            maximum += maximum_request_cost_microusd(
                model,
                adapter.build_payload(_request(scenario, model)),
            )

    assert maximum < TRIAL_COST_CAP_MICROUSD


def test_live_audits_are_non_content_and_private_report_is_mode_0600(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "audits.sqlite3"
    report_path = tmp_path / "comparison.json"
    report = run_live_comparison(
        organization_id=ORGANIZATION_ID,
        project_id=PROJECT_ID,
        retention_status=OpenAIRetentionStatus.STANDARD,
        audit_database_path=database_path,
        keychain=_FakeKeychain(),
        transport=_SyntheticLiveTransport(),
    )
    write_private_report(report, report_path)

    assert report_path.stat().st_mode & 0o777 == 0o600
    report_text = report_path.read_text(encoding="utf-8")
    assert "provider-message-id-must-not-persist" not in report_text
    assert ORGANIZATION_ID not in report_text
    assert PROJECT_ID not in report_text
    assert TEST_SECRET not in report_text
    with Database.open(database_path) as database:
        rows = database.connection.execute("SELECT * FROM inference_audits").fetchall()
        columns = {
            str(row["name"])
            for row in database.connection.execute(
                "PRAGMA table_info(inference_audits)"
            )
        }
    assert len(rows) == LIVE_CALL_CAP
    assert {"prompt", "response", "evidence", "api_key"}.isdisjoint(columns)
    serialized = json.dumps([tuple(row) for row in rows])
    assert "revised project checklist" not in serialized
    assert TEST_SECRET not in serialized


def test_clipboard_import_uses_only_approved_keychain_item_and_always_clears() -> None:
    keychain = _FakeKeychain()
    cleared: list[bool] = []

    store_key_from_clipboard(
        keychain=keychain,
        read_clipboard=lambda: TEST_SECRET,
        clear_clipboard=lambda: cleared.append(True),
    )

    assert keychain.stored == (OPENAI_API_KEY_REFERENCE, TEST_SECRET)
    assert cleared == [True]

    with pytest.raises(RuntimeError):
        store_key_from_clipboard(
            keychain=keychain,
            read_clipboard=lambda: "not-a-key",
            clear_clipboard=lambda: cleared.append(True),
        )
    assert cleared == [True, True]


def test_private_configuration_requires_exact_project_ownership_and_billing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "configuration.json"
    value = {
        "project_name": APPROVED_PROJECT_NAME,
        "organization_id": ORGANIZATION_ID,
        "project_id": PROJECT_ID,
        "organization_ownership": "northridge_controlled",
        "project_ownership": "Brad",
        "billing_availability": "active_existing",
        "billing_source": "existing_organization_billing",
        "retention_status": "standard",
        "model_access": ["gpt-5.6-terra", "gpt-5.6-luna"],
        "api_access": "responses_only",
        "service_account_name": "chief-of-staff-local",
        "provider_policy_review_owner": "Brad",
        "spend_control": "hard_limit",
        "configured_at": "2026-07-29T12:00:00-04:00",
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)

    configuration = PrivateProviderConfiguration.load(path)

    assert configuration.project_name == APPROVED_PROJECT_NAME
    assert configuration.organization_ownership == "northridge_controlled"
    assert configuration.billing_availability == "active_existing"
    assert configuration.model_access == ["gpt-5.6-terra", "gpt-5.6-luna"]
    assert configuration.api_access == "responses_only"
