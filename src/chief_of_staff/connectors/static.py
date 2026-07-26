"""In-memory connector for synthetic and contract-test scenarios."""

from __future__ import annotations

from dataclasses import dataclass

from chief_of_staff.connectors.contracts import (
    ConnectorRequest,
    ConnectorResult,
    SourceCoverage,
    SourceItem,
)
from chief_of_staff.domain import CoverageStatus


@dataclass(frozen=True, slots=True)
class StaticConnector:
    """Return predefined source facts without I/O or external capability."""

    source_name: str
    approved_scope: str
    items: tuple[SourceItem, ...]
    status: CoverageStatus
    warnings: tuple[str, ...] = ()
    error_category: str | None = None

    def retrieve(self, request: ConnectorRequest) -> ConnectorResult:
        """Return synthetic records and coverage for the requested boundary."""

        if request.approved_scope != self.approved_scope:
            raise ValueError("request scope does not match connector scope")
        retrieved_at = max(
            (item.retrieved_at for item in self.items),
            default=request.window.starts_at,
        )
        freshness_values = tuple(
            item.freshness_at for item in self.items if item.freshness_at is not None
        )
        freshness_at = max(freshness_values) if freshness_values else None
        return ConnectorResult(
            items=self.items,
            coverage=SourceCoverage(
                source=self.source_name,
                approved_scope=self.approved_scope,
                status=self.status,
                retrieved_at=retrieved_at,
                freshness_at=freshness_at,
                record_count=len(self.items),
                warnings=self.warnings,
                error_category=self.error_category,
            ),
        )
