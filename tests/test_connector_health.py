"""Retrieval-free connector preflight and recovery-message tests."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from chief_of_staff.auth import MacOSKeychain
from chief_of_staff.auth.keychain import SecurityCommandResult
from chief_of_staff.connector_health import (
    APPROVED_CONNECTORS,
    ConnectorHealth,
    format_health_report,
    inspect_approved_connectors,
    retrieval_failure_report,
)
from chief_of_staff.connectors import GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE
from chief_of_staff.domain import (
    AuthorizationStatus,
    ConnectorAuthorizationMetadata,
    CredentialHealth,
    OAuthClientMetadata,
)
from chief_of_staff.persistence import Database, StateStore

NOW = datetime(2026, 7, 30, 13, 0, tzinfo=UTC)


@dataclass(slots=True)
class _SecurityRunner:
    items: set[tuple[str, str]] = field(default_factory=set)

    def __call__(
        self,
        arguments: tuple[str, ...],
        *,
        input_text: str | None,
        capture_output: bool,
    ) -> SecurityCommandResult:
        del input_text, capture_output
        service = arguments[arguments.index("-s") + 1]
        account = arguments[arguments.index("-a") + 1]
        return SecurityCommandResult(
            returncode=0 if (service, account) in self.items else 44
        )


def _calendar_metadata(
    store: StateStore,
    *,
    expires_at: datetime,
    refresh: bool = False,
) -> ConnectorAuthorizationMetadata:
    store.save_oauth_client(
        OAuthClientMetadata(
            connector="google_calendar",
            oauth_project_id="synthetic-project",
            oauth_client_id="synthetic-client",
            credential_service="test.service",
            client_secret_account="calendar-client-secret",
            configured_at=NOW,
        )
    )
    metadata = ConnectorAuthorizationMetadata(
        connector="google_calendar",
        account_reference="primary-user",
        account_identity="user@example.invalid",
        granted_scope=GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE,
        credential_service="test.service",
        access_token_account="calendar-access",
        refresh_token_account="calendar-refresh" if refresh else None,
        authorization_status=AuthorizationStatus.AUTHORIZED,
        credential_health=(
            CredentialHealth.EXPIRED if expires_at <= NOW else CredentialHealth.HEALTHY
        ),
        refresh_health=CredentialHealth.HEALTHY if refresh else None,
        token_expires_at=expires_at,
        authorized_at=NOW - timedelta(days=1),
        updated_at=NOW,
    )
    store.save_connector_authorization(metadata)
    return metadata


def test_preflight_reports_each_approved_source_independently(
    tmp_path: Path,
) -> None:
    runner = _SecurityRunner()
    keychain = MacOSKeychain(command_runner=runner)
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        reports = inspect_approved_connectors(store, keychain, now=NOW)

    assert tuple(report.connector.display_name for report in reports) == (
        "Google Calendar",
        "Todoist",
        "Jira",
        "Work Gmail",
    )
    assert all(report.health is ConnectorHealth.UNAUTHORIZED for report in reports)
    assert all(not report.can_retrieve for report in reports)


def test_preflight_never_retrieves_with_expired_or_missing_access(
    tmp_path: Path,
) -> None:
    runner = _SecurityRunner()
    keychain = MacOSKeychain(command_runner=runner)
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        _calendar_metadata(store, expires_at=NOW - timedelta(minutes=1))
        report = inspect_approved_connectors(store, keychain, now=NOW)[0]

    assert report.health is ConnectorHealth.EXPIRED
    assert not report.can_retrieve
    assert format_health_report(report)[-1] == (
        "Run: python -m chief_of_staff.live_cli authorize "
        "--account-identity <approved-work-account> --refreshable"
    )


def test_preflight_distinguishes_healthy_and_refreshable_credentials(
    tmp_path: Path,
) -> None:
    runner = _SecurityRunner()
    keychain = MacOSKeychain(command_runner=runner)
    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        metadata = _calendar_metadata(
            store,
            expires_at=NOW + timedelta(minutes=10),
        )
        runner.items.add((metadata.credential_service, metadata.access_token_account))
        healthy = inspect_approved_connectors(store, keychain, now=NOW)[0]

        refreshable_metadata = replace(
            metadata,
            credential_health=CredentialHealth.EXPIRED,
            token_expires_at=NOW - timedelta(minutes=1),
            refresh_token_account="calendar-refresh",
            refresh_health=CredentialHealth.HEALTHY,
        )
        store.save_connector_authorization(refreshable_metadata)
        runner.items.add(("test.service", "calendar-refresh"))
        refreshable = inspect_approved_connectors(store, keychain, now=NOW)[0]

    assert healthy.health is ConnectorHealth.HEALTHY
    assert healthy.can_retrieve
    assert refreshable.health is ConnectorHealth.REFRESHABLE
    assert refreshable.can_retrieve


def test_retrieval_diagnostics_distinguish_provider_boundary_and_failure() -> None:
    connector = APPROVED_CONNECTORS[2]

    provider = retrieval_failure_report(
        connector,
        error_category="ProviderTimeout",
    )
    boundary = retrieval_failure_report(
        connector,
        error_category="ProjectBoundaryMismatch",
    )
    failure = retrieval_failure_report(
        connector,
        error_category="UnexpectedResponse",
    )

    assert provider.health is ConnectorHealth.PROVIDER_UNAVAILABLE
    assert boundary.health is ConnectorHealth.BOUNDARY_EXCEEDED
    assert format_health_report(boundary)[-1] == (
        "Run: python -m chief_of_staff.jira_live_cli authorize"
    )
    assert failure.health is ConnectorHealth.RETRIEVAL_FAILURE
