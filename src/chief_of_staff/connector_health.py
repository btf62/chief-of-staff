"""Safe, retrieval-free health inspection for approved connector instances."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from chief_of_staff.auth import KeychainSecretReference, MacOSKeychain
from chief_of_staff.auth.jira_oauth import JIRA_DURABLE_GRANTED_SCOPE
from chief_of_staff.connectors import (
    GMAIL_READONLY_SCOPE,
    GMAIL_WORK_INSTANCE,
    GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE,
    GOOGLE_CALENDAR_PRIMARY_INSTANCE,
    JIRA_PRIMARY_INSTANCE,
    TODOIST_DATA_READ_SCOPE,
    TODOIST_PRIMARY_INSTANCE,
)
from chief_of_staff.domain import (
    AuthorizationStatus,
    ConnectorAuthorizationMetadata,
    CredentialHealth,
)
from chief_of_staff.persistence import StateStore


class ConnectorHealth(StrEnum):
    """Operational state exposed without credentials or private records."""

    HEALTHY = "healthy"
    REFRESHABLE = "refreshable"
    EXPIRED = "expired"
    MISSING = "missing"
    UNAUTHORIZED = "unauthorized"
    PROVIDER_UNAVAILABLE = "provider unavailable"
    BOUNDARY_EXCEEDED = "boundary exceeded"
    RETRIEVAL_FAILURE = "retrieval failure"


@dataclass(frozen=True, slots=True)
class ApprovedConnector:
    """One accepted connector boundary and its safe recovery command."""

    instance_id: str
    display_name: str
    expected_scope: str
    recovery_command: str
    resource_required: bool = False


@dataclass(frozen=True, slots=True)
class ConnectorHealthReport:
    """Privacy-safe preflight result for one approved logical source."""

    connector: ApprovedConnector
    health: ConnectorHealth
    can_retrieve: bool
    detail: str


APPROVED_CONNECTORS: Final = (
    ApprovedConnector(
        GOOGLE_CALENDAR_PRIMARY_INSTANCE,
        "Google Calendar",
        GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE,
        (
            "python -m chief_of_staff.live_cli authorize "
            "--account-identity <approved-work-account> --refreshable"
        ),
    ),
    ApprovedConnector(
        TODOIST_PRIMARY_INSTANCE,
        "Todoist",
        TODOIST_DATA_READ_SCOPE,
        "python -m chief_of_staff.todoist_live_cli authorize",
    ),
    ApprovedConnector(
        JIRA_PRIMARY_INSTANCE,
        "Jira",
        JIRA_DURABLE_GRANTED_SCOPE,
        "python -m chief_of_staff.jira_live_cli authorize",
        resource_required=True,
    ),
    ApprovedConnector(
        GMAIL_WORK_INSTANCE,
        "Work Gmail",
        GMAIL_READONLY_SCOPE,
        "python -m chief_of_staff.gmail_live_cli authorize",
    ),
)


def inspect_approved_connectors(
    state_store: StateStore,
    keychain: MacOSKeychain,
    *,
    now: datetime | None = None,
) -> tuple[ConnectorHealthReport, ...]:
    """Inspect all approved connectors without retrieving provider data."""

    checked_at = now or datetime.now(UTC)
    if checked_at.tzinfo is None:
        raise ValueError("connector health time must be timezone-aware")
    return tuple(
        _inspect_connector(
            connector,
            state_store=state_store,
            keychain=keychain,
            now=checked_at,
        )
        for connector in APPROVED_CONNECTORS
    )


def retrieval_failure_report(
    connector: ApprovedConnector,
    *,
    error_category: str | None,
) -> ConnectorHealthReport:
    """Classify a post-preflight retrieval problem without provider details."""

    normalized = (error_category or "").casefold()
    if any(
        marker in normalized
        for marker in ("scope", "boundary", "project", "calendarid", "resource")
    ):
        health = ConnectorHealth.BOUNDARY_EXCEEDED
        detail = (
            f"{connector.display_name} stopped because the approved source "
            "boundary was not satisfied."
        )
    elif any(
        marker in normalized
        for marker in ("timeout", "rate", "provider", "network", "transport")
    ):
        health = ConnectorHealth.PROVIDER_UNAVAILABLE
        detail = f"{connector.display_name} provider is temporarily unavailable."
    else:
        health = ConnectorHealth.RETRIEVAL_FAILURE
        detail = f"{connector.display_name} retrieval did not complete."
    return ConnectorHealthReport(
        connector=connector,
        health=health,
        can_retrieve=False,
        detail=detail,
    )


def format_health_report(report: ConnectorHealthReport) -> tuple[str, ...]:
    """Return concise, safe console lines for one health result."""

    lines = (
        f"{report.connector.display_name}: {report.health.value}",
        report.detail,
    )
    if report.health in {
        ConnectorHealth.EXPIRED,
        ConnectorHealth.MISSING,
        ConnectorHealth.UNAUTHORIZED,
        ConnectorHealth.BOUNDARY_EXCEEDED,
    }:
        return (*lines, f"Run: {report.connector.recovery_command}")
    return lines


def _inspect_connector(
    connector: ApprovedConnector,
    *,
    state_store: StateStore,
    keychain: MacOSKeychain,
    now: datetime,
) -> ConnectorHealthReport:
    client = state_store.get_oauth_client(connector.instance_id)
    authorization = state_store.get_connector_authorization(connector.instance_id)
    if client is None or authorization is None:
        return ConnectorHealthReport(
            connector,
            ConnectorHealth.UNAUTHORIZED,
            False,
            f"{connector.display_name} has not been authorized.",
        )
    if authorization.granted_scope != connector.expected_scope or (
        connector.resource_required
        and state_store.get_connector_resource(connector.instance_id) is None
    ):
        return ConnectorHealthReport(
            connector,
            ConnectorHealth.BOUNDARY_EXCEEDED,
            False,
            (
                f"{connector.display_name} authorization does not match the "
                "approved source boundary."
            ),
        )
    if authorization.authorization_status is not AuthorizationStatus.AUTHORIZED:
        return ConnectorHealthReport(
            connector,
            ConnectorHealth.UNAUTHORIZED,
            False,
            f"{connector.display_name} authorization is not active.",
        )

    access_reference = KeychainSecretReference(
        authorization.credential_service,
        authorization.access_token_account,
    )
    access_present = keychain.exists(access_reference)
    expired = (
        authorization.token_expires_at <= now
        or authorization.credential_health is CredentialHealth.EXPIRED
    )
    if access_present and not expired:
        return ConnectorHealthReport(
            connector,
            ConnectorHealth.HEALTHY,
            True,
            f"{connector.display_name} is ready.",
        )
    if _healthy_refresh_credential(authorization, keychain):
        return ConnectorHealthReport(
            connector,
            ConnectorHealth.REFRESHABLE,
            True,
            (
                f"{connector.display_name} access has expired, but its approved "
                "refresh credential is available."
            ),
        )
    if expired:
        return ConnectorHealthReport(
            connector,
            ConnectorHealth.EXPIRED,
            False,
            f"{connector.display_name} authorization has expired.",
        )
    return ConnectorHealthReport(
        connector,
        ConnectorHealth.MISSING,
        False,
        f"{connector.display_name} credential is missing from macOS Keychain.",
    )


def _healthy_refresh_credential(
    authorization: ConnectorAuthorizationMetadata,
    keychain: MacOSKeychain,
) -> bool:
    account = authorization.refresh_token_account
    return bool(
        account is not None
        and authorization.refresh_health is CredentialHealth.HEALTHY
        and keychain.exists(
            KeychainSecretReference(
                authorization.credential_service,
                account,
            )
        )
    )
