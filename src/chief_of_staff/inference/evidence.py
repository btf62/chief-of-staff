"""Deterministic evidence minimization and packet construction."""

from __future__ import annotations

import hashlib
import re
from typing import Final

from chief_of_staff.inference.models import (
    CandidateResolution,
    EvidencePacket,
    InferenceCandidate,
    MinimizedEvidence,
    SensitivityTier,
)
from chief_of_staff.inference.sensitivity import assess_sensitivity

MAX_EVIDENCE_ITEMS: Final = 3
MAX_CHARACTERS_PER_ITEM: Final = 600
MAX_TOTAL_CHARACTERS: Final = 1200

_EMAIL: Final = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_TRACKING_PARAMETER: Final = re.compile(
    r"(?i)([?&])(?:utm_[a-z_]+|trk|tracking|mc_cid|mc_eid)=[^&\s]+"
)
_QUOTED_HEADER: Final = re.compile(r"(?i)^on .+ wrote:\s*$")
_ORIGINAL_MESSAGE_HEADER: Final = re.compile(
    r"(?i)^-+\s*(?:original|forwarded) message\s*-+$"
)
_SIGNATURE_START: Final = re.compile(
    r"(?i)^(?:--|thanks,?|thank you,?|best,?|regards,?|sincerely,?)\s*$"
)


class EvidencePacketError(ValueError):
    """Raised when a candidate cannot produce a bounded eligible packet."""


def stable_evidence_reference(source: str, source_record_id: str) -> str:
    """Return a stable opaque local reference independent of content."""

    if not source.strip() or not source_record_id.strip():
        raise ValueError("source and source record ID are required")
    digest = hashlib.sha256(f"{source}\0{source_record_id}".encode()).hexdigest()
    return f"ev_{digest[:20]}"


def build_evidence_packet(candidate: InferenceCandidate) -> EvidencePacket:
    """Build one minimized, sensitivity-assessed candidate packet."""

    if candidate.resolution is not CandidateResolution.UNRESOLVED_CONTEXTUAL:
        raise EvidencePacketError("only unresolved contextual candidates are eligible")

    relevant = tuple(
        item
        for item in candidate.evidence
        if item.relevant and not item.attachment and item.content.strip()
    )
    raw_values = tuple(item.content for item in relevant)
    sensitivity = assess_sensitivity(raw_values)
    if sensitivity.tier is SensitivityTier.INELIGIBLE_CREDENTIAL_MATERIAL:
        return EvidencePacket(
            candidate_id=candidate.id,
            evidence_fingerprint=candidate.evidence_fingerprint,
            evidence=(),
            sensitivity=sensitivity,
            total_characters=0,
            allowed_classifications=candidate.allowed_classifications,
        )

    minimized: list[MinimizedEvidence] = []
    total = 0
    for item in relevant[:MAX_EVIDENCE_ITEMS]:
        content = minimize_evidence_text(item.content)
        if not content:
            continue
        content = content[:MAX_CHARACTERS_PER_ITEM].rstrip()
        remaining = MAX_TOTAL_CHARACTERS - total
        if remaining <= 0:
            break
        content = content[:remaining].rstrip()
        if not content:
            continue
        minimized.append(
            MinimizedEvidence(
                reference_id=item.reference_id,
                source=item.source,
                content=content,
            )
        )
        total += len(content)

    if not minimized:
        raise EvidencePacketError("candidate has no relevant minimized evidence")
    return EvidencePacket(
        candidate_id=candidate.id,
        evidence_fingerprint=candidate.evidence_fingerprint,
        evidence=tuple(minimized),
        sensitivity=sensitivity,
        total_characters=total,
        allowed_classifications=candidate.allowed_classifications,
    )


def minimize_evidence_text(value: str) -> str:
    """Remove common unrelated history and pseudonymize email addresses."""

    lines: list[str] = []
    for raw_line in value.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw_line.strip()
        if not line:
            if lines and lines[-1]:
                lines.append("")
            continue
        if _QUOTED_HEADER.fullmatch(line) or _ORIGINAL_MESSAGE_HEADER.fullmatch(line):
            break
        if line.startswith(">"):
            continue
        if _SIGNATURE_START.fullmatch(line):
            break
        lines.append(line)

    minimized = " ".join(segment for segment in lines if segment).strip()
    minimized = _TRACKING_PARAMETER.sub("", minimized)
    return _EMAIL.sub(_local_person_reference, minimized)


def _local_person_reference(match: re.Match[str]) -> str:
    digest = hashlib.sha256(match.group(0).casefold().encode()).hexdigest()
    return f"person_{digest[:10]}"
