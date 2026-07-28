"""Regression coverage for the connector removed by ADR-0007."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import chief_of_staff.connectors as connectors
from chief_of_staff.auth.keychain import (
    KeychainSecretReference,
    MacOSKeychain,
    SecurityCommandResult,
)
from chief_of_staff.domain import (
    AuthorizationStatus,
    ConnectorAuthorizationMetadata,
    ConnectorDomain,
    ConnectorInstanceMetadata,
    CredentialHealth,
    OAuthClientMetadata,
)
from chief_of_staff.persistence import Database, StateStore

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RETIRED_PROVIDER = "".join(("asa", "na"))
NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


class _RecordingKeychainRunner:
    def __init__(self) -> None:
        self.items: set[tuple[str, str]] = set()
        self.deleted: list[tuple[str, str]] = []

    def __call__(
        self,
        arguments: tuple[str, ...],
        *,
        input_text: str | None,
        capture_output: bool,
    ) -> SecurityCommandResult:
        del input_text, capture_output
        account = arguments[arguments.index("-a") + 1]
        service = arguments[arguments.index("-s") + 1]
        identity = (service, account)
        if arguments[0] == "delete-generic-password":
            existed = identity in self.items
            self.items.discard(identity)
            self.deleted.append(identity)
            return SecurityCommandResult(returncode=0 if existed else 44)
        raise AssertionError("unexpected Keychain operation")


def test_retired_provider_is_absent_from_active_scope_and_runtime() -> None:
    active_documents = (
        "README.md",
        "AGENTS.md",
        "docs/README.md",
        "docs/product/requirements.md",
        "docs/product/features/daily-briefing-v1.md",
        "docs/architecture/overview.md",
        "docs/architecture/connectors/README.md",
        "docs/operations/first-safe-connectors.md",
        "docs/roadmap.md",
    )
    for relative_path in active_documents:
        text = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        assert RETIRED_PROVIDER not in text.casefold()

    source_root = REPOSITORY_ROOT / "src" / "chief_of_staff"
    for source_path in source_root.rglob("*.py"):
        assert (
            RETIRED_PROVIDER not in source_path.read_text(encoding="utf-8").casefold()
        )

    exported_names = {name.casefold() for name in vars(connectors)}
    assert not any(RETIRED_PROVIDER in name for name in exported_names)
    for module_suffix in (
        RETIRED_PROVIDER,
        f"auth.{RETIRED_PROVIDER}_oauth",
        f"connectors.{RETIRED_PROVIDER}",
        f"connectors.{RETIRED_PROVIDER}_discovery",
        f"connectors.{RETIRED_PROVIDER}_project_boundary",
    ):
        assert importlib.util.find_spec(f"chief_of_staff.{module_suffix}") is None


def test_phase_one_sources_and_gmail_instances_remain_explicit() -> None:
    requirements = (REPOSITORY_ROOT / "docs" / "product" / "requirements.md").read_text(
        encoding="utf-8"
    )
    for expected_source in (
        "Google Calendar",
        "Work Gmail",
        "Personal Gmail",
        "Todoist",
        "Jira",
        "Approved Google Drive content",
        "Approved repository context",
    ):
        assert expected_source in requirements

    gmail_specification = (
        REPOSITORY_ROOT / "docs" / "architecture" / "connectors" / "gmail.md"
    ).read_text(encoding="utf-8")
    assert "`Work Gmail`" in gmail_specification
    assert "`Personal Gmail`" in gmail_specification
    assert "independent" in gmail_specification.casefold()


def test_retired_instance_metadata_and_exact_keychain_references_are_removed(
    tmp_path: Path,
) -> None:
    instance_id = f"{RETIRED_PROVIDER}:primary"
    service = "org.chief-of-staff.oauth"
    client_account = f"{instance_id}:client-secret"
    access_account = f"{instance_id}:access-token:primary-user"
    refresh_account = f"{instance_id}:refresh-token:primary-user"
    runner = _RecordingKeychainRunner()
    runner.items.update(
        {
            (service, client_account),
            (service, access_account),
            (service, refresh_account),
        }
    )
    keychain = MacOSKeychain(command_runner=runner)

    with Database.open(tmp_path / "retired-instance.sqlite3") as database:
        store = StateStore(database)
        store.save_connector_instance(
            ConnectorInstanceMetadata(
                id=instance_id,
                provider=RETIRED_PROVIDER,
                alias="Retired Provider",
                domain_classification=ConnectorDomain.WORK,
                approved_resource_boundary="historical synthetic boundary",
                approved_scopes="historical:read",
                retrieval_configuration="disabled",
                enabled=False,
                retention_policy_reference="adr-0004",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        client = OAuthClientMetadata(
            connector=RETIRED_PROVIDER,
            connector_instance_id=instance_id,
            oauth_project_id="historical-project",
            oauth_client_id="historical-client",
            credential_service=service,
            client_secret_account=client_account,
            configured_at=NOW,
        )
        authorization = ConnectorAuthorizationMetadata(
            connector=RETIRED_PROVIDER,
            connector_instance_id=instance_id,
            account_reference="primary-user",
            account_identity="synthetic@example.invalid",
            granted_scope="historical:read",
            credential_service=service,
            access_token_account=access_account,
            refresh_token_account=refresh_account,
            authorization_status=AuthorizationStatus.AUTHORIZED,
            credential_health=CredentialHealth.HEALTHY,
            refresh_health=CredentialHealth.HEALTHY,
            token_expires_at=NOW + timedelta(hours=1),
            authorized_at=NOW,
            updated_at=NOW,
        )
        store.save_oauth_client(client)
        store.save_connector_authorization(authorization)

        references = (
            KeychainSecretReference(service, client.client_secret_account),
            KeychainSecretReference(service, authorization.access_token_account),
            KeychainSecretReference(
                service,
                authorization.refresh_token_account or "",
            ),
        )
        assert all(keychain.delete(reference) for reference in references)
        assert store.delete_connector_instance(instance_id)

        assert store.get_connector_instance(instance_id) is None
        assert store.get_oauth_client(instance_id) is None
        assert store.get_connector_authorization(instance_id) is None
        assert runner.deleted == [
            (service, client_account),
            (service, access_account),
            (service, refresh_account),
        ]
