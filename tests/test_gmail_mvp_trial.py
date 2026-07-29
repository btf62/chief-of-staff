"""Local-only persistence and artifact tests for the Gmail MVP trial."""

from __future__ import annotations

import base64
import json
import stat
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from chief_of_staff.connectors import (
    GMAIL_INBOUND_MESSAGE_LIMIT,
    GMAIL_READONLY_SCOPE,
    GMAIL_WORK_ACCOUNT,
    GMAIL_WORK_ALIAS,
    GMAIL_WORK_INSTANCE,
    ConnectorRequest,
    GmailAuthorization,
    GmailConnector,
    GmailFailureCategory,
    GmailFailureStage,
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
    StaticConnector,
    TodoistConnector,
)
from chief_of_staff.domain import (
    ConnectorDomain,
    ConnectorInstanceMetadata,
    CoverageStatus,
    SourceEvidence,
)
from chief_of_staff.gmail_mvp_trial import GmailMvpTrialFailure, GmailMvpTrialRunner
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
        del authorization
        if "in:sent" in request.query and "-in:sent" not in request.query:
            return GmailMessageListPage(())
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


@dataclass(frozen=True, slots=True)
class _BoundaryTransport:
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
            tuple(
                GmailMessageReference(
                    f"private-message-{index}",
                    f"private-thread-{index}",
                )
                for index in range(GMAIL_INBOUND_MESSAGE_LIMIT + 1)
            )
        )

    def get_message_metadata(
        self,
        authorization: GmailAuthorization,
        message_id: str,
    ) -> GmailMessageMetadata:
        raise AssertionError((authorization, message_id))

    def get_message_full(
        self,
        authorization: GmailAuthorization,
        message_id: str,
    ) -> GmailFullMessage:
        raise AssertionError((authorization, message_id))


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
        review_text = review.read_text(encoding="utf-8")
        assert "## Bounded body-candidate coverage" in review_text
        assert "- Eligible: 1" in review_text
        assert "- Selected under the hard cap: 1" in review_text
        assert "- Omitted without body retrieval: 0" in review_text
        assert "- Body fetches attempted: 1" in review_text
        assert "- Usable bodies: 1" in review_text
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


def test_failed_trial_writes_safe_private_attempt_reports_without_persistence(
    tmp_path: Path,
) -> None:
    gmail = GmailConnector(
        account_reference="primary-user",
        authorization_provider=_AuthorizationProvider(),
        transport=_BoundaryTransport(),
        clock=lambda: NOW,
    )
    context_path = tmp_path / "context.md"
    context_path.write_text("# Synthetic context\n", encoding="utf-8")
    briefing_directory = tmp_path / ".local" / "briefings"
    review_directory = tmp_path / ".local" / "gmail" / "reviews"

    with Database.open(tmp_path / "state.sqlite3") as database:
        store = StateStore(database)
        runner = GmailMvpTrialRunner(
            state_store=store,
            repository_root=tmp_path,
            repository_paths=(Path("context.md"),),
            calendar_connector=cast(
                GoogleCalendarConnector,
                StaticConnector(
                    source_name="google_calendar",
                    approved_scope="synthetic calendar read only",
                    items=(),
                    status=CoverageStatus.COMPLETE,
                ),
            ),
            todoist_connector=cast(
                TodoistConnector,
                StaticConnector(
                    source_name="todoist",
                    approved_scope="synthetic todoist read only",
                    items=(),
                    status=CoverageStatus.COMPLETE,
                ),
            ),
            jira_connector=cast(
                JiraConnector,
                StaticConnector(
                    source_name="jira",
                    approved_scope="synthetic jira read only",
                    items=(),
                    status=CoverageStatus.COMPLETE,
                ),
            ),
            gmail_connector=gmail,
            briefing_directory=briefing_directory,
            review_directory=review_directory,
            briefing_date_override=date(2026, 7, 28),
            clock=lambda: NOW,
        )

        with pytest.raises(GmailMvpTrialFailure) as raised:
            runner.run()

        report = raised.value.report
        failure = report.failure
        assert failure.failure_category is (
            GmailFailureCategory.CONFIGURED_BOUNDARY_EXCEEDED
        )
        assert failure.failure_stage is GmailFailureStage.LISTING
        assert failure.configured_boundary_name == "inbound_messages"
        assert failure.configured_limit == GMAIL_INBOUND_MESSAGE_LIMIT
        assert failure.observed_aggregate_count == GMAIL_INBOUND_MESSAGE_LIMIT + 1
        assert failure.pages_completed == 1
        assert failure.message_references_listed == GMAIL_INBOUND_MESSAGE_LIMIT + 1
        assert not failure.metadata_retrieval_began
        assert not failure.body_retrieval_began
        assert not failure.persistence_began
        assert not failure.raw_payloads_retained
        assert report.records_persisted == 0
        assert report.retrieval_attempts == 5
        assert len(report.failure_report_paths) == 5
        assert all(path.exists() for path in report.failure_report_paths)
        assert all(
            stat.S_IMODE(path.stat().st_mode) == 0o600
            for path in report.failure_report_paths
        )
        assert not report.briefing_run_persisted
        assert not report.review_artifact_created
        assert not report.combined_briefing_created
        inspection = store.inspect_state()
        assert inspection.connector_runs == 0
        assert inspection.briefing_runs == 0
        assert inspection.source_evidence == 0
        assert inspection.normalized_gmail_messages == 0

    assert not briefing_directory.exists()
    assert not review_directory.exists()
    assert (tmp_path / ".local" / "gmail").is_dir()
    serialized = json.dumps(asdict(report), default=str)
    assert "private-message" not in serialized
    assert "private-thread" not in serialized
    assert "synthetic read only" not in serialized
    for failure_path in report.failure_report_paths:
        failure_text = failure_path.read_text(encoding="utf-8")
        assert "private-message" not in failure_text
        assert "private-thread" not in failure_text
        assert "synthetic read only" not in failure_text
