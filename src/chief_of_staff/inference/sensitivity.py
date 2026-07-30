"""Conservative deterministic sensitivity classification."""

from __future__ import annotations

import re
from typing import Final

from chief_of_staff.inference.models import SensitivityAssessment, SensitivityTier

_SECRET_PATTERNS: Final = (
    re.compile(r"(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token)\b"),
    re.compile(r"(?i)\b(?:password|passwd|client[_ -]?secret)\s*[:=]"),
    re.compile(r"\b(?:sk|ghp|xoxb)[-_][A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
_TIER_3_TERMS: Final = frozenset(
    {
        "bank account",
        "confession",
        "counseling transcript",
        "crisis narrative",
        "diagnosis",
        "disciplinary action",
        "medical record",
        "payroll record",
        "social security",
        "suicidal",
    }
)
_TIER_2_TERMS: Final = frozenset(
    {
        "confidential planning",
        "congregant",
        "family",
        "financial",
        "health",
        "pastoral",
        "personnel",
        "private care",
        "salary",
    }
)
_TIER_1_TERMS: Final = frozenset(
    {
        "agenda",
        "deadline",
        "deliverable",
        "meeting",
        "project",
        "release",
        "review",
        "status",
        "task",
    }
)
_AMBIGUOUS_TERMS: Final = frozenset(
    {
        "private matter",
        "sensitive issue",
        "personal situation",
    }
)


def assess_sensitivity(values: tuple[str, ...]) -> SensitivityAssessment:
    """Classify bounded text conservatively before any provider boundary."""

    combined = "\n".join(values)
    if any(pattern.search(combined) for pattern in _SECRET_PATTERNS):
        return SensitivityAssessment(
            tier=SensitivityTier.INELIGIBLE_CREDENTIAL_MATERIAL,
            hosted_eligible=False,
            reason="credential or secret-like material is prohibited",
        )

    normalized = combined.casefold()
    tier_3 = _contains_term(normalized, _TIER_3_TERMS)
    tier_2 = _contains_term(normalized, _TIER_2_TERMS)
    tier_1 = _contains_term(normalized, _TIER_1_TERMS)
    ambiguous = _contains_term(normalized, _AMBIGUOUS_TERMS)
    present_tiers = sum((tier_1, tier_2, tier_3))

    if present_tiers > 1:
        return SensitivityAssessment(
            tier=SensitivityTier.MIXED,
            hosted_eligible=False,
            reason="evidence spans multiple sensitivity classes",
        )
    if tier_3:
        return SensitivityAssessment(
            tier=SensitivityTier.TIER_3,
            hosted_eligible=False,
            reason="highly sensitive content is hosted-inference-ineligible",
        )
    if tier_2:
        return SensitivityAssessment(
            tier=SensitivityTier.TIER_2,
            hosted_eligible=False,
            reason="heightened-sensitivity content is hosted-inference-ineligible",
        )
    if ambiguous or not tier_1:
        return SensitivityAssessment(
            tier=SensitivityTier.UNKNOWN,
            hosted_eligible=False,
            reason="unknown or ambiguous sensitivity is ineligible",
        )
    return SensitivityAssessment(
        tier=SensitivityTier.TIER_1,
        hosted_eligible=True,
        reason="ordinary operational evidence is eligible for a future approved trial",
    )


def _contains_term(value: str, terms: frozenset[str]) -> bool:
    return any(
        re.search(rf"(?<!\w){re.escape(term)}(?!\w)", value) is not None
        for term in terms
    )
