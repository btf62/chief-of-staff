"""High-precision, read-only Work Gmail connector with inert MIME handling."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
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
GMAIL_PROCESSING_VERSION: Final = "gmail-deterministic-v2"

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


class GmailError(RuntimeError):
    """Base error for the bounded Work Gmail connector."""


class GmailAuthenticationError(GmailError):
    """Raised when the exact Work Gmail authorization is unavailable."""


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
    ) -> None:
        super().__init__(message)
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


class GmailStream(StrEnum):
    """The two independently bounded Work Gmail retrieval streams."""

    INBOUND = "inbound"
    SENT = "sent"


@dataclass(frozen=True, slots=True)
class GmailBoundedStream:
    """One exact query, time window, and pre-expansion message cap."""

    stream: GmailStream
    query: str
    window_start: datetime
    window_end: datetime
    message_limit: int


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
    bodies_retrieved: int
    automated_bulk_exclusions: int
    opaque_or_unsupported_messages: int


@dataclass(frozen=True, slots=True)
class GmailRetrievalAudit:
    """Privacy-safe aggregate retrieval and detection facts."""

    messages_listed: int
    pages: int
    metadata_inspected: int
    direct_inbound_candidates: int
    outbound_candidates: int
    automated_bulk_exclusions: int
    body_records_retrieved: int
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
    last_audit: GmailRetrievalAudit | None = field(default=None, init=False)
    last_proposed_detections: tuple[GmailDetection, ...] = field(
        default=(),
        init=False,
    )
    last_detections: tuple[GmailDetection, ...] = field(default=(), init=False)
    last_rejections: tuple[GmailRejectedCandidate, ...] = field(
        default=(),
        init=False,
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
        """Run listing, metadata-first filtering, bounded content, and detection."""

        if request.approved_scope != GMAIL_READONLY_SCOPE:
            raise GmailRetrievalError("Gmail request exceeded the approved scope")
        authorization = self.authorization_provider.get_gmail_authorization(
            self.account_reference
        )
        if authorization.granted_scopes != frozenset({GMAIL_READONLY_SCOPE}):
            raise GmailAuthenticationError("Gmail grant scope is not exact")
        profile = self.transport.get_profile(authorization)
        if profile.email_address.casefold() != self.work_account.casefold():
            raise GmailAuthenticationError("Gmail profile did not match Work Gmail")

        streams = gmail_bounded_streams(
            request.briefing_date,
            request.timezone,
        )
        stream_references: dict[GmailStream, tuple[GmailMessageReference, ...]] = {}
        stream_pages: dict[GmailStream, int] = {}
        stream_duplicates: dict[GmailStream, int] = {}
        references_by_id: dict[str, GmailMessageReference] = {}
        memberships: dict[str, set[GmailStream]] = {}
        cross_stream_duplicates = 0
        for stream in streams:
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
                            "cross-stream Gmail message ID changed thread identity"
                        )
                else:
                    references_by_id[reference.id] = reference
                memberships.setdefault(reference.id, set()).add(stream.stream)
        if len(references_by_id) > GMAIL_MESSAGE_LIMIT:
            raise GmailBoundaryExceeded(
                "more than 500 unique Gmail messages matched the two bounded streams",
                boundary="combined_unique_messages",
                observed_count=len(references_by_id),
                limit=GMAIL_MESSAGE_LIMIT,
            )

        references = tuple(references_by_id.values())
        metadata: list[GmailMessageMetadata] = []
        classifications: dict[str, GmailMessageClassification] = {}
        partial_warnings: list[str] = []
        partial_streams: set[GmailStream] = set()
        for reference in references:
            try:
                message = self.transport.get_message_metadata(
                    authorization,
                    reference.id,
                )
            except GmailAuthenticationError:
                raise
            except GmailRetrievalError:
                partial_warnings.append("one or more metadata records were unavailable")
                partial_streams.update(memberships[reference.id])
                continue
            if message.id != reference.id or message.thread_id != reference.thread_id:
                partial_warnings.append("one metadata record had inconsistent identity")
                partial_streams.update(memberships[reference.id])
                continue
            metadata.append(message)
            classifications[message.id] = classify_gmail_metadata(
                message,
                self.work_account,
            )

        candidate_messages = tuple(
            message
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
        if len(candidate_messages) > GMAIL_BODY_CANDIDATE_LIMIT:
            raise GmailBoundaryExceeded(
                "more than 120 Gmail messages qualified for body retrieval",
                boundary="body_candidates",
                observed_count=len(candidate_messages),
                limit=GMAIL_BODY_CANDIDATE_LIMIT,
            )

        bodies: dict[str, str] = {}
        unsupported_ids = {
            message_id
            for message_id, classification in classifications.items()
            if classification is GmailMessageClassification.UNSUPPORTED
        }
        run_chars = 0
        for message in candidate_messages:
            if message.size_estimate > GMAIL_MAX_MESSAGE_SIZE_ESTIMATE:
                unsupported_ids.add(message.id)
                partial_warnings.append(
                    "one or more candidate messages exceeded the content-size limit"
                )
                partial_streams.update(memberships[message.id])
                continue
            try:
                full_message = self.transport.get_message_full(
                    authorization,
                    message.id,
                )
            except GmailAuthenticationError:
                raise
            except GmailRetrievalError:
                partial_warnings.append("one or more candidate bodies were unavailable")
                partial_streams.update(memberships[message.id])
                continue
            if (
                full_message.metadata.id != message.id
                or full_message.metadata.thread_id != message.thread_id
            ):
                partial_warnings.append("one body record had inconsistent identity")
                partial_streams.update(memberships[message.id])
                continue
            body = extract_minimized_message_text(full_message.payload)
            if body is None:
                unsupported_ids.add(message.id)
                continue
            if len(body) > GMAIL_MAX_MESSAGE_TEXT_CHARS:
                body = body[:GMAIL_MAX_MESSAGE_TEXT_CHARS].rstrip()
            run_chars += len(body)
            if run_chars > GMAIL_MAX_RUN_TEXT_CHARS:
                raise GmailBoundaryExceeded(
                    "Gmail content run limit was exceeded",
                    boundary="content_characters",
                    observed_count=run_chars,
                    limit=GMAIL_MAX_RUN_TEXT_CHARS,
                )
            bodies[message.id] = body

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
                        "corrected Gmail conclusion omitted replacement text"
                    )
                detection = replace(detection, statement=replacement_text.strip())
            elif action != "show":
                raise GmailRetrievalError("Gmail recurrence action was invalid")
            effective_detections.append(detection)
        detections = tuple(effective_detections)
        self.last_proposed_detections = proposed_detections
        self.last_detections = detections
        self.last_rejections = (
            *rejections,
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
            candidate_ids = {message.id for message in candidate_messages} & message_ids
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
                body_candidates=len(candidate_ids),
                bodies_retrieved=len(message_ids & bodies.keys()),
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
            body_records_retrieved=len(bodies),
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
                    None if not partial_warnings else "partial_message_retrieval"
                ),
                page_count=page_count,
                retrieved_count=len(references),
                selected_count=len(candidate_messages),
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
        while True:
            page = self.transport.list_messages(
                authorization,
                GmailMessageListRequest(
                    query=stream.query,
                    page_token=page_token,
                ),
            )
            page_count += 1
            if page_count > GMAIL_PAGE_LIMIT:
                raise GmailBoundaryExceeded(
                    "Gmail pagination exceeded its page limit",
                    boundary=f"{stream.stream.value}_pages",
                    observed_count=page_count,
                    limit=GMAIL_PAGE_LIMIT,
                )
            for reference in page.messages:
                if not reference.id or not reference.thread_id:
                    continue
                existing = references.get(reference.id)
                if existing is not None:
                    duplicate_count += 1
                    if existing.thread_id != reference.thread_id:
                        raise GmailRetrievalError(
                            "duplicate Gmail message ID changed thread identity"
                        )
                    continue
                references[reference.id] = reference
                if len(references) > stream.message_limit:
                    raise GmailBoundaryExceeded(
                        f"more than {stream.message_limit} Gmail messages matched "
                        f"the {stream.stream.value} stream",
                        boundary=f"{stream.stream.value}_messages",
                        observed_count=len(references),
                        limit=stream.message_limit,
                    )
            page_token = page.next_page_token
            if page_token is None:
                break
            if not page_token or page_token in seen_tokens:
                raise GmailRetrievalError("Gmail returned an invalid page token")
            seen_tokens.add(page_token)
        return tuple(references.values()), page_count, duplicate_count

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
                "inbound stream body candidates",
                audit.inbound.body_candidates,
            ),
            ContextResourceCoverage(
                "inbound stream bodies",
                audit.inbound.bodies_retrieved,
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
                "sent stream body candidates",
                audit.sent.body_candidates,
            ),
            ContextResourceCoverage("sent stream bodies", audit.sent.bodies_retrieved),
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
                "candidate bodies",
                audit.body_records_retrieved,
            ),
            ContextResourceCoverage("unique threads", audit.unique_threads),
            ContextResourceCoverage(
                "explicit detections",
                audit.people_waiting_proposed + audit.explicit_commitments_detected,
            ),
        )


def gmail_bounded_streams(
    briefing_date: date,
    timezone: str,
) -> tuple[GmailBoundedStream, GmailBoundedStream]:
    """Return exact inbound and sent stream boundaries through briefing day."""

    zone = ZoneInfo(timezone)
    ends_at = datetime.combine(
        briefing_date + timedelta(days=1),
        time.min,
        tzinfo=zone,
    )
    inbound_starts_at = datetime.combine(
        briefing_date - timedelta(days=7),
        time.min,
        tzinfo=zone,
    )
    sent_starts_at = datetime.combine(
        briefing_date - timedelta(days=14),
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
