"""Typed records shared by persistence and future pipeline layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class ConnectorStatus(StrEnum):
    """Lifecycle state for one connector retrieval."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class CoverageStatus(StrEnum):
    """Coverage reported by a connector."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    UNAUTHORIZED = "unauthorized"


class BriefingStatus(StrEnum):
    """Lifecycle state for one briefing generation."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    WITHHELD = "withheld"
    FAILED = "failed"


class ConclusionKind(StrEnum):
    """Application-owned conclusion categories."""

    COMMITMENT = "commitment"
    WAITING_ITEM = "waiting_item"
    PREPARATION_ITEM = "preparation_item"
    RECOMMENDATION = "recommendation"


class Classification(StrEnum):
    """Whether a conclusion is direct source fact or contextual inference."""

    EXPLICIT = "explicit"
    INFERRED = "inferred"


class DispositionKind(StrEnum):
    """Supported append-oriented local disposition events."""

    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    DISMISSED = "dismissed"
    DELEGATED = "delegated"
    RESCHEDULED = "rescheduled"
    COMPLETED = "completed"
    INTENTIONALLY_ABANDONED = "intentionally_abandoned"


class RecurrenceAction(StrEnum):
    """How prior local state affects materially unchanged evidence."""

    SHOW = "show"
    REPLACE = "replace"
    SUPPRESS = "suppress"


class AuthorizationStatus(StrEnum):
    """Inspectable non-secret connector authorization state."""

    AUTHORIZED = "authorized"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


class CredentialHealth(StrEnum):
    """Whether the referenced Keychain credential appears usable."""

    HEALTHY = "healthy"
    EXPIRED = "expired"
    MISSING = "missing"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ConnectorRun:
    """Retrieval metadata without raw source payloads."""

    id: str
    source: str
    approved_scope: str
    started_at: datetime
    status: ConnectorStatus
    coverage_status: CoverageStatus
    retrieval_window_start: datetime | None = None
    retrieval_window_end: datetime | None = None
    completed_at: datetime | None = None
    freshness_at: datetime | None = None
    error_category: str | None = None
    page_count: int | None = None


@dataclass(frozen=True, slots=True)
class BriefingRun:
    """Metadata for one versioned briefing generation."""

    id: str
    briefing_date: date
    timezone: str
    invocation_mode: str
    started_at: datetime
    status: BriefingStatus
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    """Minimal authoritative source reference supporting a conclusion."""

    id: str
    connector_run_id: str | None
    source: str
    source_record_id: str
    evidence_fingerprint: str
    retrieved_at: datetime
    display_url: str | None = None
    excerpt: str | None = None
    freshness_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Conclusion:
    """Explicit or inferred application conclusion with provenance."""

    id: str
    kind: ConclusionKind
    classification: Classification
    statement: str
    explanation: str
    confidence: float | None
    evidence_fingerprint: str
    processing_version: str
    created_at: datetime
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DispositionEvent:
    """One immutable-in-normal-operation correction or disposition event."""

    id: str
    conclusion_id: str
    disposition: DispositionKind
    created_at: datetime
    briefing_run_id: str | None = None
    replacement_text: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ConclusionState:
    """Inspectable conclusion, provenance, and complete disposition history."""

    conclusion: Conclusion
    evidence: tuple[SourceEvidence, ...]
    history: tuple[DispositionEvent, ...]

    @property
    def latest_disposition(self) -> DispositionEvent | None:
        """Return the most recent append-oriented event."""

        return self.history[-1] if self.history else None


@dataclass(frozen=True, slots=True)
class RecurrenceDecision:
    """Projection applied when a materially equivalent candidate reappears."""

    action: RecurrenceAction
    prior_conclusion_id: str | None = None
    replacement_text: str | None = None
    disposition: DispositionKind | None = None


@dataclass(frozen=True, slots=True)
class StateInspection:
    """Non-content inventory of persistent application-owned state."""

    schema_versions: tuple[int, ...]
    connector_runs: int
    briefing_runs: int
    source_evidence: int
    conclusions: int
    disposition_events: int
    oauth_clients: int
    connector_authorizations: int


@dataclass(frozen=True, slots=True)
class OAuthClientMetadata:
    """Non-secret installed-application client configuration."""

    connector: str
    oauth_project_id: str
    oauth_client_id: str
    credential_service: str
    client_secret_account: str
    configured_at: datetime


@dataclass(frozen=True, slots=True)
class ConnectorAuthorizationMetadata:
    """Non-secret authorization and Keychain-reference metadata."""

    connector: str
    account_reference: str
    account_identity: str
    granted_scope: str
    credential_service: str
    access_token_account: str
    authorization_status: AuthorizationStatus
    credential_health: CredentialHealth
    token_expires_at: datetime
    authorized_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None
