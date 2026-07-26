"""Read-only source connector boundaries."""

from chief_of_staff.connectors.contracts import (
    ConnectorRequest,
    ConnectorResult,
    ReadOnlyConnector,
    RetrievalWindow,
    SourceCoverage,
    SourceItem,
)
from chief_of_staff.connectors.static import StaticConnector

__all__ = (
    "ConnectorRequest",
    "ConnectorResult",
    "ReadOnlyConnector",
    "RetrievalWindow",
    "SourceCoverage",
    "SourceItem",
    "StaticConnector",
)
