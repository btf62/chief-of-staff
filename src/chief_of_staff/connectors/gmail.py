"""High-precision, read-only Work Gmail connector with inert MIME handling."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import time as time_module
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from email.utils import getaddresses
from enum import StrEnum
from html.parser import HTMLParser
from typing import Final, Protocol
from zoneinfo import ZoneInfo

from chief_of_staff.connectors.contracts import (
    ConnectorRequest,
    ConnectorResult,
    ContextResourceCoverage,
    SourceCoverage,
    SourceItem,
)
from chief_of_staff.domain import CoverageStatus

GMAIL_CONNECTOR: Final = "gmail"
GMAIL_WORK_INSTANCE: Final = "gmail:work"
GMAIL_WORK_ALIAS: Final = "Work Gmail"
GMAIL_WORK_ACCOUNT: Final = "bfiles@northridgerochester.com"
GMAIL_READONLY_SCOPE: Final = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_MESSAGES_ENDPOINT: Final = "/gmail/v1/users/me/messages"
GMAIL_PROFILE_ENDPOINT: Final = "/gmail/v1/users/me/profile"
GMAIL_METADATA_HEADERS: Final = (
    "From",
    "To",
    "Cc",
    "Bcc",
    "Reply-To",
    "Subject",
    "Date",
    "Message-ID",
    "In-Reply-To",
    "References",
    "Auto-Submitted",
    "Precedence",
    "List-Id",
    "List-Unsubscribe",
)
GMAIL_INBOUND_MESSAGE_LIMIT: Final = 300
GMAIL_SENT_MESSAGE_LIMIT: Final = 200
GMAIL_MESSAGE_LIMIT: Final = 500
GMAIL_BODY_CANDIDATE_LIMIT: Final = 120
GMAIL_PAGE_SIZE: Final = 100
GMAIL_PAGE_LIMIT: Final = 20
GMAIL_MAX_MESSAGE_SIZE_ESTIMATE: Final = 2 * 1024 * 1024
GMAIL_MAX_MESSAGE_TEXT_CHARS: Final = 16_000
GMAIL_MAX_RUN_TEXT_CHARS: Final = 500_000
GMAIL_REVIEW_REJECTION_LIMIT: Final = 20
GMAIL_PROCESSING_VERSION: Final = "gmail-deterministic-v3"
GMAIL_DEFAULT_INBOUND_DAYS: Final = 7
GMAIL_MINIMUM_INBOUND_DAYS: Final = 3
GMAIL_DEFAULT_SENT_DAYS: Final = 14
GMAIL_MINIMUM_SENT_DAYS: Final = 7
GMAIL_MAX_TRANSIENT_ATTEMPTS: Final = 3
GMAIL_MAX_RETRY_DELAY_SECONDS: Final = 30

_EXCLUDED_LABELS = frozenset(
    {
        "DRAFT",
        "SPAM",
        "TRASH",
        "CATEGORY_PROMOTIONS",
        "CATEGORY_SOCIAL",
        "CATEGORY_FORUMS",
    }
)
_AUTOMATED_LOCAL_PARTS = frozenset(
    {"no-reply", "noreply", "do-not-reply", "donotreply", "notifications"}
)
_REQUEST_PATTERNS = (
    re.compile(
        r"\bplease\s+(?:send|review|confirm|reply|respond|decide|approve|"
        r"share|provide|complete|call|schedule|let me know)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:could|would|can)\s+you\s+(?:please\s+)?"
        r"(?:send|review|confirm|reply|respond|decide|approve|share|provide|"
        r"complete|call|schedule|let me know)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bI\s+need\s+(?:your\s+(?:decision|approval|response|input)|"
        r"you\s+to\s+(?:send|review|confirm|reply|respond|decide|approve|"
        r"share|provide|complete|call|schedule))\b",
        re.IGNORECASE,
    ),
)
_COMMITMENT_PATTERN = re.compile(
    r"\b(?:I(?:'ll| will)\s+(?:send|review|follow up|reply|respond|complete|"
    r"finish|deliver|confirm|share|provide)|"
    r"I\s+can\s+get\s+(?:that|it)\s+to\s+you\b)[^.!?\n]{1,220}[.!?]?",
    re.IGNORECASE,
)
_INSTRUCTION_LIKE_PATTERNS = (
    re.compile(
        r"\bignore (?:all |the )?(?:previous|prior|system) instructions\b", re.I
    ),
    re.compile(
        r"\b(?:reveal|print|return|expose) (?:the )?(?:secret|token|password)", re.I
    ),
    re.compile(r"\bsystem prompt\b", re.I),
    re.compile(r"\bcall (?:a |the )?tool\b", re.I),
)
_COMPLETION_PATTERNS = (
    re.compile(r"\b(?:sent|completed|finished|delivered|attached)\b", re.I),
    re.compile(r"\bhere (?:is|are)\b", re.I),
    re.compile(r"\bI (?:need to|have to) reschedule\b", re.I),
    re.compile(r"\bI (?:can no longer|won't be able to)\b", re.I),
)
_QUOTE_MARKERS = (
    re.compile(r"^On .+ wrote:$", re.I),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}$", re.I),
    re.compile(r"^From:\s+.+$", re.I),
    re.compile(r"^Sent:\s+.+$", re.I),
)


class GmailStream(StrEnum):
    """The two independently bounded Work Gmail retrieval streams."""

    INBOUND = "inbound"
    SENT = "sent"


class GmailFailureStage(StrEnum):
    """Privacy-safe lifecycle stage at which Gmail retrieval stopped."""

    INITIALIZATION = "initialization"
    AUTHORIZATION = "authorization"
    PROFILE = "profile"
    LISTING = "listing"
    METADATA = "metadata"
    BODY = "body"
    PROCESSING = "processing"


class GmailFailureCategory(StrEnum):
    """Provider-neutral, privacy-safe Gmail failure categories."""

    CONFIGURED_BOUNDARY_EXCEEDED = "configured_boundary_exceeded"
    AUTHORIZATION_UNAVAILABLE = "authorization_unavailable"
    ACCOUNT_OR_SCOPE_MISMATCH = "account_or_scope_mismatch"
    PROVIDER_FORBIDDEN = "provider_forbidden"
    RATE_LIMITING = "rate_limiting"
    TIMEOUT = "timeout"
    NETWORK_OR_TRANSPORT_FAILURE = "network_or_transport_failure"
    PROVIDER_SERVER_FAILURE = "provider_server_failure"
    INVALID_PROVIDER_RESPONSE = "invalid_provider_response"
    PAGINATION_FAILURE = "pagination_failure"
    RESPONSE_SIZE_BOUNDARY = "response_size_boundary"
    FIXED_ENDPOINT_VIOLATION = "fixed_endpoint_violation"
    UNEXPECTED_INTERNAL_FAILURE = "unexpected_internal_failure"


class GmailError(RuntimeError):
    """Base error for the bounded Work Gmail connector."""

    default_category = GmailFailureCategory.UNEXPECTED_INTERNAL_FAILURE
    default_stage = GmailFailureStage.INITIALIZATION

    def __init__(
        self,
        message: str = "",
        *,
        category: GmailFailureCategory | None = None,
        stage: GmailFailureStage | None = None,
        affected_stream: GmailStream | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category or self.default_category
        self.stage = stage or self.default_stage
        self.affected_stream = affected_stream
        self.retry_after_seconds = retry_after_seconds


class GmailAuthenticationError(GmailError):
    """Raised when the exact Work Gmail authorization is unavailable."""

    default_category = GmailFailureCategory.AUTHORIZATION_UNAVAILABLE
    default_stage = GmailFailureStage.AUTHORIZATION


class GmailRetrievalError(GmailError):
    """Raised when a bounded Gmail retrieval cannot continue safely."""


class GmailBoundaryExceeded(GmailError):
    """Raised before expansion when a configured run cap is exceeded."""

    def __init__(
        self,
        message: str,
        *,
        boundary: str,
        observed_count: int,
        limit: int,
        stage: GmailFailureStage,
        affected_stream: GmailStream | None = None,
    ) -> None:
        super().__init__(
            message,
            category=GmailFailureCategory.CONFIGURED_BOUNDARY_EXCEEDED,
            stage=stage,
            affected_stream=affected_stream,
        )
        self.boundary = boundary
        self.observed_count = observed_count
        self.limit = limit


class GmailAuthorizationUnavailable(GmailAuthenticationError):
    """Raised when no healthy exact Work Gmail grant is available."""


@dataclass(frozen=True, slots=True)
class GmailAuthorization:
    """Non-secret exact-scope authorization reference."""

    account_reference: str
    granted_scopes: frozenset[str]
    credential_reference: str


class GmailAuthorizationProvider(Protocol):
    """Resolve one exact Work Gmail authorization without returning a token."""

    def get_gmail_authorization(
        self,
        account_reference: str,
    ) -> GmailAuthorization:
        """Return a healthy exact-scope authorization or raise."""


@dataclass(frozen=True, slots=True)
class GmailProfile:
    """Minimal provider profile used only for account confirmation."""

    email_address: str


@dataclass(frozen=True, slots=True)
class GmailMessageReference:
    """Immutable identity returned by the list endpoint."""

    id: str
    thread_id: str


@dataclass(frozen=True, slots=True)
class GmailMessageListRequest:
    """One stable, bounded list request."""

    query: str
    page_size: int = GMAIL_PAGE_SIZE
    page_token: str | None = None


@dataclass(frozen=True, slots=True)
class GmailMessageListPage:
    """One message-list page with an opaque continuation token."""

    messages: tuple[GmailMessageReference, ...]
    next_page_token: str | None = None


@dataclass(frozen=True, slots=True)
class GmailMessageMetadata:
    """Minimum message facts retrieved before any content."""

    id: str
    thread_id: str
    internal_date: datetime
    label_ids: tuple[str, ...]
    size_estimate: int
    headers: tuple[tuple[str, str], ...]

    def header(self, name: str) -> str | None:
        """Return the first case-insensitive header value."""

        expected = name.casefold()
        for header_name, value in self.headers:
            if header_name.casefold() == expected:
                return value
        return None


@dataclass(frozen=True, slots=True)
class GmailMimePart:
    """Bounded MIME tree used transiently by deterministic extraction."""

    mime_type: str
    filename: str = ""
    body_data: str | None = field(default=None, repr=False)
    attachment_id: str | None = None
    parts: tuple[GmailMimePart, ...] = ()


@dataclass(frozen=True, slots=True)
class GmailFullMessage:
    """One candidate message with transient inline MIME content."""

    metadata: GmailMessageMetadata
    payload: GmailMimePart


class GmailTransport(Protocol):
    """The complete read-only transport surface."""

    def get_profile(self, authorization: GmailAuthorization) -> GmailProfile:
        """Return only the authorized account identity."""

    def list_messages(
        self,
        authorization: GmailAuthorization,
        request: GmailMessageListRequest,
    ) -> GmailMessageListPage:
        """List immutable message identities within the approved query."""

    def get_message_metadata(
        self,
        authorization: GmailAuthorization,
        message_id: str,
    ) -> GmailMessageMetadata:
        """Retrieve approved metadata headers before content."""

    def get_message_full(
        self,
        authorization: GmailAuthorization,
        message_id: str,
    ) -> GmailFullMessage:
        """Retrieve one approved candidate with `format=full`."""


class GmailMessageClassification(StrEnum):
    """Conservative metadata-first body-retrieval categories."""

    OUTBOUND = "outbound"
    DIRECT_INBOUND = "direct_inbound"
    AUTOMATED = "automated"
    BULK = "bulk"
    PROMOTIONAL = "promotional_social_or_forum"
    SELF_MESSAGE = "self_message"
    UNSUPPORTED = "unsupported_or_ambiguous"


@dataclass(frozen=True, slots=True)
class GmailBoundedStream:
    """One exact query, time window, and pre-expansion message cap."""

    stream: GmailStream
    query: str
    window_start: datetime
    window_end: datetime
    message_limit: int


@dataclass(frozen=True, slots=True)
class GmailBodyCandidate:
    """One metadata-classified eligible body candidate kept private in memory."""

    message: GmailMessageMetadata = field(repr=False)
    stream: GmailStream


@dataclass(frozen=True, slots=True)
class GmailBodyCandidateSelection:
    """A deterministic bounded selection with private identities suppressed."""

    selected: tuple[GmailBodyCandidate, ...] = field(repr=False)
    omitted: tuple[GmailBodyCandidate, ...] = field(repr=False)
    inbound_eligible: int
    inbound_selected: int
    sent_eligible: int
    sent_selected: int

    @property
    def eligible_count(self) -> int:
        """Return the unique eligible-candidate count."""

        return self.inbound_eligible + self.sent_eligible

    @property
    def selected_count(self) -> int:
        """Return the bounded selected-candidate count."""

        return self.inbound_selected + self.sent_selected

    @property
    def omitted_count(self) -> int:
        """Return the count omitted without body retrieval."""

        return self.eligible_count - self.selected_count

    def eligible_for(self, stream: GmailStream) -> int:
        """Return eligible candidates assigned to one stream."""

        if stream is GmailStream.INBOUND:
            return self.inbound_eligible
        return self.sent_eligible

    def selected_for(self, stream: GmailStream) -> int:
        """Return selected candidates assigned to one stream."""

        if stream is GmailStream.INBOUND:
            return self.inbound_selected
        return self.sent_selected


class GmailDetectionType(StrEnum):
    """Deterministic conclusions available to the trial and briefing."""

    PEOPLE_WAITING = "people_waiting"
    EXPLICIT_COMMITMENT = "explicit_commitment"
    COMMITMENT_AT_RISK = "commitment_at_risk"


@dataclass(frozen=True, slots=True)
class GmailDetection:
    """One explicit, source-backed deterministic conclusion."""

    type: GmailDetectionType
    message_id: str
    thread_id: str
    statement: str
    explanation: str
    evidence_excerpt: str = field(repr=False)
    display_url: str
    detected_at: datetime
    due_at: datetime | None = None

    @property
    def evidence_fingerprint(self) -> str:
        """Return a stable fingerprint without exposing the excerpt."""

        material = (
            f"{self.type}\0{self.message_id}\0{self.thread_id}\0"
            f"{self.statement}\0{self.due_at.isoformat() if self.due_at else ''}"
        )
        return hashlib.sha256(material.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class GmailRejectedCandidate:
    """Private-review explanation for a bounded rejected sample."""

    message_id: str
    reason: str
    display_url: str


@dataclass(frozen=True, slots=True)
class GmailStreamAudit:
    """Privacy-safe aggregate facts for one completed retrieval stream."""

    stream: GmailStream
    window_start: datetime
    window_end: datetime
    status: str
    messages_listed: int
    pages: int
    duplicate_message_ids: int
    metadata_inspected: int
    body_candidates: int
    body_candidates_selected: int
    body_candidates_omitted: int
    body_fetches_attempted: int
    bodies_retrieved: int
    bodies_unavailable_or_unsupported: int
    automated_bulk_exclusions: int
    opaque_or_unsupported_messages: int


@dataclass(frozen=True, slots=True)
class GmailFailureAudit:
    """Privacy-safe aggregate state captured for the current failed run only."""

    connector_alias: str
    failure_stage: GmailFailureStage
    failure_category: GmailFailureCategory
    affected_stream: GmailStream | None
    retrieval_window_start: datetime
    retrieval_window_end: datetime
    configured_boundary_name: str | None
    configured_limit: int | None
    observed_aggregate_count: int | None
    pages_completed: int
    message_references_listed: int
    metadata_retrieval_began: bool
    metadata_records_inspected: int
    body_retrieval_began: bool
    bodies_retrieved: int
    persistence_began: bool
    raw_payloads_retained: bool
    occurred_at: datetime


@dataclass(slots=True)
class _GmailRetrievalProgress:
    """Mutable aggregate counters retained only for one connector call."""

    window_start: datetime
    window_end: datetime
    stage: GmailFailureStage = GmailFailureStage.INITIALIZATION
    affected_stream: GmailStream | None = None
    pages_completed: int = 0
    message_references_listed: int = 0
    metadata_retrieval_began: bool = False
    metadata_records_inspected: int = 0
    body_retrieval_began: bool = False
    bodies_retrieved: int = 0


@dataclass(frozen=True, slots=True)
class GmailRetrievalAudit:
    """Privacy-safe aggregate retrieval and detection facts."""

    messages_listed: int
    pages: int
    metadata_inspected: int
    direct_inbound_candidates: int
    outbound_candidates: int
    automated_bulk_exclusions: int
    body_candidates_eligible: int
    body_candidates_selected: int
    body_candidates_omitted: int
    body_fetches_attempted: int
    body_records_retrieved: int
    body_records_unavailable_or_unsupported: int
    body_candidate_cap_caused_partial_coverage: bool
    extracted_content_limit_caused_partial_coverage: bool
    opaque_or_unsupported_messages: int
    unique_threads: int
    explicit_requests_detected: int
    people_waiting_proposed: int
    explicit_commitments_detected: int
    commitments_at_risk_proposed: int
    duplicate_message_ids: int
    inbound: GmailStreamAudit
    sent: GmailStreamAudit
    concurrent_changes_cannot_be_excluded: bool = True


@dataclass(slots=True)
class GmailConnector:
    """Retrieve and classify one exact Work Gmail instance without mutation."""

    account_reference: str
    authorization_provider: GmailAuthorizationProvider
    transport: GmailTransport
    work_account: str = GMAIL_WORK_ACCOUNT
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
    )
    recurrence_resolver: Callable[[str], tuple[str, str | None]] = field(
        default=lambda _fingerprint: ("show", None),
        repr=False,
    )
    allow_window_fallback: bool = False
    allow_authorization_refresh: bool = False
    max_transient_attempts: int = 1
    failure_reporter: Callable[[GmailFailureAudit], None] | None = field(
        default=None,
        repr=False,
    )
    sleeper: Callable[[float], None] = field(
        default=time_module.sleep,
        repr=False,
    )
    last_audit: GmailRetrievalAudit | None = field(default=None, init=False)
    last_failure_audit: GmailFailureAudit | None = field(default=None, init=False)
    attempt_failure_audits: tuple[GmailFailureAudit, ...] = field(
        default=(),
        init=False,
    )
    last_attempt_count: int = field(default=0, init=False)
    last_proposed_detections: tuple[GmailDetection, ...] = field(
        default=(),
        init=False,
    )
    last_detections: tuple[GmailDetection, ...] = field(default=(), init=False)
    last_rejections: tuple[GmailRejectedCandidate, ...] = field(
        default=(),
        init=False,
    )
    _active_progress: _GmailRetrievalProgress | None = field(
        default=None,
        init=False,
        repr=False,
    )

    @property
    def source_name(self) -> str:
        """Return the provider identity."""

        return GMAIL_CONNECTOR

    @property
    def approved_scope(self) -> str:
        """Return the exact restricted read-only scope."""

        return GMAIL_READONLY_SCOPE

    def retrieve(self, request: ConnectorRequest) -> ConnectorResult:
        """Run one bounded retrieval with explicitly enabled safe recovery."""

        self.last_audit = None
        self.last_failure_audit = None
        self.attempt_failure_audits = ()
        self.last_attempt_count = 0
        self.last_proposed_detections = ()
        self.last_detections = ()
        self.last_rejections = ()
        inbound_days = GMAIL_DEFAULT_INBOUND_DAYS
        sent_days = GMAIL_DEFAULT_SENT_DAYS
        consecutive_transient_attempts = 0
        authorization_refreshed = False

        while True:
            progress = _GmailRetrievalProgress(
                window_start=request.window.starts_at,
                window_end=request.window.ends_at,
            )
            self._active_progress = progress
            self.last_attempt_count += 1
            try:
                streams = gmail_bounded_streams(
                    request.briefing_date,
                    request.timezone,
                    inbound_days=inbound_days,
                    sent_days=sent_days,
                )
                progress.window_start = min(stream.window_start for stream in streams)
                progress.window_end = max(stream.window_end for stream in streams)
                result = self._retrieve(request, streams)
            except GmailError as error:
                failure = self._failure_audit(error)
                self._record_failure(failure)
                reduced_window = self._reduce_window(
                    error,
                    inbound_days=inbound_days,
                    sent_days=sent_days,
                )
                if reduced_window is not None:
                    inbound_days, sent_days = reduced_window
                    consecutive_transient_attempts = 0
                    continue
                if (
                    error.category is GmailFailureCategory.AUTHORIZATION_UNAVAILABLE
                    and self.allow_authorization_refresh
                    and not authorization_refreshed
                    and self._refresh_authorization()
                ):
                    authorization_refreshed = True
                    consecutive_transient_attempts = 0
                    continue
                if _is_transient_gmail_failure(error):
                    consecutive_transient_attempts += 1
                    transient_attempt_limit = min(
                        max(self.max_transient_attempts, 1),
                        GMAIL_MAX_TRANSIENT_ATTEMPTS,
                    )
                    if consecutive_transient_attempts < transient_attempt_limit:
                        self.sleeper(
                            _gmail_retry_delay(
                                error,
                                consecutive_transient_attempts,
                            )
                        )
                        continue
                raise
            except Exception as error:
                diagnostic_error = GmailRetrievalError(
                    "unexpected internal Gmail failure",
                    category=GmailFailureCategory.UNEXPECTED_INTERNAL_FAILURE,
                    stage=self._progress().stage,
                    affected_stream=self._progress().affected_stream,
                )
                self._record_failure(self._failure_audit(diagnostic_error))
                raise diagnostic_error from error
            finally:
                self._active_progress = None
            self.last_failure_audit = None
            return result

    def _record_failure(self, failure: GmailFailureAudit) -> None:
        """Retain and report only safe aggregate facts for one failed attempt."""

        self.last_failure_audit = failure
        self.attempt_failure_audits = (*self.attempt_failure_audits, failure)
        if self.failure_reporter is not None:
            self.failure_reporter(failure)

    def _reduce_window(
        self,
        error: GmailError,
        *,
        inbound_days: int,
        sent_days: int,
    ) -> tuple[int, int] | None:
        """Narrow only a stream whose list cap was exceeded."""

        if not self.allow_window_fallback or not isinstance(
            error,
            GmailBoundaryExceeded,
        ):
            return None
        if (
            error.boundary == "inbound_messages"
            and inbound_days > GMAIL_MINIMUM_INBOUND_DAYS
        ):
            return inbound_days - 1, sent_days
        if error.boundary == "sent_messages" and sent_days > GMAIL_MINIMUM_SENT_DAYS:
            return inbound_days, sent_days - 1
        return None

    def _refresh_authorization(self) -> bool:
        """Perform at most one exact-scope refresh when the provider supports it."""

        refresh = getattr(
            self.authorization_provider,
            "refresh_gmail_authorization",
            None,
        )
        if not callable(refresh):
            return False
        try:
            refreshed = refresh(self.account_reference)
        except GmailError:
            return False
        return isinstance(
            refreshed, GmailAuthorization
        ) and refreshed.granted_scopes == frozenset({GMAIL_READONLY_SCOPE})

    def _retrieve(
        self,
        request: ConnectorRequest,
        streams: tuple[GmailBoundedStream, GmailBoundedStream],
    ) -> ConnectorResult:
        """Run listing, metadata-first filtering, bounded content, and detection."""

        progress = self._progress()
        if request.approved_scope != GMAIL_READONLY_SCOPE:
            raise GmailAuthenticationError(
                "Gmail request exceeded the approved scope",
                category=GmailFailureCategory.ACCOUNT_OR_SCOPE_MISMATCH,
            )
        progress.stage = GmailFailureStage.AUTHORIZATION
        authorization = self.authorization_provider.get_gmail_authorization(
            self.account_reference
        )
        if authorization.granted_scopes != frozenset({GMAIL_READONLY_SCOPE}):
            raise GmailAuthenticationError(
                "Gmail grant scope is not exact",
                category=GmailFailureCategory.ACCOUNT_OR_SCOPE_MISMATCH,
            )
        progress.stage = GmailFailureStage.PROFILE
        profile = self.transport.get_profile(authorization)
        if profile.email_address.casefold() != self.work_account.casefold():
            raise GmailAuthenticationError(
                "Gmail profile did not match Work Gmail",
                category=GmailFailureCategory.ACCOUNT_OR_SCOPE_MISMATCH,
                stage=GmailFailureStage.PROFILE,
            )
        stream_references: dict[GmailStream, tuple[GmailMessageReference, ...]] = {}
        stream_pages: dict[GmailStream, int] = {}
        stream_duplicates: dict[GmailStream, int] = {}
        references_by_id: dict[str, GmailMessageReference] = {}
        memberships: dict[str, set[GmailStream]] = {}
        cross_stream_duplicates = 0
        for stream in streams:
            progress.stage = GmailFailureStage.LISTING
            progress.affected_stream = stream.stream
            progress.window_start = stream.window_start
            progress.window_end = stream.window_end
            references, page_count, duplicate_count = self._list_stream(
                authorization,
                stream,
            )
            stream_references[stream.stream] = references
            stream_pages[stream.stream] = page_count
            stream_duplicates[stream.stream] = duplicate_count
            for reference in references:
                existing = references_by_id.get(reference.id)
                if existing is not None:
                    cross_stream_duplicates += 1
                    if existing.thread_id != reference.thread_id:
                        raise GmailRetrievalError(
                            "cross-stream Gmail message ID changed thread identity",
                            category=GmailFailureCategory.INVALID_PROVIDER_RESPONSE,
                            stage=GmailFailureStage.LISTING,
                        )
                else:
                    references_by_id[reference.id] = reference
                memberships.setdefault(reference.id, set()).add(stream.stream)
        progress.affected_stream = None
        progress.window_start = min(stream.window_start for stream in streams)
        progress.window_end = max(stream.window_end for stream in streams)
        if len(references_by_id) > GMAIL_MESSAGE_LIMIT:
            raise GmailBoundaryExceeded(
                "more than 500 unique Gmail messages matched the two bounded streams",
                boundary="combined_unique_messages",
                observed_count=len(references_by_id),
                limit=GMAIL_MESSAGE_LIMIT,
                stage=GmailFailureStage.LISTING,
            )

        references = tuple(references_by_id.values())
        metadata: list[GmailMessageMetadata] = []
        classifications: dict[str, GmailMessageClassification] = {}
        partial_warnings: list[str] = []
        partial_streams: set[GmailStream] = set()
        progress.stage = GmailFailureStage.METADATA
        progress.metadata_retrieval_began = bool(references)
        for reference in references:
            membership = memberships[reference.id]
            progress.affected_stream = (
                next(iter(membership)) if len(membership) == 1 else None
            )
            try:
                message = self.transport.get_message_metadata(
                    authorization,
                    reference.id,
                )
            except GmailAuthenticationError:
                raise
            except GmailRetrievalError as error:
                if _gmail_failure_requires_stop(error):
                    raise
                partial_warnings.append("one or more metadata records were unavailable")
                partial_streams.update(memberships[reference.id])
                continue
            if message.id != reference.id or message.thread_id != reference.thread_id:
                partial_warnings.append("one metadata record had inconsistent identity")
                partial_streams.update(memberships[reference.id])
                continue
            metadata.append(message)
            progress.metadata_records_inspected += 1
            classifications[message.id] = classify_gmail_metadata(
                message,
                self.work_account,
            )
        progress.affected_stream = None

        eligible_candidates = tuple(
            GmailBodyCandidate(
                message=message,
                stream=(
                    GmailStream.INBOUND
                    if classifications[message.id]
                    is GmailMessageClassification.DIRECT_INBOUND
                    else GmailStream.SENT
                ),
            )
            for message in metadata
            if (
                classifications[message.id] is GmailMessageClassification.DIRECT_INBOUND
                and GmailStream.INBOUND in memberships[message.id]
            )
            or (
                classifications[message.id] is GmailMessageClassification.OUTBOUND
                and GmailStream.SENT in memberships[message.id]
            )
        )
        candidate_selection = select_gmail_body_candidates(eligible_candidates)
        cap_omitted_ids = {
            candidate.message.id for candidate in candidate_selection.omitted
        }
        if candidate_selection.omitted_count:
            partial_warnings.append(
                "bounded body-candidate selection chose "
                f"{candidate_selection.selected_count} of "
                f"{candidate_selection.eligible_count} eligible messages; "
                f"{candidate_selection.omitted_count} were omitted without "
                "body retrieval"
            )
            partial_streams.update(
                candidate.stream for candidate in candidate_selection.omitted
            )

        bodies: dict[str, str] = {}
        unsupported_ids = {
            message_id
            for message_id, classification in classifications.items()
            if classification is GmailMessageClassification.UNSUPPORTED
        }
        body_unavailable_or_unsupported_ids: set[str] = set()
        body_fetch_attempted_ids: set[str] = set()
        content_limit_omitted_ids: set[str] = set()
        run_chars = 0
        for index, candidate in enumerate(candidate_selection.selected):
            message = candidate.message
            progress.stage = GmailFailureStage.BODY
            progress.affected_stream = candidate.stream
            if message.size_estimate > GMAIL_MAX_MESSAGE_SIZE_ESTIMATE:
                unsupported_ids.add(message.id)
                body_unavailable_or_unsupported_ids.add(message.id)
                partial_warnings.append(
                    "one or more candidate messages exceeded the content-size limit"
                )
                partial_streams.add(candidate.stream)
                continue
            progress.body_retrieval_began = True
            body_fetch_attempted_ids.add(message.id)
            try:
                full_message = self.transport.get_message_full(
                    authorization,
                    message.id,
                )
            except GmailAuthenticationError:
                raise
            except GmailRetrievalError as error:
                if _gmail_failure_requires_stop(error):
                    raise
                body_unavailable_or_unsupported_ids.add(message.id)
                partial_warnings.append("one or more candidate bodies were unavailable")
                partial_streams.add(candidate.stream)
                continue
            if (
                full_message.metadata.id != message.id
                or full_message.metadata.thread_id != message.thread_id
            ):
                body_unavailable_or_unsupported_ids.add(message.id)
                partial_warnings.append("one body record had inconsistent identity")
                partial_streams.add(candidate.stream)
                continue
            body = extract_minimized_message_text(full_message.payload)
            if body is None:
                unsupported_ids.add(message.id)
                body_unavailable_or_unsupported_ids.add(message.id)
                partial_warnings.append(
                    "one or more candidate bodies had no supported current-message text"
                )
                partial_streams.add(candidate.stream)
                continue
            if len(body) > GMAIL_MAX_MESSAGE_TEXT_CHARS:
                unsupported_ids.add(message.id)
                body_unavailable_or_unsupported_ids.add(message.id)
                partial_warnings.append(
                    "one or more candidate bodies exceeded the per-message "
                    "extracted-text limit"
                )
                partial_streams.add(candidate.stream)
                continue
            if run_chars + len(body) > GMAIL_MAX_RUN_TEXT_CHARS:
                remaining = candidate_selection.selected[index:]
                content_limit_omitted_ids.update(item.message.id for item in remaining)
                body_unavailable_or_unsupported_ids.update(
                    item.message.id for item in remaining
                )
                partial_streams.update(item.stream for item in remaining)
                break
            run_chars += len(body)
            bodies[message.id] = body
            progress.bodies_retrieved += 1
        if content_limit_omitted_ids:
            partial_warnings.append(
                "the total extracted-text limit preserved completed evidence "
                f"and omitted {len(content_limit_omitted_ids)} selected messages"
            )
        body_unavailable_or_unsupported_ids.update(
            candidate.message.id
            for candidate in candidate_selection.selected
            if candidate.message.id not in bodies
        )

        progress.stage = GmailFailureStage.PROCESSING
        progress.affected_stream = None
        proposed_detections, rejections = detect_gmail_conclusions(
            tuple(metadata),
            classifications,
            bodies,
            briefing_date=request.briefing_date,
        )
        effective_detections: list[GmailDetection] = []
        disposition_rejections: list[GmailRejectedCandidate] = []
        for detection in proposed_detections:
            action, replacement_text = self.recurrence_resolver(
                detection.evidence_fingerprint
            )
            if action == "suppress":
                disposition_rejections.append(
                    GmailRejectedCandidate(
                        detection.message_id,
                        "local disposition suppresses materially unchanged evidence",
                        detection.display_url,
                    )
                )
                continue
            if action == "replace":
                if replacement_text is None or not replacement_text.strip():
                    raise GmailRetrievalError(
                        "corrected Gmail conclusion omitted replacement text",
                        category=GmailFailureCategory.UNEXPECTED_INTERNAL_FAILURE,
                        stage=GmailFailureStage.PROCESSING,
                    )
                detection = replace(detection, statement=replacement_text.strip())
            elif action != "show":
                raise GmailRetrievalError(
                    "Gmail recurrence action was invalid",
                    category=GmailFailureCategory.UNEXPECTED_INTERNAL_FAILURE,
                    stage=GmailFailureStage.PROCESSING,
                )
            effective_detections.append(detection)
        detections = tuple(effective_detections)
        self.last_proposed_detections = proposed_detections
        self.last_detections = detections
        aggregate_only_omitted_ids = cap_omitted_ids | content_limit_omitted_ids
        self.last_rejections = (
            *(
                rejection
                for rejection in rejections
                if rejection.message_id not in aggregate_only_omitted_ids
            ),
            *disposition_rejections,
        )[:GMAIL_REVIEW_REJECTION_LIMIT]
        exclusion_classes = {
            GmailMessageClassification.AUTOMATED,
            GmailMessageClassification.BULK,
            GmailMessageClassification.PROMOTIONAL,
        }

        def stream_audit(stream: GmailBoundedStream) -> GmailStreamAudit:
            message_ids = {
                reference.id for reference in stream_references[stream.stream]
            }
            metadata_ids = message_ids & classifications.keys()
            eligible_ids = {
                candidate.message.id
                for candidate in eligible_candidates
                if candidate.stream is stream.stream
            }
            selected_stream_ids = {
                candidate.message.id
                for candidate in candidate_selection.selected
                if candidate.stream is stream.stream
            }
            omitted_stream_ids = {
                candidate.message.id
                for candidate in candidate_selection.omitted
                if candidate.stream is stream.stream
            }
            return GmailStreamAudit(
                stream=stream.stream,
                window_start=stream.window_start,
                window_end=stream.window_end,
                status=(
                    CoverageStatus.PARTIAL.value
                    if stream.stream in partial_streams
                    else CoverageStatus.COMPLETE.value
                ),
                messages_listed=len(message_ids),
                pages=stream_pages[stream.stream],
                duplicate_message_ids=stream_duplicates[stream.stream],
                metadata_inspected=len(metadata_ids),
                body_candidates=len(eligible_ids),
                body_candidates_selected=len(selected_stream_ids),
                body_candidates_omitted=len(omitted_stream_ids),
                body_fetches_attempted=len(
                    selected_stream_ids & body_fetch_attempted_ids
                ),
                bodies_retrieved=len(selected_stream_ids & bodies.keys()),
                bodies_unavailable_or_unsupported=len(
                    selected_stream_ids - bodies.keys()
                ),
                automated_bulk_exclusions=sum(
                    classifications[message_id] in exclusion_classes
                    for message_id in metadata_ids
                ),
                opaque_or_unsupported_messages=len(message_ids & unsupported_ids),
            )

        inbound_audit, sent_audit = (stream_audit(stream) for stream in streams)
        duplicate_count = sum(stream_duplicates.values()) + cross_stream_duplicates
        page_count = sum(stream_pages.values())
        self.last_audit = GmailRetrievalAudit(
            messages_listed=len(references),
            pages=page_count,
            metadata_inspected=len(metadata),
            direct_inbound_candidates=sum(
                value is GmailMessageClassification.DIRECT_INBOUND
                for value in classifications.values()
            ),
            outbound_candidates=sum(
                value is GmailMessageClassification.OUTBOUND
                for value in classifications.values()
            ),
            automated_bulk_exclusions=sum(
                value in exclusion_classes for value in classifications.values()
            ),
            body_candidates_eligible=candidate_selection.eligible_count,
            body_candidates_selected=candidate_selection.selected_count,
            body_candidates_omitted=candidate_selection.omitted_count,
            body_fetches_attempted=len(body_fetch_attempted_ids),
            body_records_retrieved=len(bodies),
            body_records_unavailable_or_unsupported=len(
                body_unavailable_or_unsupported_ids
            ),
            body_candidate_cap_caused_partial_coverage=bool(cap_omitted_ids),
            extracted_content_limit_caused_partial_coverage=bool(
                content_limit_omitted_ids
            ),
            opaque_or_unsupported_messages=len(unsupported_ids),
            unique_threads=len({message.thread_id for message in metadata}),
            explicit_requests_detected=sum(
                detection.type is GmailDetectionType.PEOPLE_WAITING
                for detection in proposed_detections
            ),
            people_waiting_proposed=sum(
                detection.type is GmailDetectionType.PEOPLE_WAITING
                for detection in proposed_detections
            ),
            explicit_commitments_detected=sum(
                detection.type
                in {
                    GmailDetectionType.EXPLICIT_COMMITMENT,
                    GmailDetectionType.COMMITMENT_AT_RISK,
                }
                for detection in proposed_detections
            ),
            commitments_at_risk_proposed=sum(
                detection.type is GmailDetectionType.COMMITMENT_AT_RISK
                for detection in proposed_detections
            ),
            duplicate_message_ids=duplicate_count,
            inbound=inbound_audit,
            sent=sent_audit,
        )

        retrieved_at = self.clock()
        status = CoverageStatus.PARTIAL if partial_warnings else CoverageStatus.COMPLETE
        context = self._coverage_resources()
        warnings = [
            "Gmail pagination is not a transactional mailbox snapshot",
            (
                "inbound stream "
                f"{inbound_audit.status}: {inbound_audit.window_start.isoformat()} "
                f"through {inbound_audit.window_end.isoformat()}"
            ),
            (
                "sent stream "
                f"{sent_audit.status}: {sent_audit.window_start.isoformat()} "
                f"through {sent_audit.window_end.isoformat()}"
            ),
            *dict.fromkeys(partial_warnings),
        ]
        return ConnectorResult(
            items=tuple(
                _source_item_from_detection(detection, retrieved_at)
                for detection in detections
            ),
            coverage=SourceCoverage(
                source=GMAIL_CONNECTOR,
                approved_scope=GMAIL_READONLY_SCOPE,
                status=status,
                retrieved_at=retrieved_at,
                record_count=len(detections),
                freshness_at=max(
                    (message.internal_date for message in metadata),
                    default=retrieved_at,
                ),
                warnings=tuple(warnings),
                error_category=(
                    (
                        "bounded_body_candidate_selection"
                        if cap_omitted_ids
                        else (
                            "extracted_content_boundary"
                            if content_limit_omitted_ids
                            else "partial_message_retrieval"
                        )
                    )
                    if partial_warnings
                    else None
                ),
                page_count=page_count,
                retrieved_count=len(references),
                selected_count=candidate_selection.selected_count,
                candidate_count=len(proposed_detections),
                context_resources=context,
            ),
        )

    def _list_stream(
        self,
        authorization: GmailAuthorization,
        stream: GmailBoundedStream,
    ) -> tuple[tuple[GmailMessageReference, ...], int, int]:
        references: dict[str, GmailMessageReference] = {}
        duplicate_count = 0
        page_count = 0
        page_token: str | None = None
        seen_tokens: set[str] = set()
        progress = self._progress()
        try:
            while True:
                page = self.transport.list_messages(
                    authorization,
                    GmailMessageListRequest(
                        query=stream.query,
                        page_token=page_token,
                    ),
                )
                page_count += 1
                progress.pages_completed += 1
                if page_count > GMAIL_PAGE_LIMIT:
                    raise GmailBoundaryExceeded(
                        "Gmail pagination exceeded its page limit",
                        boundary=f"{stream.stream.value}_pages",
                        observed_count=page_count,
                        limit=GMAIL_PAGE_LIMIT,
                        stage=GmailFailureStage.LISTING,
                        affected_stream=stream.stream,
                    )
                for reference in page.messages:
                    if not reference.id or not reference.thread_id:
                        continue
                    existing = references.get(reference.id)
                    if existing is not None:
                        duplicate_count += 1
                        if existing.thread_id != reference.thread_id:
                            raise GmailRetrievalError(
                                "duplicate Gmail message ID changed thread identity",
                                category=(
                                    GmailFailureCategory.INVALID_PROVIDER_RESPONSE
                                ),
                                stage=GmailFailureStage.LISTING,
                                affected_stream=stream.stream,
                            )
                        continue
                    references[reference.id] = reference
                    progress.message_references_listed += 1
                    if len(references) > stream.message_limit:
                        raise GmailBoundaryExceeded(
                            f"more than {stream.message_limit} Gmail messages matched "
                            f"the {stream.stream.value} stream",
                            boundary=f"{stream.stream.value}_messages",
                            observed_count=len(references),
                            limit=stream.message_limit,
                            stage=GmailFailureStage.LISTING,
                            affected_stream=stream.stream,
                        )
                page_token = page.next_page_token
                if page_token is None:
                    break
                if not page_token or page_token in seen_tokens:
                    raise GmailRetrievalError(
                        "Gmail returned an invalid page token",
                        category=GmailFailureCategory.PAGINATION_FAILURE,
                        stage=GmailFailureStage.LISTING,
                        affected_stream=stream.stream,
                    )
                seen_tokens.add(page_token)
        finally:
            page_token = None
            seen_tokens.clear()
        return tuple(references.values()), page_count, duplicate_count

    def _progress(self) -> _GmailRetrievalProgress:
        progress = self._active_progress
        if progress is None:
            raise RuntimeError("Gmail retrieval progress is unavailable")
        return progress

    def _failure_audit(self, error: GmailError) -> GmailFailureAudit:
        progress = self._progress()
        boundary_name: str | None = None
        configured_limit: int | None = None
        observed_count: int | None = None
        if isinstance(error, GmailBoundaryExceeded):
            boundary_name = error.boundary
            configured_limit = error.limit
            observed_count = error.observed_count
        return GmailFailureAudit(
            connector_alias=GMAIL_WORK_ALIAS,
            failure_stage=error.stage,
            failure_category=error.category,
            affected_stream=error.affected_stream or progress.affected_stream,
            retrieval_window_start=progress.window_start,
            retrieval_window_end=progress.window_end,
            configured_boundary_name=boundary_name,
            configured_limit=configured_limit,
            observed_aggregate_count=observed_count,
            pages_completed=progress.pages_completed,
            message_references_listed=progress.message_references_listed,
            metadata_retrieval_began=progress.metadata_retrieval_began,
            metadata_records_inspected=progress.metadata_records_inspected,
            body_retrieval_began=progress.body_retrieval_began,
            bodies_retrieved=progress.bodies_retrieved,
            persistence_began=False,
            raw_payloads_retained=False,
            occurred_at=self.clock(),
        )

    def _coverage_resources(self) -> tuple[ContextResourceCoverage, ...]:
        audit = self.last_audit
        if audit is None:
            return ()
        return (
            ContextResourceCoverage(
                "inbound stream messages",
                audit.inbound.messages_listed,
            ),
            ContextResourceCoverage("inbound stream pages", audit.inbound.pages),
            ContextResourceCoverage(
                "inbound stream duplicates",
                audit.inbound.duplicate_message_ids,
            ),
            ContextResourceCoverage(
                "inbound stream metadata",
                audit.inbound.metadata_inspected,
            ),
            ContextResourceCoverage(
                "inbound eligible body candidates",
                audit.inbound.body_candidates,
            ),
            ContextResourceCoverage(
                "inbound selected body candidates",
                audit.inbound.body_candidates_selected,
            ),
            ContextResourceCoverage(
                "inbound omitted body candidates",
                audit.inbound.body_candidates_omitted,
            ),
            ContextResourceCoverage(
                "inbound body fetches attempted",
                audit.inbound.body_fetches_attempted,
            ),
            ContextResourceCoverage(
                "inbound usable bodies",
                audit.inbound.bodies_retrieved,
            ),
            ContextResourceCoverage(
                "inbound bodies unavailable or unsupported",
                audit.inbound.bodies_unavailable_or_unsupported,
            ),
            ContextResourceCoverage(
                "inbound stream automated, bulk, or unsupported",
                audit.inbound.automated_bulk_exclusions
                + audit.inbound.opaque_or_unsupported_messages,
            ),
            ContextResourceCoverage("sent stream messages", audit.sent.messages_listed),
            ContextResourceCoverage("sent stream pages", audit.sent.pages),
            ContextResourceCoverage(
                "sent stream duplicates",
                audit.sent.duplicate_message_ids,
            ),
            ContextResourceCoverage(
                "sent stream metadata", audit.sent.metadata_inspected
            ),
            ContextResourceCoverage(
                "sent eligible body candidates",
                audit.sent.body_candidates,
            ),
            ContextResourceCoverage(
                "sent selected body candidates",
                audit.sent.body_candidates_selected,
            ),
            ContextResourceCoverage(
                "sent omitted body candidates",
                audit.sent.body_candidates_omitted,
            ),
            ContextResourceCoverage(
                "sent body fetches attempted",
                audit.sent.body_fetches_attempted,
            ),
            ContextResourceCoverage(
                "sent usable bodies",
                audit.sent.bodies_retrieved,
            ),
            ContextResourceCoverage(
                "sent bodies unavailable or unsupported",
                audit.sent.bodies_unavailable_or_unsupported,
            ),
            ContextResourceCoverage(
                "sent stream automated, bulk, or unsupported",
                audit.sent.automated_bulk_exclusions
                + audit.sent.opaque_or_unsupported_messages,
            ),
            ContextResourceCoverage("combined unique messages", audit.messages_listed),
            ContextResourceCoverage(
                "direct inbound candidates",
                audit.direct_inbound_candidates,
            ),
            ContextResourceCoverage("outbound candidates", audit.outbound_candidates),
            ContextResourceCoverage(
                "automated and bulk exclusions",
                audit.automated_bulk_exclusions,
            ),
            ContextResourceCoverage(
                "eligible body candidates",
                audit.body_candidates_eligible,
            ),
            ContextResourceCoverage(
                "selected body candidates",
                audit.body_candidates_selected,
            ),
            ContextResourceCoverage(
                "omitted body candidates",
                audit.body_candidates_omitted,
            ),
            ContextResourceCoverage(
                "body fetches attempted",
                audit.body_fetches_attempted,
            ),
            ContextResourceCoverage(
                "usable candidate bodies",
                audit.body_records_retrieved,
            ),
            ContextResourceCoverage(
                "bodies unavailable or unsupported",
                audit.body_records_unavailable_or_unsupported,
            ),
            ContextResourceCoverage("unique threads", audit.unique_threads),
            ContextResourceCoverage(
                "explicit detections",
                audit.people_waiting_proposed + audit.explicit_commitments_detected,
            ),
        )


def _gmail_failure_requires_stop(error: GmailRetrievalError) -> bool:
    """Return whether an operation-level failure invalidates the bounded run."""

    return error.category is not GmailFailureCategory.INVALID_PROVIDER_RESPONSE


def _is_transient_gmail_failure(error: GmailError) -> bool:
    """Return whether the exact same bounded read may be retried."""

    return error.category in {
        GmailFailureCategory.RATE_LIMITING,
        GmailFailureCategory.TIMEOUT,
        GmailFailureCategory.NETWORK_OR_TRANSPORT_FAILURE,
        GmailFailureCategory.PROVIDER_SERVER_FAILURE,
    }


def _gmail_retry_delay(error: GmailError, failed_attempts: int) -> float:
    """Return a bounded provider-directed or exponential retry delay."""

    if error.retry_after_seconds is not None:
        return float(
            min(
                max(error.retry_after_seconds, 0),
                GMAIL_MAX_RETRY_DELAY_SECONDS,
            )
        )
    return float(
        min(
            2 ** max(failed_attempts - 1, 0),
            GMAIL_MAX_RETRY_DELAY_SECONDS,
        )
    )


def gmail_bounded_streams(
    briefing_date: date,
    timezone: str,
    *,
    inbound_days: int = GMAIL_DEFAULT_INBOUND_DAYS,
    sent_days: int = GMAIL_DEFAULT_SENT_DAYS,
) -> tuple[GmailBoundedStream, GmailBoundedStream]:
    """Return exact inbound and sent stream boundaries through briefing day."""

    if not GMAIL_MINIMUM_INBOUND_DAYS <= inbound_days <= GMAIL_DEFAULT_INBOUND_DAYS:
        raise ValueError("inbound Gmail window is outside its accepted range")
    if not GMAIL_MINIMUM_SENT_DAYS <= sent_days <= GMAIL_DEFAULT_SENT_DAYS:
        raise ValueError("sent Gmail window is outside its accepted range")
    zone = ZoneInfo(timezone)
    ends_at = datetime.combine(
        briefing_date + timedelta(days=1),
        time.min,
        tzinfo=zone,
    )
    inbound_starts_at = datetime.combine(
        briefing_date - timedelta(days=inbound_days),
        time.min,
        tzinfo=zone,
    )
    sent_starts_at = datetime.combine(
        briefing_date - timedelta(days=sent_days),
        time.min,
        tzinfo=zone,
    )
    inbound_query = (
        f"after:{int(inbound_starts_at.timestamp())} "
        f"before:{int(ends_at.timestamp())} "
        "-in:sent -in:drafts -in:spam -in:trash "
        "-category:promotions -category:social -category:forums"
    )
    sent_query = (
        f"after:{int(sent_starts_at.timestamp())} "
        f"before:{int(ends_at.timestamp())} in:sent -in:drafts"
    )
    return (
        GmailBoundedStream(
            stream=GmailStream.INBOUND,
            query=inbound_query,
            window_start=inbound_starts_at,
            window_end=ends_at,
            message_limit=GMAIL_INBOUND_MESSAGE_LIMIT,
        ),
        GmailBoundedStream(
            stream=GmailStream.SENT,
            query=sent_query,
            window_start=sent_starts_at,
            window_end=ends_at,
            message_limit=GMAIL_SENT_MESSAGE_LIMIT,
        ),
    )


def select_gmail_body_candidates(
    candidates: tuple[GmailBodyCandidate, ...],
    *,
    limit: int = GMAIL_BODY_CANDIDATE_LIMIT,
) -> GmailBodyCandidateSelection:
    """Select a proportional, recent, stable subset without inspecting content."""

    if limit < 0:
        raise ValueError("Gmail body-candidate limit must not be negative")
    bounded_limit = min(limit, GMAIL_BODY_CANDIDATE_LIMIT)
    unique: dict[str, GmailBodyCandidate] = {}
    for candidate in sorted(
        candidates,
        key=lambda item: (item.message.id, item.stream.value),
    ):
        existing = unique.get(candidate.message.id)
        if existing is None:
            unique[candidate.message.id] = candidate
            continue
        if existing.message != candidate.message:
            raise ValueError("duplicate Gmail candidate metadata was inconsistent")

    grouped = {
        stream: tuple(
            sorted(
                (
                    candidate
                    for candidate in unique.values()
                    if candidate.stream is stream
                ),
                key=lambda item: (
                    -item.message.internal_date.timestamp(),
                    item.message.id,
                ),
            )
        )
        for stream in (GmailStream.INBOUND, GmailStream.SENT)
    }
    counts = {stream: len(values) for stream, values in grouped.items()}
    total = sum(counts.values())
    capacity = min(total, bounded_limit)
    allocations = _proportional_gmail_allocations(counts, capacity)
    selected = tuple(
        candidate
        for stream in (GmailStream.INBOUND, GmailStream.SENT)
        for candidate in grouped[stream][: allocations[stream]]
    )
    omitted = tuple(
        candidate
        for stream in (GmailStream.INBOUND, GmailStream.SENT)
        for candidate in grouped[stream][allocations[stream] :]
    )
    return GmailBodyCandidateSelection(
        selected=selected,
        omitted=omitted,
        inbound_eligible=counts[GmailStream.INBOUND],
        inbound_selected=allocations[GmailStream.INBOUND],
        sent_eligible=counts[GmailStream.SENT],
        sent_selected=allocations[GmailStream.SENT],
    )


def _proportional_gmail_allocations(
    counts: dict[GmailStream, int],
    capacity: int,
) -> dict[GmailStream, int]:
    """Allocate capacity by largest remainder and redistribute unused slots."""

    streams = (GmailStream.INBOUND, GmailStream.SENT)
    total = sum(counts.get(stream, 0) for stream in streams)
    if capacity <= 0 or total <= 0:
        return {stream: 0 for stream in streams}
    if capacity >= total:
        return {stream: counts.get(stream, 0) for stream in streams}

    allocations = {
        stream: min(
            counts.get(stream, 0),
            capacity * counts.get(stream, 0) // total,
        )
        for stream in streams
    }
    remainders = {
        stream: capacity * counts.get(stream, 0) % total for stream in streams
    }
    unallocated = capacity - sum(allocations.values())
    priority = sorted(
        streams,
        key=lambda stream: (-remainders[stream], streams.index(stream)),
    )
    while unallocated:
        distributed = False
        for stream in priority:
            if allocations[stream] >= counts.get(stream, 0):
                continue
            allocations[stream] += 1
            unallocated -= 1
            distributed = True
            if not unallocated:
                break
        if not distributed:
            break
    return allocations


def classify_gmail_metadata(
    message: GmailMessageMetadata,
    work_account: str,
) -> GmailMessageClassification:
    """Classify one message without inspecting its body."""

    labels = {label.upper() for label in message.label_ids}
    if labels & {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS"}:
        return GmailMessageClassification.PROMOTIONAL
    if labels & {"DRAFT", "SPAM", "TRASH"}:
        return GmailMessageClassification.UNSUPPORTED

    sender = _addresses(message.header("From"))
    recipients = _addresses(
        ", ".join(
            value
            for value in (
                message.header("To"),
                message.header("Cc"),
                message.header("Bcc"),
            )
            if value
        )
    )
    account = work_account.casefold()
    outbound = account in sender
    intended_recipient = account in recipients
    if outbound and intended_recipient:
        return GmailMessageClassification.SELF_MESSAGE

    auto_submitted = (message.header("Auto-Submitted") or "").casefold()
    precedence = (message.header("Precedence") or "").casefold()
    local_parts = {address.split("@", 1)[0] for address in sender if "@" in address}
    if auto_submitted not in {"", "no"} or local_parts & _AUTOMATED_LOCAL_PARTS:
        return GmailMessageClassification.AUTOMATED
    if (
        message.header("List-Id")
        or message.header("List-Unsubscribe")
        or precedence in {"bulk", "list", "junk"}
    ):
        return GmailMessageClassification.BULK
    if outbound:
        return GmailMessageClassification.OUTBOUND
    if sender and intended_recipient:
        return GmailMessageClassification.DIRECT_INBOUND
    return GmailMessageClassification.UNSUPPORTED


def extract_minimized_message_text(part: GmailMimePart) -> str | None:
    """Extract inert current-message text without attachments or quoted history."""

    plain: list[str] = []
    html: list[str] = []

    def visit(candidate: GmailMimePart) -> None:
        if candidate.filename or candidate.attachment_id:
            return
        mime_type = candidate.mime_type.casefold()
        if mime_type == "text/plain" and candidate.body_data is not None:
            decoded = _decode_body(candidate.body_data)
            if decoded is not None:
                plain.append(decoded)
        elif mime_type == "text/html" and candidate.body_data is not None:
            decoded = _decode_body(candidate.body_data)
            if decoded is not None:
                html.append(_sanitize_html(decoded))
        for child in candidate.parts:
            visit(child)

    visit(part)
    selected = "\n".join(value for value in plain if value.strip())
    if not selected.strip():
        selected = "\n".join(value for value in html if value.strip())
    minimized = _minimize_current_message(selected)
    return minimized or None


def detect_gmail_conclusions(
    metadata: tuple[GmailMessageMetadata, ...],
    classifications: dict[str, GmailMessageClassification],
    bodies: dict[str, str],
    *,
    briefing_date: date,
) -> tuple[tuple[GmailDetection, ...], tuple[GmailRejectedCandidate, ...]]:
    """Detect only explicit requests and attributable sent promises."""

    by_thread: dict[str, list[GmailMessageMetadata]] = {}
    for message in metadata:
        by_thread.setdefault(message.thread_id, []).append(message)
    for messages in by_thread.values():
        messages.sort(key=lambda item: item.internal_date)

    detections: list[GmailDetection] = []
    rejections: list[GmailRejectedCandidate] = []
    for message in sorted(metadata, key=lambda item: item.internal_date):
        classification = classifications.get(
            message.id,
            GmailMessageClassification.UNSUPPORTED,
        )
        body = bodies.get(message.id)
        display_url = gmail_message_url(message.id)
        if body is None:
            if classification in {
                GmailMessageClassification.OUTBOUND,
                GmailMessageClassification.DIRECT_INBOUND,
            }:
                rejections.append(
                    GmailRejectedCandidate(
                        message.id,
                        "candidate content was unavailable or unsupported",
                        display_url,
                    )
                )
            continue
        if any(pattern.search(body) for pattern in _INSTRUCTION_LIKE_PATTERNS):
            rejections.append(
                GmailRejectedCandidate(
                    message.id,
                    "instruction-like message content remained inert",
                    display_url,
                )
            )
            continue

        if classification is GmailMessageClassification.DIRECT_INBOUND:
            request_match = next(
                (
                    pattern.search(body)
                    for pattern in _REQUEST_PATTERNS
                    if pattern.search(body)
                ),
                None,
            )
            if request_match is None:
                rejections.append(
                    GmailRejectedCandidate(
                        message.id,
                        "no explicit request phrase was present",
                        display_url,
                    )
                )
                continue
            if _thread_may_start_outside_window(message, by_thread[message.thread_id]):
                rejections.append(
                    GmailRejectedCandidate(
                        message.id,
                        "bounded evidence did not establish complete reply state",
                        display_url,
                    )
                )
                continue
            if _has_later_outbound(
                message,
                by_thread[message.thread_id],
                classifications,
            ):
                rejections.append(
                    GmailRejectedCandidate(
                        message.id,
                        "a later bounded outbound response was present",
                        display_url,
                    )
                )
                continue
            excerpt = _sentence_around(body, request_match.start())
            detections.append(
                GmailDetection(
                    type=GmailDetectionType.PEOPLE_WAITING,
                    message_id=message.id,
                    thread_id=message.thread_id,
                    statement=_waiting_statement(message),
                    explanation=(
                        "A direct inbound human message contains an explicit "
                        "request and no later bounded outbound response."
                    ),
                    evidence_excerpt=excerpt,
                    display_url=display_url,
                    detected_at=message.internal_date,
                )
            )
            continue

        if classification is GmailMessageClassification.OUTBOUND:
            commitment_match = _COMMITMENT_PATTERN.search(body)
            if commitment_match is None:
                rejections.append(
                    GmailRejectedCandidate(
                        message.id,
                        "no attributable direct promise was present",
                        display_url,
                    )
                )
                continue
            excerpt = _sentence_around(body, commitment_match.start())
            due_at = _parse_supported_due_date(excerpt, message.internal_date)
            completed = _later_completion_evidence(
                message,
                by_thread[message.thread_id],
                classifications,
                bodies,
            )
            detection_type = GmailDetectionType.EXPLICIT_COMMITMENT
            explanation = "Brad's sent message contains an attributable direct promise."
            if (
                due_at is not None
                and due_at.date() <= briefing_date + timedelta(days=3)
                and not completed
            ):
                detection_type = GmailDetectionType.COMMITMENT_AT_RISK
                explanation = (
                    "Brad's sent message contains an attributable direct promise "
                    "with a supported due date that is due soon or overdue, and "
                    "no later bounded completion or renegotiation evidence."
                )
            detections.append(
                GmailDetection(
                    type=detection_type,
                    message_id=message.id,
                    thread_id=message.thread_id,
                    statement=_commitment_statement(message),
                    explanation=explanation,
                    evidence_excerpt=excerpt,
                    display_url=display_url,
                    detected_at=message.internal_date,
                    due_at=due_at,
                )
            )
    latest_waiting_by_thread: dict[str, GmailDetection] = {}
    retained: list[GmailDetection] = []
    for detection in detections:
        if detection.type is GmailDetectionType.PEOPLE_WAITING:
            latest_waiting_by_thread[detection.thread_id] = detection
        else:
            retained.append(detection)
    retained.extend(latest_waiting_by_thread.values())
    retained.sort(key=lambda detection: detection.detected_at)
    return tuple(retained), tuple(rejections)


def gmail_message_url(message_id: str) -> str:
    """Return the authoritative Gmail message link without thread expansion."""

    return f"https://mail.google.com/mail/u/0/#all/{message_id}"


def _source_item_from_detection(
    detection: GmailDetection,
    retrieved_at: datetime,
) -> SourceItem:
    item_type = (
        "waiting_item"
        if detection.type is GmailDetectionType.PEOPLE_WAITING
        else "commitment"
    )
    facts: dict[str, str | int | bool | tuple[str, ...] | None] = {
        "title": detection.statement,
        "summary": detection.explanation,
        "importance": 4,
        "explicit_commitment": (
            detection.type is GmailDetectionType.COMMITMENT_AT_RISK
        ),
        "status": "explicit",
        "all_day": detection.due_at is not None,
        "due_at": (None if detection.due_at is None else detection.due_at.isoformat()),
    }
    return SourceItem(
        id=f"{detection.type}:{detection.message_id}",
        source_record_id=detection.message_id,
        item_type=item_type,
        facts=facts,
        retrieved_at=retrieved_at,
        freshness_at=detection.detected_at,
        display_url=detection.display_url,
    )


def _addresses(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return frozenset(
        address.casefold() for _name, address in getaddresses([value]) if "@" in address
    )


def _decode_body(value: str) -> str | None:
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        return raw.decode("utf-8")
    except UnicodeDecodeError, UnicodeEncodeError, binascii.Error, ValueError:
        return None


class _SafeHTMLTextExtractor(HTMLParser):
    """Extract text while discarding active and remote-resource elements."""

    _blocked = frozenset({"script", "style", "form", "img", "svg", "iframe"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocked_depth = 0
        self.text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag.casefold() in self._blocked:
            self.blocked_depth += 1
        elif self.blocked_depth == 0 and tag.casefold() in {"br", "p", "div", "li"}:
            self.text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self._blocked and self.blocked_depth:
            self.blocked_depth -= 1
        elif self.blocked_depth == 0 and tag.casefold() in {"p", "div", "li"}:
            self.text.append("\n")

    def handle_data(self, data: str) -> None:
        if self.blocked_depth == 0:
            self.text.append(data)


def _sanitize_html(value: str) -> str:
    parser = _SafeHTMLTextExtractor()
    parser.feed(value)
    parser.close()
    return "".join(parser.text)


def _minimize_current_message(value: str) -> str:
    lines: list[str] = []
    for raw_line in value.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw_line.strip()
        if line.startswith(">") or any(marker.match(line) for marker in _QUOTE_MARKERS):
            break
        if line in {"--", "-- "} or line.casefold().startswith("sent from my "):
            break
        if lines and line.casefold() in {
            "best,",
            "regards,",
            "sincerely,",
            "thanks,",
            "thank you,",
        }:
            break
        if line:
            lines.append(re.sub(r"\s+", " ", line))
    return "\n".join(lines).strip()


def _has_later_outbound(
    message: GmailMessageMetadata,
    thread: list[GmailMessageMetadata],
    classifications: dict[str, GmailMessageClassification],
) -> bool:
    return any(
        candidate.internal_date > message.internal_date
        and classifications.get(candidate.id) is GmailMessageClassification.OUTBOUND
        for candidate in thread
    )


def _thread_may_start_outside_window(
    message: GmailMessageMetadata,
    thread: list[GmailMessageMetadata],
) -> bool:
    has_reference = bool(message.header("In-Reply-To") or message.header("References"))
    earlier_in_window = any(
        candidate.internal_date < message.internal_date for candidate in thread
    )
    return has_reference and not earlier_in_window


def _later_completion_evidence(
    message: GmailMessageMetadata,
    thread: list[GmailMessageMetadata],
    classifications: dict[str, GmailMessageClassification],
    bodies: dict[str, str],
) -> bool:
    return any(
        candidate.internal_date > message.internal_date
        and classifications.get(candidate.id) is GmailMessageClassification.OUTBOUND
        and any(
            pattern.search(bodies.get(candidate.id, ""))
            for pattern in _COMPLETION_PATTERNS
        )
        for candidate in thread
    )


def _sentence_around(body: str, start: int) -> str:
    left = max(body.rfind(".", 0, start), body.rfind("\n", 0, start))
    right_candidates = tuple(
        position
        for position in (
            body.find(".", start),
            body.find("!", start),
            body.find("?", start),
            body.find("\n", start),
        )
        if position >= 0
    )
    right = min(right_candidates) + 1 if right_candidates else len(body)
    sentence = body[left + 1 : right].strip()
    return sentence[:280].rstrip()


def _waiting_statement(message: GmailMessageMetadata) -> str:
    subject = _clean_subject(message.header("Subject"))
    return f"Respond to the explicit Work Gmail request: {subject}"


def _commitment_statement(message: GmailMessageMetadata) -> str:
    subject = _clean_subject(message.header("Subject"))
    return f"Honor the explicit Work Gmail commitment: {subject}"


def _clean_subject(value: str | None) -> str:
    subject = re.sub(r"^(?:(?:re|fw|fwd):\s*)+", "", value or "", flags=re.I)
    subject = re.sub(r"\s+", " ", subject).strip()
    return subject[:160] or "(no subject)"


def _parse_supported_due_date(
    excerpt: str,
    sent_at: datetime,
) -> datetime | None:
    zone = sent_at.tzinfo or UTC
    iso_match = re.search(r"\bby\s+(\d{4}-\d{2}-\d{2})\b", excerpt, re.I)
    if iso_match:
        try:
            parsed = date.fromisoformat(iso_match.group(1))
        except ValueError:
            return None
        return datetime.combine(parsed, time.min, tzinfo=zone)

    relative_match = re.search(r"\bby\s+(today|tomorrow)\b", excerpt, re.I)
    if relative_match:
        offset = 1 if relative_match.group(1).casefold() == "tomorrow" else 0
        return datetime.combine(
            sent_at.date() + timedelta(days=offset),
            time.min,
            tzinfo=zone,
        )

    month_match = re.search(
        r"\bby\s+(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+(\d{1,2})(?:,\s*(\d{4}))?\b",
        excerpt,
        re.I,
    )
    if month_match:
        year = int(month_match.group(3) or sent_at.year)
        try:
            parsed = datetime.strptime(
                f"{month_match.group(1)} {month_match.group(2)} {year}",
                "%B %d %Y",
            ).date()
        except ValueError:
            return None
        return datetime.combine(parsed, time.min, tzinfo=zone)

    weekday_match = re.search(
        r"\bby\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
        excerpt,
        re.I,
    )
    if weekday_match:
        weekdays = {
            name.casefold(): index
            for index, name in enumerate(
                (
                    "Monday",
                    "Tuesday",
                    "Wednesday",
                    "Thursday",
                    "Friday",
                    "Saturday",
                    "Sunday",
                )
            )
        }
        target = weekdays[weekday_match.group(1).casefold()]
        delta = (target - sent_at.weekday()) % 7
        return datetime.combine(
            sent_at.date() + timedelta(days=delta),
            time.min,
            tzinfo=zone,
        )
    return None
