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


class EvidenceClassification(StrEnum):
    """Milestone 7 evidence judgment without introducing model inference."""

    DIRECT_SOURCE_FACT = "direct_source_fact"
    EXPLICIT_DETERMINISTIC_CONCLUSION = "explicit_deterministic_conclusion"
    CONTEXTUAL_INFERENCE = "contextual_inference"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class DispositionKind(StrEnum):
    """Supported append-oriented local disposition events."""

    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    DISMISSED = "dismissed"
    DELEGATED = "delegated"
    RESCHEDULED = "rescheduled"
    COMPLETED = "completed"
    INTENTIONALLY_ABANDONED = "intentionally_abandoned"
    DELETED = "deleted"


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


class ConnectorDomain(StrEnum):
    """Operational domain carried independently for each connector instance."""

    WORK = "work"
    PERSONAL = "personal"
    UNCLASSIFIED = "unclassified"


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
    connector_instance_id: str | None = None


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
    connector_instance_id: str | None = None


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
    previous_state: str = "active"
    new_state: str | None = None
    delegate_description: str | None = None
    follow_up_at: datetime | None = None
    rescheduled_for: datetime | None = None
    evidence_fingerprint: str = ""
    processing_version: str = ""
    expected_version: int = 0
    resulting_version: int = 1
    idempotency_key: str = ""


@dataclass(frozen=True, slots=True)
class ConclusionState:
    """Inspectable conclusion, provenance, and complete disposition history."""

    conclusion: Conclusion
    evidence: tuple[SourceEvidence, ...]
    history: tuple[DispositionEvent, ...]
    projection: ConclusionProjection | None = None

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
    material_evidence_changed: bool = False
    reappearance_explanation: str | None = None


@dataclass(frozen=True, slots=True)
class ConclusionProjection:
    """Derived current local interpretation for one conclusion."""

    conclusion_id: str
    current_state: str
    display_statement: str
    version: int
    updated_at: datetime
    last_event_id: str | None = None
    delegate_description: str | None = None
    follow_up_at: datetime | None = None
    rescheduled_for: datetime | None = None


@dataclass(frozen=True, slots=True)
class DispositionResult:
    """Idempotent result of applying one local disposition."""

    applied: bool
    projection: ConclusionProjection
    event: DispositionEvent | None


@dataclass(frozen=True, slots=True)
class BriefingPresentationSource:
    """Minimized source link shown with one briefing item."""

    source: str
    display_url: str | None = None
    freshness_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class BriefingPresentationItem:
    """Persistable presentation item without raw source payloads."""

    id: str
    headline: str
    detail: str
    content_kind: str
    sources: tuple[BriefingPresentationSource, ...]
    conclusion_id: str | None = None
    uncertainty: str | None = None
    explanation: str | None = None


@dataclass(frozen=True, slots=True)
class BriefingPresentationSection:
    """One persisted canonical section."""

    name: str
    items: tuple[BriefingPresentationItem, ...]
    summary: str | None = None


@dataclass(frozen=True, slots=True)
class BriefingPresentation:
    """One safe, structured local briefing presentation."""

    briefing_run_id: str
    generation_mode: str
    chief_of_staff_note: str
    created_at: datetime
    sections: tuple[BriefingPresentationSection, ...]


@dataclass(frozen=True, slots=True)
class BriefingCoverage:
    """One source-coverage row associated with a briefing."""

    source: str
    coverage_status: CoverageStatus
    freshness_at: datetime | None
    error_category: str | None = None


@dataclass(frozen=True, slots=True)
class BriefingPresentationState:
    """Presentation plus run metadata, coverage, and conclusion projections."""

    run: BriefingRun
    presentation: BriefingPresentation
    coverage: tuple[BriefingCoverage, ...]


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
    connector_resources: int
    normalized_source_tasks: int
    normalized_source_task_labels: int
    normalized_jira_issues: int
    normalized_jira_issue_labels: int
    normalized_jira_issue_links: int
    normalized_gmail_messages: int
    connector_instances: int
    inference_audits: int
    conclusion_current_states: int
    conclusion_tombstones: int
    briefing_presentations: int
    briefing_items: int


@dataclass(frozen=True, slots=True)
class ConnectorInstanceMetadata:
    """Application-owned identity and policy for one configured source account."""

    id: str
    provider: str
    alias: str
    domain_classification: ConnectorDomain
    approved_resource_boundary: str
    approved_scopes: str
    retrieval_configuration: str
    enabled: bool
    retention_policy_reference: str
    created_at: datetime
    updated_at: datetime
    last_coverage_status: CoverageStatus | None = None
    last_freshness_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("connector instance ID", self.id),
            ("provider", self.provider),
            ("account alias", self.alias),
            ("approved resource boundary", self.approved_resource_boundary),
            ("approved scopes", self.approved_scopes),
            ("retrieval configuration", self.retrieval_configuration),
            ("retention policy reference", self.retention_policy_reference),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        if "@" in self.alias:
            raise ValueError("account alias must not be a full email address")


@dataclass(frozen=True, slots=True)
class OAuthClientMetadata:
    """Non-secret installed-application client configuration."""

    connector: str
    oauth_project_id: str
    oauth_client_id: str
    credential_service: str
    client_secret_account: str
    configured_at: datetime
    application_owner: str | None = None
    oauth_grant_type: str | None = None
    connector_instance_id: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectorAuthorizationMetadata:
    """Non-secret authorization and Keychain-reference metadata."""

    connector: str
    account_reference: str
    account_identity: str
    granted_scope: str
    credential_service: str
    access_token_account: str
    refresh_token_account: str | None
    authorization_status: AuthorizationStatus
    credential_health: CredentialHealth
    refresh_health: CredentialHealth | None
    token_expires_at: datetime
    authorized_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None
    connector_instance_id: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectorResourceMetadata:
    """One non-secret provider resource bound to a connector grant."""

    connector: str
    resource_reference: str
    resource_id: str
    resource_url: str
    resource_type: str
    grant_type: str
    selected_at: datetime
    connector_instance_id: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedSourceTask:
    """Minimal persisted task facts linked to authoritative evidence."""

    evidence_id: str
    title: str
    provider_priority: int
    recurring: bool
    all_day: bool
    due_at: datetime | None = None
    project_id: str | None = None
    project_name: str | None = None
    section_id: str | None = None
    section_name: str | None = None
    responsible_user_id: str | None = None
    parent_task_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    labels: tuple[tuple[str | None, str], ...] = ()


@dataclass(frozen=True, slots=True)
class NormalizedJiraIssueLink:
    """Minimum persisted reference to one Jira-linked issue."""

    relationship: str
    issue_id: str
    issue_key: str
    display_url: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedJiraIssue:
    """Approved Jira issue facts linked to one evidence snapshot."""

    evidence_id: str
    issue_key: str
    summary: str
    project_key: str
    issue_type: str
    status: str
    status_category: str
    assignee_account_id: str
    priority_name: str | None
    due_date: date | None
    created_at: datetime
    updated_at: datetime
    parent_key: str | None = None
    labels: tuple[str, ...] = ()
    links: tuple[NormalizedJiraIssueLink, ...] = ()


@dataclass(frozen=True, slots=True)
class NormalizedGmailMessage:
    """Minimum persisted Work Gmail facts linked to authoritative evidence."""

    evidence_id: str
    thread_id: str
    direction: str
    occurred_at: datetime
    label_classification: str
    processing_version: str
    participant_references: tuple[str, ...] = ()
    subject: str | None = None
    detection_type: str | None = None
