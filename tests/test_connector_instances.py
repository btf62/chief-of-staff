"""Multi-account connector-instance, migration, and isolation tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from chief_of_staff.connectors import (
    ConnectorInstance,
    ConnectorInstanceIdentity,
    ConnectorRequest,
    SourceItem,
    StaticConnector,
    partition_source_items_by_domain,
)
from chief_of_staff.domain import (
    AuthorizationStatus,
    ConnectorAuthorizationMetadata,
    ConnectorDomain,
    ConnectorInstanceMetadata,
    CoverageStatus,
    CredentialHealth,
    NormalizedSourceTask,
    OAuthClientMetadata,
    SourceEvidence,
)
from chief_of_staff.persistence import (
    Database,
    Migration,
    StateStore,
    apply_migrations,
    load_migrations,
)
from chief_of_staff.pipeline import DeterministicBriefingPipeline, resolve_context

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
SCOPE = "synthetic messages in one approved account"


def _instance(
    instance_id: str,
    alias: str,
    domain: ConnectorDomain,
) -> ConnectorInstanceMetadata:
    return ConnectorInstanceMetadata(
        id=instance_id,
        provider="gmail",
        alias=alias,
        domain_classification=domain,
        approved_resource_boundary=SCOPE,
        approved_scopes="gmail.readonly",
        retrieval_configuration=f"{domain.value}-configuration",
        enabled=True,
        retention_policy_reference=f"{domain.value}-retention",
        created_at=NOW,
        updated_at=NOW,
    )


def _oauth(instance_id: str) -> OAuthClientMetadata:
    return OAuthClientMetadata(
        connector="gmail",
        connector_instance_id=instance_id,
        oauth_project_id=f"{instance_id}-project",
        oauth_client_id=f"{instance_id}-client",
        credential_service="org.chief-of-staff.oauth",
        client_secret_account=f"{instance_id}:client-secret",
        configured_at=NOW,
        application_owner="synthetic owner",
    )


def _authorization(instance_id: str) -> ConnectorAuthorizationMetadata:
    return ConnectorAuthorizationMetadata(
        connector="gmail",
        connector_instance_id=instance_id,
        account_reference=f"{instance_id}:account",
        account_identity=f"{instance_id}@example.invalid",
        granted_scope="gmail.readonly",
        credential_service="org.chief-of-staff.oauth",
        access_token_account=f"{instance_id}:access-token",
        refresh_token_account=f"{instance_id}:refresh-token",
        authorization_status=AuthorizationStatus.AUTHORIZED,
        credential_health=CredentialHealth.HEALTHY,
        refresh_health=CredentialHealth.HEALTHY,
        token_expires_at=NOW + timedelta(hours=1),
        authorized_at=NOW,
        updated_at=NOW,
    )


def _source_item(item_id: str) -> SourceItem:
    return SourceItem(
        id=item_id,
        source_record_id="same-provider-record-id",
        item_type="context",
        facts={"title": f"Synthetic {item_id}"},
        retrieved_at=NOW,
        display_url=f"https://example.invalid/{item_id}",
    )


def _bound_connector(
    instance_id: str,
    alias: str,
    domain: ConnectorDomain,
    *items: SourceItem,
    status: CoverageStatus = CoverageStatus.COMPLETE,
) -> ConnectorInstance:
    return ConnectorInstance(
        identity=ConnectorInstanceIdentity(
            id=instance_id,
            provider="gmail",
            alias=alias,
            domain_classification=domain,
        ),
        connector=StaticConnector(
            source_name="gmail",
            approved_scope=SCOPE,
            items=items,
            status=status,
        ),
    )


def test_two_provider_instances_keep_credentials_and_health_independent(
    tmp_path: Path,
) -> None:
    with Database.open(tmp_path / "instances.sqlite3") as database:
        store = StateStore(database)
        for instance_id, alias, domain in (
            ("gmail:work", "Work Gmail", ConnectorDomain.WORK),
            ("gmail:personal", "Personal Gmail", ConnectorDomain.PERSONAL),
        ):
            store.save_connector_instance(_instance(instance_id, alias, domain))
            store.save_oauth_client(_oauth(instance_id))
            store.save_connector_authorization(_authorization(instance_id))

        work = store.get_connector_authorization("gmail:work")
        personal = store.get_connector_authorization("gmail:personal")
        assert work is not None and personal is not None
        assert work.access_token_account != personal.access_token_account
        assert work.refresh_token_account != personal.refresh_token_account
        work_instance = store.get_connector_instance("gmail:work")
        personal_instance = store.get_connector_instance("gmail:personal")
        assert work_instance is not None and personal_instance is not None
        assert (
            work_instance.retrieval_configuration
            != personal_instance.retrieval_configuration
        )
        assert (
            work_instance.retention_policy_reference
            != personal_instance.retention_policy_reference
        )

        store.set_connector_authorization_health(
            "gmail:work",
            status=AuthorizationStatus.ERROR,
            health=CredentialHealth.ERROR,
            updated_at=NOW + timedelta(minutes=1),
        )
        assert store.get_connector_authorization("gmail:personal") == personal
        assert store.delete_connector_authorization("gmail:work")
        assert store.get_connector_authorization("gmail:work") is None
        assert store.get_connector_authorization("gmail:personal") == personal
        with pytest.raises(ValueError, match="multiple connector instances"):
            store.get_connector_authorization("gmail")


def test_task_snapshot_reconciliation_is_restricted_to_one_instance(
    tmp_path: Path,
) -> None:
    with Database.open(tmp_path / "snapshot-isolation.sqlite3") as database:
        store = StateStore(database)
        for instance_id, alias, domain in (
            ("gmail:work", "Work Gmail", ConnectorDomain.WORK),
            ("gmail:personal", "Personal Gmail", ConnectorDomain.PERSONAL),
        ):
            store.save_connector_instance(_instance(instance_id, alias, domain))
            evidence_id = f"{instance_id}:evidence"
            store.add_source_evidence(
                SourceEvidence(
                    id=evidence_id,
                    connector_run_id=None,
                    connector_instance_id=instance_id,
                    source="gmail",
                    source_record_id="same-source-record",
                    evidence_fingerprint=f"{instance_id}:fingerprint",
                    retrieved_at=NOW,
                )
            )
            store.add_normalized_source_task(
                NormalizedSourceTask(
                    evidence_id=evidence_id,
                    title=f"Synthetic task from {alias}",
                    provider_priority=1,
                    recurring=False,
                    all_day=True,
                )
            )

        reconciliation = store.reconcile_source_task_snapshot(
            source="gmail",
            connector_instance_id="gmail:work",
            current_evidence_ids={},
        )

        assert reconciliation.removed_count == 1
        remaining = database.connection.execute(
            """
            SELECT connector_instance_id
            FROM source_evidence
            ORDER BY connector_instance_id
            """
        ).fetchall()
        assert [str(row["connector_instance_id"]) for row in remaining] == [
            "gmail:personal"
        ]


def test_connector_instances_keep_coverage_provenance_and_domains_separate() -> None:
    work = _bound_connector(
        "gmail:work",
        "Work Gmail",
        ConnectorDomain.WORK,
        _source_item("work-message"),
    )
    personal = _bound_connector(
        "gmail:personal",
        "Personal Gmail",
        ConnectorDomain.PERSONAL,
        _source_item("personal-message"),
    )
    context = resolve_context(
        run_id="two-account-coverage",
        briefing_date=date(2026, 7, 27),
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (work, personal))

    assert len(result.deduplication.records) == 2
    assert {
        record.provenance.connector_instance_id
        for record in result.deduplication.records
    } == {"gmail:work", "gmail:personal"}
    assert {
        record.provenance.domain_classification
        for record in result.deduplication.records
    } == {ConnectorDomain.WORK, ConnectorDomain.PERSONAL}
    coverage = result.plan.sections[-1].summary or ""
    assert "`Work Gmail`: complete" in coverage
    assert "`Personal Gmail`: complete" in coverage
    assert "@example.invalid" not in result.rendered.text
    assert "gmail:work" not in result.rendered.text
    assert "gmail:personal" not in result.rendered.text


def test_auth_failure_is_distinct_from_an_empty_second_account() -> None:
    unauthorized = _bound_connector(
        "gmail:work",
        "Work Gmail",
        ConnectorDomain.WORK,
        status=CoverageStatus.UNAUTHORIZED,
    )
    empty = _bound_connector(
        "gmail:personal",
        "Personal Gmail",
        ConnectorDomain.PERSONAL,
        status=CoverageStatus.COMPLETE,
    )
    context = resolve_context(
        run_id="two-account-auth-status",
        briefing_date=date(2026, 7, 27),
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (unauthorized, empty))
    coverage = result.plan.sections[-1].summary or ""

    assert "`Work Gmail`: unauthorized" in coverage
    assert "`Personal Gmail`: complete" in coverage


def test_domain_partitioning_never_mixes_evidence_by_default() -> None:
    request = ConnectorRequest(
        run_id="domain-packet",
        briefing_date=date(2026, 7, 27),
        timezone="America/New_York",
        approved_scope=SCOPE,
        window=resolve_context(
            run_id="domain-packet",
            briefing_date=date(2026, 7, 27),
            timezone="America/New_York",
        ).retrieval_window,
    )
    work = _bound_connector(
        "gmail:work",
        "Work Gmail",
        ConnectorDomain.WORK,
        _source_item("work"),
    ).retrieve(request)
    personal = _bound_connector(
        "gmail:personal",
        "Personal Gmail",
        ConnectorDomain.PERSONAL,
        _source_item("personal"),
    ).retrieve(request)

    packets = partition_source_items_by_domain((*work.items, *personal.items))

    assert set(packets) == {ConnectorDomain.WORK, ConnectorDomain.PERSONAL}
    assert {item.connector_instance_id for item in packets[ConnectorDomain.WORK]} == {
        "gmail:work"
    }
    assert {
        item.connector_instance_id for item in packets[ConnectorDomain.PERSONAL]
    } == {"gmail:personal"}


def test_legacy_authorization_and_runs_migrate_without_data_loss(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrations = load_migrations()
    apply_migrations(connection, migrations[:6])
    connection.execute(
        """
        INSERT INTO oauth_clients(
            connector, oauth_project_id, oauth_client_id, credential_service,
            client_secret_account, configured_at, application_owner,
            oauth_grant_type
        )
        VALUES ('todoist', 'project', 'client', 'service', 'secret-ref', ?,
                'owner', NULL)
        """,
        (NOW.isoformat(),),
    )
    connection.execute(
        """
        INSERT INTO connector_authorizations(
            connector, account_reference, account_identity, granted_scope,
            credential_service, access_token_account, refresh_token_account,
            authorization_status, credential_health, refresh_health,
            token_expires_at, authorized_at, last_used_at, updated_at
        )
        VALUES ('todoist', 'account-ref', 'identity', 'data:read', 'service',
                'access-ref', 'refresh-ref', 'authorized', 'healthy',
                'healthy', ?, ?, ?, ?)
        """,
        (
            (NOW + timedelta(hours=1)).isoformat(),
            NOW.isoformat(),
            NOW.isoformat(),
            NOW.isoformat(),
        ),
    )
    connection.execute(
        """
        INSERT INTO connector_runs(
            id, source, approved_scope, started_at, completed_at, status,
            coverage_status, freshness_at, page_count
        )
        VALUES ('run-1', 'todoist', 'approved tasks', ?, ?, 'succeeded',
                'complete', ?, 1)
        """,
        (NOW.isoformat(), NOW.isoformat(), NOW.isoformat()),
    )
    connection.execute(
        """
        INSERT INTO source_evidence(
            id, connector_run_id, source, source_record_id,
            evidence_fingerprint, retrieved_at
        )
        VALUES ('evidence-1', 'run-1', 'todoist', 'task-1',
                'fingerprint', ?)
        """,
        (NOW.isoformat(),),
    )

    apply_migrations(connection, migrations)

    assert (
        connection.execute(
            "SELECT connector_instance_id FROM connector_runs WHERE id = 'run-1'"
        ).fetchone()[0]
        == "todoist:primary"
    )
    assert (
        connection.execute(
            """
        SELECT connector_instance_id
        FROM source_evidence
        WHERE id = 'evidence-1'
        """
        ).fetchone()[0]
        == "todoist:primary"
    )
    assert connection.execute("SELECT count(*) FROM oauth_clients").fetchone()[0] == 1
    assert (
        connection.execute("SELECT count(*) FROM connector_authorizations").fetchone()[
            0
        ]
        == 1
    )
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_failed_instance_migration_rolls_back_and_can_recover(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rollback.sqlite3"
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrations = load_migrations()
    apply_migrations(connection, migrations[:6])
    broken = Migration.create(
        7,
        "connector_instances",
        "CREATE TABLE incomplete(id TEXT PRIMARY KEY);\nINVALID SQL;\n",
    )

    with pytest.raises(sqlite3.DatabaseError):
        apply_migrations(connection, (*migrations[:6], broken))

    assert (
        connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
        == 6
    )
    assert (
        connection.execute(
            """
        SELECT count(*)
        FROM sqlite_master
        WHERE type = 'table' AND name = 'incomplete'
        """
        ).fetchone()[0]
        == 0
    )

    apply_migrations(connection, migrations)
    assert (
        connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
        == 12
    )
    connection.close()
