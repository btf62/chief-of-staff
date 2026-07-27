"""Convert source envelopes into typed application records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from chief_of_staff.connectors import SourceItem


class RecordKind(StrEnum):
    """Normalized source-record categories used by the reduced pipeline."""

    CALENDAR_EVENT = "calendar_event"
    TASK = "task"
    CONTEXT = "context"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Authoritative source reference carried through composition."""

    source: str
    source_record_id: str
    display_url: str | None
    retrieved_at: datetime
    freshness_at: datetime | None


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
        id=f"{source}:{item.id}",
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


def _boolean(item: SourceItem, key: str, *, default: bool) -> bool:
    value = item.facts.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


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
