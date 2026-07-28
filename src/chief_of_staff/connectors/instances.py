"""Application-owned connector instances layered over provider connectors."""

from __future__ import annotations

from dataclasses import dataclass, replace

from chief_of_staff.connectors.contracts import (
    ConnectorRequest,
    ConnectorResult,
    ReadOnlyConnector,
    SourceItem,
)
from chief_of_staff.domain import ConnectorDomain

GOOGLE_CALENDAR_PRIMARY_INSTANCE = "google_calendar:primary"
TODOIST_PRIMARY_INSTANCE = "todoist:primary"
JIRA_PRIMARY_INSTANCE = "jira:primary"
ASANA_PRIMARY_INSTANCE = "asana:primary"


@dataclass(frozen=True, slots=True)
class ConnectorInstanceIdentity:
    """Stable instance identity safe for provenance and presentation."""

    id: str
    provider: str
    alias: str
    domain_classification: ConnectorDomain

    def __post_init__(self) -> None:
        for field_name, value in (
            ("connector instance ID", self.id),
            ("provider", self.provider),
            ("account alias", self.alias),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        if "@" in self.alias:
            raise ValueError("account alias must not be a full email address")


@dataclass(frozen=True, slots=True)
class ConnectorInstance:
    """Bind one independently configured account to a provider implementation."""

    identity: ConnectorInstanceIdentity
    connector: ReadOnlyConnector

    def __post_init__(self) -> None:
        if self.identity.provider != self.connector.source_name:
            raise ValueError("connector instance provider does not match connector")

    @property
    def source_name(self) -> str:
        """Return the provider identity used by source-specific policy."""

        return self.connector.source_name

    @property
    def approved_scope(self) -> str:
        """Return this instance's approved provider resource boundary."""

        return self.connector.approved_scope

    def retrieve(self, request: ConnectorRequest) -> ConnectorResult:
        """Retrieve through one account and attach its identity to every fact."""

        result = self.connector.retrieve(request)
        return ConnectorResult(
            items=tuple(
                replace(
                    item,
                    connector_instance_id=self.identity.id,
                    account_alias=self.identity.alias,
                    domain_classification=self.identity.domain_classification,
                )
                for item in result.items
            ),
            coverage=replace(
                result.coverage,
                connector_instance_id=self.identity.id,
                account_alias=self.identity.alias,
                domain_classification=self.identity.domain_classification,
            ),
        )


def connector_instance_key(
    *,
    source: str,
    connector_instance_id: str | None,
) -> tuple[str, str]:
    """Return an identity key that never combines separate source accounts."""

    return (source, connector_instance_id or source)


def partition_source_items_by_domain(
    items: tuple[SourceItem, ...],
) -> dict[ConnectorDomain, tuple[SourceItem, ...]]:
    """Create domain-isolated evidence groups for later inference packets."""

    grouped: dict[ConnectorDomain, list[SourceItem]] = {}
    for item in items:
        if item.domain_classification is None:
            raise ValueError("source item has no connector-domain classification")
        grouped.setdefault(item.domain_classification, []).append(item)
    return {domain: tuple(values) for domain, values in grouped.items()}
