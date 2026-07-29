"""Local-only persistence and artifact tests for the Gmail MVP trial."""

from __future__ import annotations

import base64
import stat
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

from chief_of_staff.connectors import (
    GMAIL_READONLY_SCOPE,
    GMAIL_WORK_ACCOUNT,
    GMAIL_WORK_ALIAS,
    GMAIL_WORK_INSTANCE,
    ConnectorRequest,
    GmailAuthorization,
    GmailConnector,
    GmailFullMessage,
    GmailMessageListPage,
    GmailMessageListRequest,
    GmailMessageMetadata,
    GmailMessageReference,
    GmailMimePart,
    GmailProfile,
    GoogleCalendarConnector,
    JiraConnector,
    RetrievalWindow,
    TodoistConnector,
)
from chief_of_staff.domain import (
    ConnectorDomain,
    ConnectorInstanceMetadata,
    SourceEvidence,
)
from chief_of_staff.gmail_mvp_trial import GmailMvpTrialRunner
from chief_of_staff.persistence import Database, StateStore

NOW = datetime(2026, 7, 28, 13, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _AuthorizationProvider:
    def get_gmail_authorization(self, account_reference: str) -> GmailAuthorization:
        return GmailAuthorization(
            account_reference=account_reference,
            granted_scopes=frozenset({GMAIL_READONLY_SCOPE}),
            credential_reference="synthetic",
        )


@dataclass(frozen=True, slots=True)
class _Transport:
    metadata: GmailMessageMetadata

    def get_profile(self, authorization: GmailAuthorization) -> GmailProfile:
        del authorization
        return GmailProfile(GMAIL_WORK_ACCOUNT)

    def list_messages(
        self,
        authorization: GmailAuthorization,
        request: GmailMessageListRequest,
    ) -> GmailMessageListPage:
        del authorization, request
        return GmailMessageListPage(
            (GmailMessageReference(self.metadata.id, self.metadata.thread_id),)
        )

    def get_message_metadata(
        self,
        authorization: GmailAuthorization,
        message_id: str,
    ) -> GmailMessageMetadata:
        del authorization
        assert message_id == self.metadata.id
        return self.metadata

    def get_message_full(
        self,
        authorization: GmailAuthorization,
        message_id: str,
    ) -> GmailFullMessage:
        del authorization
        assert message_id == self.metadata.id
        body = base64.urlsafe_b64encode(
            b"Please confirm the synthetic decision."
        ).decode()
        return GmailFullMessage(
            self.metadata,
            GmailMimePart(mime_type="text/plain", body_data=body),
        )


def test_private_review_and_minimized_facts_are_local_inspectable_and_deletable(
    tmp_path: Path,
) -> None:
    metadata = GmailMessageMetadata(
        id="message-1",
        thread_id="thread-1",
        internal_date=NOW,
        label_ids=("INBOX",),
        size_estimate=100,
        headers=(
            ("From", "person@example.invalid"),
            ("To", GMAIL_WORK_ACCOUNT),
            ("Subject", "Synthetic request"),
        ),
    )
    connector = GmailConnector(
        account_reference="primary-user",
        authorization_provider=_AuthorizationProvider(),
        transport=_Transport(metadata),
        clock=lambda: NOW,
    )
    connector.retrieve(
        ConnectorRequest(
            run_id="synthetic-run",
            briefing_date=date(2026, 7, 28),
            timezone="America/New_York",
            approved_scope=GMAIL_READONLY_SCOPE,
            window=RetrievalWindow(NOW - timedelta(days=14), NOW),
        )
    )

    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        store.save_connector_instance(
            ConnectorInstanceMetadata(
                id=GMAIL_WORK_INSTANCE,
                provider="gmail",
                alias=GMAIL_WORK_ALIAS,
                domain_classification=ConnectorDomain.WORK,
                approved_resource_boundary=GMAIL_WORK_ACCOUNT,
                approved_scopes=GMAIL_READONLY_SCOPE,
                retrieval_configuration="bounded metadata-first",
                enabled=True,
                retention_policy_reference="ADR-0004",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        evidence_id = "evidence-1"
        store.add_source_evidence(
            SourceEvidence(
                id=evidence_id,
                connector_run_id=None,
                connector_instance_id=GMAIL_WORK_INSTANCE,
                source="gmail",
                source_record_id=metadata.id,
                evidence_fingerprint="source-fingerprint",
                retrieved_at=NOW,
            )
        )
        runner = GmailMvpTrialRunner(
            state_store=store,
            repository_root=tmp_path,
            repository_paths=(),
            calendar_connector=cast(GoogleCalendarConnector, object()),
            todoist_connector=cast(TodoistConnector, object()),
            jira_connector=cast(JiraConnector, object()),
            gmail_connector=connector,
            briefing_directory=tmp_path / ".local" / "briefings",
            review_directory=tmp_path / ".local" / "gmail" / "reviews",
            clock=lambda: NOW,
        )

        persisted = runner._persist_gmail(
            evidence_ids={("gmail", GMAIL_WORK_INSTANCE, metadata.id): evidence_id},
            run_id="synthetic-run",
            created_at=NOW,
        )
        review = runner._write_review("synthetic-run")

        assert persisted == 1
        assert stat.S_IMODE(review.stat().st_mode) == 0o600
        assert store.inspect_state().normalized_gmail_messages == 1
        assert store.inspect_state().conclusions == 1
        evidence = database.connection.execute(
            "SELECT excerpt FROM source_evidence WHERE id = ?",
            (evidence_id,),
        ).fetchone()
        assert evidence is not None
        assert evidence["excerpt"] == "Please confirm the synthetic decision."
        database_bytes = (tmp_path / "state.sqlite3").read_bytes()
        assert b"full MIME" not in database_bytes
        assert store.delete_source_evidence(evidence_id)
        assert store.inspect_state().normalized_gmail_messages == 0
        assert store.inspect_state().conclusions == 0


def test_private_trial_paths_are_ignored_by_repository() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    gitignore = (repository_root / ".gitignore").read_text(encoding="utf-8")

    assert ".local/" in gitignore
