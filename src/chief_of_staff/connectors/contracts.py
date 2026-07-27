"""Provider-neutral, retrieval-only connector contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from chief_of_staff.domain import CoverageStatus

type FactValue = str | int | bool | None


@dataclass(frozen=True, slots=True)
class RetrievalWindow:
    """Explicit bounded time window supplied to a connector."""

    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class ConnectorRequest:
    """Read-only retrieval context shared by all connectors."""

    run_id: str
    briefing_date: date
    timezone: str
    approved_scope: str
    window: RetrievalWindow


@dataclass(frozen=True, slots=True)
class SourceItem:
    """Minimal source fact envelope returned before normalization."""

    id: str
    source_record_id: str
    item_type: str
    facts: dict[str, FactValue]
    retrieved_at: datetime
    display_url: str | None = None
    freshness_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ContextResourceCoverage:
    """Retrieved and persisted counts for one supporting context resource."""

    resource: str
    retrieved_count: int
    persisted_count: int | None = None


@dataclass(frozen=True, slots=True)
class SourceCoverage:
    """What a connector did and did not retrieve."""

    source: str
    approved_scope: str
    status: CoverageStatus
    retrieved_at: datetime
    record_count: int
    freshness_at: datetime | None = None
    warnings: tuple[str, ...] = ()
    error_category: str | None = None
    page_count: int | None = None
    retrieved_count: int | None = None
    selected_count: int | None = None
    persisted_count: int | None = None
    candidate_count: int | None = None
    displayed_count: int | None = None
    context_resources: tuple[ContextResourceCoverage, ...] = ()


@dataclass(frozen=True, slots=True)
class ConnectorResult:
    """Read-only connector output and its explicit coverage report."""

    items: tuple[SourceItem, ...]
    coverage: SourceCoverage


@runtime_checkable
class ReadOnlyConnector(Protocol):
    """The only connector capability available to the deterministic pipeline."""

    @property
    def source_name(self) -> str:
        """Return a stable source identity."""

    @property
    def approved_scope(self) -> str:
        """Return the human-readable approved resource boundary."""

    def retrieve(self, request: ConnectorRequest) -> ConnectorResult:
        """Read source records without exposing any mutation operation."""
