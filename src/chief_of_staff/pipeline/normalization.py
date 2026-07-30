"""Convert source envelopes into typed application records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from chief_of_staff.connectors import SourceItem
from chief_of_staff.domain import ConnectorDomain


class RecordKind(StrEnum):
    """Normalized source-record categories used by the reduced pipeline."""

    CALENDAR_EVENT = "calendar_event"
    TASK = "task"
    WAITING_ITEM = "waiting_item"
    COMMITMENT = "commitment"
    PREPARATION_ITEM = "preparation_item"
    CONTEXT = "context"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Authoritative source reference carried through composition."""

    source: str
    source_record_id: str
    display_url: str | None
    retrieved_at: datetime
    freshness_at: datetime | None
    connector_run_id: str | None = None
    connector_instance_id: str | None = None
    account_alias: str | None = None
    domain_classification: ConnectorDomain | None = None


@dataclass(frozen=True, slots=True)
class AssociatedSourceFacts:
    """Source-owned facts retained for a non-destructive association."""

    provenance: Provenance
    status: str | None
    status_category: str | None
    assignee_reference: str | None
    due_at: datetime | None
    all_day: bool
    source_priority: str | None
    provider_priority: int | None
    completion_state: bool | None


@dataclass(frozen=True, slots=True)
class NormalizedRecord:
    """Typed, source-authoritative facts without recommendation state."""

    id: str
    kind: RecordKind
    title: str
    summary: str | None
    status: str | None
    event_type: str | None
    importance: int
    explicit_commitment: bool
    preparation: str | None
    all_day: bool
    start_at: datetime | None
    end_at: datetime | None
    due_at: datetime | None
    provenance: Provenance
    provider_priority: int | None = None
    explicit_priority_link: bool = False
    calendar_dependency: bool = False
    effort_minutes: int | None = None
    source_priority: str | None = None
    project_reference: str | None = None
    issue_type: str | None = None
    status_category: str | None = None
    assignee_reference: str | None = None
    parent_reference: str | None = None
    labels: tuple[str, ...] = ()
    dependency_references: tuple[str, ...] = ()
    dependency_relationships: tuple[str, ...] = ()
    dependency_display_urls: tuple[str, ...] = ()
    membership_references: tuple[str, ...] = ()
    dependent_references: tuple[str, ...] = ()
    related_source_ids: tuple[str, ...] = ()
    blocked: bool = False
    source_owned_risk: bool = False
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    hard_deadline: bool = False
    primary_stewardship: bool = False
    relationship_consequence: bool = False
    six_month_goal: bool = False
    seasonal_initiative: bool = False
    delegation_opportunity: bool = False
    energy_requirement: str | None = None
    opportunity_cost: str | None = None
    uncertainty: str | None = None
    inference_explanation: str | None = None
    evidence_fingerprint: str | None = None
    associated_provenance: tuple[Provenance, ...] = ()
    associated_source_facts: tuple[AssociatedSourceFacts, ...] = ()
    association_conflicts: tuple[str, ...] = ()


def normalize_item(
    source: str,
    item: SourceItem,
    *,
    timezone: str,
) -> NormalizedRecord:
    """Validate and normalize one minimal connector result."""

    zone = ZoneInfo(timezone)
    try:
        kind = RecordKind(item.item_type)
    except ValueError:
        raise ValueError("unsupported source item type") from None

    title = _required_string(item, "title")
    importance = _integer(item, "importance", default=0)
    if not 0 <= importance <= 5:
        raise ValueError("importance must be between 0 and 5")

    return NormalizedRecord(
        id=(
            f"{source}:{item.connector_instance_id}:{item.id}"
            if item.connector_instance_id is not None
            else f"{source}:{item.id}"
        ),
        kind=kind,
        title=title,
        summary=_optional_string(item, "summary"),
        status=_optional_string(item, "status"),
        event_type=_optional_string(item, "event_type"),
        importance=importance,
        explicit_commitment=_boolean(item, "explicit_commitment", default=False),
        preparation=_optional_string(item, "preparation"),
        all_day=_boolean(item, "all_day", default=False),
        start_at=_optional_datetime(item, "start_at", zone),
        end_at=_optional_datetime(item, "end_at", zone),
        due_at=_optional_datetime(item, "due_at", zone),
        provenance=Provenance(
            source=source,
            source_record_id=item.source_record_id,
            display_url=item.display_url,
            retrieved_at=_aware(item.retrieved_at, zone),
            freshness_at=(
                None if item.freshness_at is None else _aware(item.freshness_at, zone)
            ),
            connector_run_id=item.connector_run_id,
            connector_instance_id=item.connector_instance_id,
            account_alias=item.account_alias,
            domain_classification=item.domain_classification,
        ),
        provider_priority=_optional_integer(item, "provider_priority"),
        explicit_priority_link=_boolean(
            item,
            "explicit_priority_link",
            default=False,
        ),
        calendar_dependency=_boolean(
            item,
            "calendar_dependency",
            default=False,
        ),
        effort_minutes=_optional_positive_integer(item, "effort_minutes"),
        source_priority=_optional_string(item, "source_priority"),
        project_reference=_optional_string(item, "project_reference"),
        issue_type=_optional_string(item, "issue_type"),
        status_category=_optional_string(item, "status_category"),
        assignee_reference=_optional_string(item, "assignee_reference"),
        parent_reference=_optional_string(item, "parent_reference"),
        labels=_string_tuple(item, "labels"),
        dependency_references=_string_tuple(item, "dependency_references"),
        dependency_relationships=_string_tuple(item, "dependency_relationships"),
        dependency_display_urls=_string_tuple(item, "dependency_display_urls"),
        membership_references=_string_tuple(item, "membership_references"),
        dependent_references=_string_tuple(item, "dependent_references"),
        related_source_ids=_string_tuple(item, "related_source_ids"),
        blocked=_boolean(item, "blocked", default=False),
        source_owned_risk=_boolean(item, "source_owned_risk", default=False),
        source_created_at=_optional_datetime(item, "source_created_at", zone),
        source_updated_at=_optional_datetime(item, "source_updated_at", zone),
        hard_deadline=_boolean(item, "hard_deadline", default=False),
        primary_stewardship=_boolean(item, "primary_stewardship", default=False),
        relationship_consequence=_boolean(
            item,
            "relationship_consequence",
            default=False,
        ),
        six_month_goal=_boolean(item, "six_month_goal", default=False),
        seasonal_initiative=_boolean(item, "seasonal_initiative", default=False),
        delegation_opportunity=_boolean(
            item,
            "delegation_opportunity",
            default=False,
        ),
        energy_requirement=_optional_choice(
            item,
            "energy_requirement",
            {"low", "moderate", "high"},
        ),
        opportunity_cost=_optional_string(item, "opportunity_cost"),
        uncertainty=_optional_choice(
            item,
            "uncertainty",
            {"low", "moderate", "high", "unknown"},
        ),
        inference_explanation=_optional_string(item, "inference_explanation"),
        evidence_fingerprint=_optional_string(item, "evidence_fingerprint"),
    )


def _required_string(item: SourceItem, key: str) -> str:
    value = item.facts.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_string(item: SourceItem, key: str) -> str | None:
    value = item.facts.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    stripped = value.strip()
    return stripped or None


def _optional_choice(
    item: SourceItem,
    key: str,
    permitted: set[str],
) -> str | None:
    value = _optional_string(item, key)
    if value is None:
        return None
    normalized = value.casefold()
    if normalized not in permitted:
        allowed = ", ".join(sorted(permitted))
        raise ValueError(f"{key} must be one of: {allowed}")
    return normalized


def _integer(item: SourceItem, key: str, *, default: int) -> int:
    value = item.facts.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _optional_integer(item: SourceItem, key: str) -> int | None:
    value = item.facts.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if key == "provider_priority" and value not in {1, 2, 3, 4}:
        raise ValueError("provider_priority must be between 1 and 4")
    return value


def _optional_positive_integer(item: SourceItem, key: str) -> int | None:
    value = _optional_integer(item, key)
    if value is not None and value <= 0:
        raise ValueError(f"{key} must be greater than zero")
    return value


def _boolean(item: SourceItem, key: str, *, default: bool) -> bool:
    value = item.facts.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _string_tuple(item: SourceItem, key: str) -> tuple[str, ...]:
    value = item.facts.get(key, ())
    if not isinstance(value, tuple) or not all(
        isinstance(element, str) and element.strip() for element in value
    ):
        raise ValueError(f"{key} must contain non-empty strings")
    return tuple(element.strip() for element in value)


def _optional_datetime(
    item: SourceItem,
    key: str,
    zone: ZoneInfo,
) -> datetime | None:
    value = item.facts.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{key} must be an ISO 8601 string") from None
    return _aware(parsed, zone)


def _aware(value: datetime, zone: ZoneInfo) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("source timestamps must be timezone-aware")
    return value.astimezone(zone)


def record_completion_state(record: NormalizedRecord) -> bool | None:
    """Return only an explicit source-supported completion state."""

    status_category = (record.status_category or "").casefold()
    status = (record.status or "").casefold()
    if status_category in {"done", "complete", "completed"}:
        return True
    if status_category in {"new", "open", "to do", "todo", "in progress"}:
        return False
    if status in {"complete", "completed", "closed", "done"}:
        return True
    if status in {"new", "open", "pending", "in progress"}:
        return False
    return None


def record_priority_fact(record: NormalizedRecord) -> str | int | None:
    """Return a source-owned priority value without interpreting importance."""

    if record.source_priority is not None:
        return record.source_priority
    return record.provider_priority


def record_status_fact(record: NormalizedRecord) -> str | None:
    """Return the most structured source-owned status value available."""

    return record.status_category or record.status
