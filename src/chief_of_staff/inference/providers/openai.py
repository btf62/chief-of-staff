"""Disabled-by-default OpenAI Responses API adapter."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, Protocol, cast

import openai
from openai import OpenAI

from chief_of_staff.auth import KeychainSecretReference
from chief_of_staff.inference.models import (
    INFERENCE_TASK_NAME,
    MAX_EXPLANATION_CHARACTERS,
    MODEL_CONFIGURATION_VERSION,
    ContextualClassification,
    InclusionRecommendation,
    InferenceRequest,
    InferenceResult,
    InferenceStatus,
    ProviderAuditMetadata,
    Uncertainty,
    UsageMetadata,
)
from chief_of_staff.inference.providers.base import (
    InferenceConfigurationError,
    InferenceCredentialError,
    InferenceDisabledError,
    InferenceModelMismatchError,
    InferenceProviderPolicyError,
    InferenceRateLimitError,
    InferenceRefusalError,
    InferenceSchemaError,
    InferenceTimeoutError,
    InferenceUnavailableError,
)

OPENAI_RESPONSES_ENDPOINT: Final = "https://api.openai.com/v1/responses"
OPENAI_PROVIDER_NAME: Final = "openai"
OPENAI_EVALUATION_MODELS: Final = (
    "gpt-5.6-terra",
    "gpt-5.6-luna",
)
OPENAI_SELECTED_CONTEXTUAL_ACTION_MODEL: Final = "gpt-5.6-luna"
OPENAI_API_KEY_REFERENCE: Final = KeychainSecretReference(
    service="chief-of-staff/openai",
    account="milestone-8-evaluation-api-key",
)
OPENAI_REASONING_EFFORT: Final = "low"
OPENAI_SERVICE_TIER: Final = "default"
OPENAI_PROMPT_CACHE_MODE: Final = "explicit"
OPENAI_MAX_OUTPUT_TOKENS: Final = 500


@dataclass(frozen=True, slots=True)
class OpenAITaskModelSelection:
    """Reviewed task-specific model choice without enabling provider access."""

    task_name: str
    provider: str
    model_id: str
    reasoning_effort: str
    endpoint: str
    model_configuration_version: str
    enabled_by_default: bool


OPENAI_TASK_MODEL_SELECTIONS: Final = MappingProxyType(
    {
        INFERENCE_TASK_NAME: OpenAITaskModelSelection(
            task_name=INFERENCE_TASK_NAME,
            provider=OPENAI_PROVIDER_NAME,
            model_id=OPENAI_SELECTED_CONTEXTUAL_ACTION_MODEL,
            reasoning_effort=OPENAI_REASONING_EFFORT,
            endpoint=OPENAI_RESPONSES_ENDPOINT,
            model_configuration_version=MODEL_CONFIGURATION_VERSION,
            enabled_by_default=False,
        )
    }
)


@dataclass(frozen=True, slots=True)
class OpenAIModelPricing:
    """Standard short-context prices expressed as micro-USD per token."""

    input_microusd_per_token: Decimal
    cached_input_microusd_per_token: Decimal
    cache_write_microusd_per_token: Decimal
    output_microusd_per_token: Decimal


OPENAI_EVALUATION_PRICING: Final[dict[str, OpenAIModelPricing]] = {
    "gpt-5.6-terra": OpenAIModelPricing(
        input_microusd_per_token=Decimal("2.50"),
        cached_input_microusd_per_token=Decimal("0.25"),
        cache_write_microusd_per_token=Decimal("3.125"),
        output_microusd_per_token=Decimal("15.00"),
    ),
    "gpt-5.6-luna": OpenAIModelPricing(
        input_microusd_per_token=Decimal("1.00"),
        cached_input_microusd_per_token=Decimal("0.10"),
        cache_write_microusd_per_token=Decimal("1.25"),
        output_microusd_per_token=Decimal("6.00"),
    ),
}
CONTEXTUAL_ACTION_RESULT_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "classification": {
            "type": "string",
            "enum": [item.value for item in ContextualClassification],
        },
        "evidence_reference_ids": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 3,
        },
        "explanation": {"type": "string"},
        "uncertainty": {
            "type": "string",
            "enum": [item.value for item in Uncertainty],
        },
        "recommendation": {
            "type": "string",
            "enum": [item.value for item in InclusionRecommendation],
        },
    },
    "required": [
        "classification",
        "evidence_reference_ids",
        "explanation",
        "uncertainty",
        "recommendation",
    ],
    "additionalProperties": False,
}

_EXPECTED_RESULT_FIELDS: Final = frozenset(
    {
        "classification",
        "evidence_reference_ids",
        "explanation",
        "uncertainty",
        "recommendation",
    }
)


@dataclass(frozen=True, slots=True)
class _ParsedStructuredResult:
    classification: ContextualClassification
    evidence_reference_ids: tuple[str, ...]
    explanation: str
    uncertainty: Uncertainty
    recommendation: InclusionRecommendation


class OpenAIRetentionStatus(StrEnum):
    """Explicitly reviewed provider retention state."""

    UNREVIEWED = "unreviewed"
    STANDARD = "standard"
    MODIFIED_ABUSE_MONITORING = "modified_abuse_monitoring"
    ZERO_DATA_RETENTION = "zero_data_retention"


@dataclass(frozen=True, slots=True)
class OpenAIAdapterConfiguration:
    """Non-secret configuration that never selects a model automatically."""

    enabled: bool = False
    live_use_approved: bool = False
    endpoint: str = OPENAI_RESPONSES_ENDPOINT
    organization_id: str | None = None
    project_id: str | None = None
    model_id: str | None = None
    model_configuration_version: str | None = None
    retention_status: OpenAIRetentionStatus = OpenAIRetentionStatus.UNREVIEWED
    provider_policy_review_owner: str | None = None
    prompt_cache_policy_reviewed: bool = False
    api_key_reference: KeychainSecretReference | None = None
    max_requests_per_run: int = 0
    timeout_seconds: float = 20.0
    max_output_tokens: int = OPENAI_MAX_OUTPUT_TOKENS


class KeychainReader(Protocol):
    """Narrow Keychain methods required by the provider adapter."""

    def exists(self, reference: KeychainSecretReference) -> bool:
        """Return whether the exact Keychain item exists."""

    def read(self, reference: KeychainSecretReference) -> str:
        """Read the exact secret without displaying it."""


class OpenAIResponsesTransport(Protocol):
    """Injectable transport so mocked evaluation never uses the network."""

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
        """Return one raw Responses API-shaped mapping."""


class OpenAISDKResponsesTransport:
    """Official-SDK transport with no retries and no retained provider state."""

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
        """Create one synchronous response and return only required fields."""

        if endpoint != OPENAI_RESPONSES_ENDPOINT:
            raise InferenceConfigurationError(
                "only the approved Responses endpoint is valid"
            )
        try:
            with OpenAI(
                api_key=api_key,
                organization=organization_id,
                project=project_id,
                max_retries=0,
                timeout=timeout_seconds,
            ) as client:
                response = client.responses.create(**cast(Any, dict(payload)))
        except openai.APITimeoutError as error:
            raise TimeoutError from error
        except openai.RateLimitError as error:
            raise InferenceRateLimitError("provider rate limit was reached") from error
        except openai.AuthenticationError as error:
            raise InferenceCredentialError(
                "the approved provider credential was rejected"
            ) from error
        except openai.PermissionDeniedError as error:
            raise InferenceConfigurationError(
                "the approved project denied the Responses request"
            ) from error
        except openai.APIConnectionError as error:
            raise InferenceUnavailableError(
                "provider transport is unavailable"
            ) from error
        except openai.APIStatusError as error:
            if error.status_code >= 500:
                raise InferenceUnavailableError(
                    "provider service is unavailable"
                ) from error
            raise InferenceConfigurationError(
                "the provider rejected the approved request configuration"
            ) from error

        raw = cast(dict[str, object], response.model_dump(mode="json"))
        return {
            "status": raw.get("status"),
            "model": raw.get("model"),
            "output": _without_provider_identifiers(raw.get("output", [])),
            "usage": _without_provider_identifiers(raw.get("usage", {})),
            "service_tier": raw.get("service_tier"),
            "store": raw.get("store"),
            "background": raw.get("background"),
        }


class OpenAIResponsesAdapter:
    """Translate one provider-neutral task to strict Responses API JSON."""

    provider_name = OPENAI_PROVIDER_NAME

    def __init__(
        self,
        configuration: OpenAIAdapterConfiguration,
        *,
        keychain: KeychainReader,
        transport: OpenAIResponsesTransport,
    ) -> None:
        self.configuration = configuration
        self._keychain = keychain
        self._transport = transport
        self._request_count = 0

    @property
    def request_count(self) -> int:
        """Return calls attempted by this bounded adapter instance."""

        return self._request_count

    def infer(self, request: InferenceRequest) -> InferenceResult:
        """Make one approved request or fail closed before transport."""

        self._validate_configuration(request)
        reference = self.configuration.api_key_reference
        if reference is None or not self._keychain.exists(reference):
            raise InferenceCredentialError("required Keychain item is unavailable")
        api_key = self._keychain.read(reference)
        if not api_key:
            raise InferenceCredentialError("required Keychain item is unavailable")

        self._request_count += 1
        started = time.monotonic()
        try:
            raw = self._transport.create_response(
                endpoint=self.configuration.endpoint,
                payload=self.build_payload(request),
                api_key=api_key,
                organization_id=cast(str, self.configuration.organization_id),
                project_id=cast(str, self.configuration.project_id),
                timeout_seconds=self.configuration.timeout_seconds,
            )
        except TimeoutError as error:
            raise InferenceTimeoutError("provider request timed out") from error
        except InferenceRateLimitError:
            raise
        except InferenceUnavailableError:
            raise
        except OSError as error:
            raise InferenceUnavailableError(
                "provider transport is unavailable"
            ) from error
        latency_ms = max(0, int((time.monotonic() - started) * 1000))

        if raw.get("status") != "completed":
            raise InferenceUnavailableError("provider response did not complete")
        returned_model = _required_string(raw, "model")
        if returned_model != self.configuration.model_id:
            raise InferenceModelMismatchError(
                "provider returned an unapproved model identifier"
            )
        if (
            raw.get("service_tier") != OPENAI_SERVICE_TIER
            or raw.get("store") is not False
            or raw.get("background") is not False
        ):
            raise InferenceProviderPolicyError(
                "provider response violated approved state or service policy"
            )
        if _contains_refusal(raw):
            raise InferenceRefusalError("provider refused the bounded task")
        output = _parse_output_json(raw)
        parsed = _validate_structured_result(output)
        usage = _parse_usage(raw.get("usage"), returned_model)
        if usage.cached_input_tokens or usage.cache_write_tokens:
            raise InferenceProviderPolicyError(
                "provider reported prohibited prompt-cache activity"
            )
        return InferenceResult(
            status=InferenceStatus.COMPLETED,
            classification=parsed.classification,
            evidence_reference_ids=parsed.evidence_reference_ids,
            explanation=parsed.explanation,
            uncertainty=parsed.uncertainty,
            recommendation=parsed.recommendation,
            task_version=request.task_version,
            prompt_version=request.prompt_version,
            schema_version=request.schema_version,
            policy_version=request.policy_version,
            model_configuration_version=request.model_configuration_version,
            provider_audit=ProviderAuditMetadata(
                provider=self.provider_name,
                model_id=returned_model,
                request_count=1,
                latency_ms=latency_ms,
            ),
            usage=usage,
        )

    def build_payload(self, request: InferenceRequest) -> dict[str, object]:
        """Build strict, stateless, tool-free Responses API input."""

        evidence = [
            {
                "reference_id": item.reference_id,
                "source": item.source,
                "content": item.content,
            }
            for item in request.packet.evidence
        ]
        task_input = {
            "task": request.task_name,
            "candidate_id": request.packet.candidate_id,
            "allowed_classifications": [
                item.value for item in request.packet.allowed_classifications
            ],
            "evidence": evidence,
        }
        return {
            "model": self.configuration.model_id or "",
            "instructions": (
                "Classify only the supplied unresolved candidate. Use only the "
                "supplied evidence references. Prefer not_actionable or "
                "insufficient_evidence over an unsupported actionable claim. "
                "Do not create facts, claim explicit evidence, use tools, rank "
                "the day, or propose external action."
            ),
            "input": json.dumps(task_input, separators=(",", ":"), sort_keys=True),
            "store": False,
            "background": False,
            "stream": False,
            "tools": [],
            "tool_choice": "none",
            "max_output_tokens": self.configuration.max_output_tokens,
            "truncation": "disabled",
            "service_tier": OPENAI_SERVICE_TIER,
            "reasoning": {
                "effort": OPENAI_REASONING_EFFORT,
                "context": "current_turn",
                "mode": "standard",
            },
            "prompt_cache_options": {
                "mode": OPENAI_PROMPT_CACHE_MODE,
            },
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "contextual_action_classification",
                    "strict": True,
                    "schema": CONTEXTUAL_ACTION_RESULT_SCHEMA,
                }
            },
        }

    def _validate_configuration(self, request: InferenceRequest) -> None:
        if not self.configuration.enabled:
            raise InferenceDisabledError("hosted inference is disabled")
        if not self.configuration.live_use_approved:
            raise InferenceConfigurationError("live provider use is not approved")
        if self.configuration.endpoint != OPENAI_RESPONSES_ENDPOINT:
            raise InferenceConfigurationError(
                "only the approved Responses endpoint is valid"
            )
        required = (
            self.configuration.organization_id,
            self.configuration.project_id,
            self.configuration.model_id,
            self.configuration.model_configuration_version,
            self.configuration.provider_policy_review_owner,
        )
        if any(value is None or not value.strip() for value in required):
            raise InferenceConfigurationError(
                "approved organization, project, model, policy owner, and version are required"
            )
        if (
            self.configuration.retention_status is OpenAIRetentionStatus.UNREVIEWED
            or not self.configuration.prompt_cache_policy_reviewed
        ):
            raise InferenceConfigurationError(
                "retention and prompt-cache policy must be reviewed"
            )
        if (
            self.configuration.model_configuration_version
            != request.model_configuration_version
        ):
            raise InferenceConfigurationError(
                "request and approved model-configuration versions differ"
            )
        if self.configuration.max_requests_per_run <= 0:
            raise InferenceConfigurationError("a positive request cap is required")
        if self.configuration.max_requests_per_run > 10:
            raise InferenceConfigurationError(
                "one model adapter cannot exceed ten evaluation requests"
            )
        if self._request_count >= self.configuration.max_requests_per_run:
            raise InferenceConfigurationError("bounded request cap is exhausted")
        if self.configuration.timeout_seconds <= 0:
            raise InferenceConfigurationError("a positive timeout is required")
        if self.configuration.model_id not in OPENAI_EVALUATION_MODELS:
            raise InferenceConfigurationError(
                "model is outside the approved comparative evaluation"
            )
        if self.configuration.api_key_reference != OPENAI_API_KEY_REFERENCE:
            raise InferenceConfigurationError(
                "credential reference is outside the approved Keychain item"
            )
        if self.configuration.timeout_seconds != 20.0:
            raise InferenceConfigurationError("the approved timeout is 20 seconds")
        if self.configuration.max_output_tokens != OPENAI_MAX_OUTPUT_TOKENS:
            raise InferenceConfigurationError("max output tokens are outside policy")


def _required_string(value: Mapping[str, object], field: str) -> str:
    selected = value.get(field)
    if not isinstance(selected, str) or not selected:
        raise InferenceSchemaError("provider response is missing a required field")
    return selected


def _contains_refusal(raw: Mapping[str, object]) -> bool:
    output = raw.get("output")
    if not isinstance(output, list):
        return False
    for item in output:
        if not isinstance(item, Mapping):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        if any(
            isinstance(part, Mapping) and part.get("type") == "refusal"
            for part in content
        ):
            return True
    return False


def _parse_output_json(raw: Mapping[str, object]) -> object:
    output = raw.get("output")
    if not isinstance(output, list):
        raise InferenceSchemaError("provider response has no structured output")
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, Mapping) or part.get("type") != "output_text":
                continue
            text = part.get("text")
            if not isinstance(text, str):
                continue
            try:
                return json.loads(text)
            except json.JSONDecodeError as error:
                raise InferenceSchemaError(
                    "provider output is not valid structured JSON"
                ) from error
    raise InferenceSchemaError("provider response has no structured output")


def _validate_structured_result(value: object) -> _ParsedStructuredResult:
    if not isinstance(value, dict) or set(value) != _EXPECTED_RESULT_FIELDS:
        raise InferenceSchemaError("provider output does not match the owned schema")
    classification = value.get("classification")
    references = value.get("evidence_reference_ids")
    explanation = value.get("explanation")
    uncertainty = value.get("uncertainty")
    recommendation = value.get("recommendation")
    if not all(
        isinstance(item, str) for item in (classification, uncertainty, recommendation)
    ):
        raise InferenceSchemaError("provider output contains an invalid enum type")
    try:
        parsed_classification = ContextualClassification(cast(str, classification))
        parsed_uncertainty = Uncertainty(cast(str, uncertainty))
        parsed_recommendation = InclusionRecommendation(cast(str, recommendation))
    except (TypeError, ValueError) as error:
        raise InferenceSchemaError(
            "provider output contains an unsupported enum value"
        ) from error
    if (
        not isinstance(references, list)
        or len(references) > 3
        or any(not isinstance(item, str) or not item for item in references)
    ):
        raise InferenceSchemaError("provider evidence references are invalid")
    if (
        not isinstance(explanation, str)
        or not explanation.strip()
        or len(explanation) > MAX_EXPLANATION_CHARACTERS
    ):
        raise InferenceSchemaError("provider explanation is invalid")
    return _ParsedStructuredResult(
        classification=parsed_classification,
        evidence_reference_ids=tuple(cast(list[str], references)),
        explanation=explanation.strip(),
        uncertainty=parsed_uncertainty,
        recommendation=parsed_recommendation,
    )


def _parse_usage(value: object, model_id: str) -> UsageMetadata:
    if not isinstance(value, Mapping):
        return UsageMetadata(input_tokens=0, output_tokens=0, total_tokens=0)
    input_tokens = _nonnegative_int(value.get("input_tokens"))
    output_tokens = _nonnegative_int(value.get("output_tokens"))
    total_tokens = _nonnegative_int(value.get("total_tokens"))
    input_details = value.get("input_tokens_details")
    output_details = value.get("output_tokens_details")
    cached_input_tokens = (
        _nonnegative_int(input_details.get("cached_tokens"))
        if isinstance(input_details, Mapping)
        else 0
    )
    cache_write_tokens = (
        _nonnegative_int(input_details.get("cache_write_tokens"))
        if isinstance(input_details, Mapping)
        else 0
    )
    reasoning_tokens = (
        _nonnegative_int(output_details.get("reasoning_tokens"))
        if isinstance(output_details, Mapping)
        else 0
    )
    usage = UsageMetadata(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
    )
    return UsageMetadata(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_microusd=estimate_usage_cost_microusd(model_id, usage),
        cached_input_tokens=cached_input_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
    )


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def estimate_usage_cost_microusd(model_id: str, usage: UsageMetadata) -> int:
    """Estimate standard-tier cost from current GPT-5.6 usage details."""

    try:
        pricing = OPENAI_EVALUATION_PRICING[model_id]
    except KeyError:
        raise InferenceConfigurationError(
            "pricing is unavailable for the approved model"
        ) from None
    uncached_tokens = max(
        0,
        usage.input_tokens - usage.cached_input_tokens - usage.cache_write_tokens,
    )
    estimate = (
        Decimal(uncached_tokens) * pricing.input_microusd_per_token
        + Decimal(usage.cached_input_tokens) * pricing.cached_input_microusd_per_token
        + Decimal(usage.cache_write_tokens) * pricing.cache_write_microusd_per_token
        + Decimal(usage.output_tokens) * pricing.output_microusd_per_token
    )
    return int(estimate.to_integral_value(rounding=ROUND_CEILING))


def _without_provider_identifiers(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _without_provider_identifiers(item)
            for key, item in value.items()
            if key not in {"id", "request_id", "_request_id"}
        }
    if isinstance(value, list):
        return [_without_provider_identifiers(item) for item in value]
    return value
