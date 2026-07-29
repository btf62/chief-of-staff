"""Deterministic briefing integration tests for high-confidence Gmail facts."""

from __future__ import annotations

from datetime import UTC, date, datetime

from chief_of_staff.connectors import (
    GMAIL_READONLY_SCOPE,
    GMAIL_WORK_ALIAS,
    GMAIL_WORK_INSTANCE,
    ConnectorInstance,
    ConnectorInstanceIdentity,
    ConnectorRequest,
    ConnectorResult,
    GmailAuthenticationError,
    SourceItem,
    StaticConnector,
)
from chief_of_staff.domain import ConnectorDomain, CoverageStatus
from chief_of_staff.pipeline import (
    BriefingSectionName,
    DeterministicBriefingPipeline,
    resolve_context,
)

NOW = datetime(2026, 7, 28, 13, 0, tzinfo=UTC)


def _gmail_connector(*items: SourceItem) -> ConnectorInstance:
    return ConnectorInstance(
        identity=ConnectorInstanceIdentity(
            id=GMAIL_WORK_INSTANCE,
            provider="gmail",
            alias=GMAIL_WORK_ALIAS,
            domain_classification=ConnectorDomain.WORK,
        ),
        connector=StaticConnector(
            source_name="gmail",
            approved_scope=GMAIL_READONLY_SCOPE,
            items=items,
            status=CoverageStatus.COMPLETE,
        ),
    )


def _item(
    item_id: str,
    item_type: str,
    title: str,
    *,
    due_at: str | None = None,
) -> SourceItem:
    return SourceItem(
        id=item_id,
        source_record_id=item_id,
        item_type=item_type,
        facts={
            "title": title,
            "summary": "Explicit bounded email evidence supports this conclusion.",
            "importance": 4,
            "explicit_commitment": item_type == "commitment",
            "status": "explicit",
            "all_day": due_at is not None,
            "due_at": due_at,
        },
        retrieved_at=NOW,
        freshness_at=NOW,
        display_url=f"https://mail.google.com/mail/u/0/#all/{item_id}",
    )


def test_high_confidence_email_conclusions_use_canonical_sections_and_provenance() -> (
    None
):
    context = resolve_context(
        run_id="gmail-briefing",
        briefing_date=date(2026, 7, 28),
        timezone="America/New_York",
    )
    connector = _gmail_connector(
        _item("waiting", "waiting_item", "Respond to an explicit request"),
        _item(
            "commitment",
            "commitment",
            "Honor an explicit commitment",
            due_at="2026-07-28T00:00:00-04:00",
        ),
    )

    result = DeterministicBriefingPipeline().run(context, (connector,))

    sections = {section.name: section for section in result.plan.sections}
    assert len(sections[BriefingSectionName.PEOPLE_WAITING].items) == 1
    assert len(sections[BriefingSectionName.COMMITMENTS_AT_RISK].items) == 1
    for section_name in (
        BriefingSectionName.PEOPLE_WAITING,
        BriefingSectionName.COMMITMENTS_AT_RISK,
    ):
        source = sections[section_name].items[0].sources[0]
        assert source.display_url is not None
        assert source.connector_instance_id == GMAIL_WORK_INSTANCE
        assert source.account_alias == GMAIL_WORK_ALIAS
    assert result.rendered.word_count <= 1000
    assert "`Work Gmail`: complete" in result.rendered.text


def test_email_sections_are_omitted_when_no_high_confidence_items_exist() -> None:
    context = resolve_context(
        run_id="empty-gmail-briefing",
        briefing_date=date(2026, 7, 28),
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(context, (_gmail_connector(),))

    names = {section.name for section in result.plan.sections}
    assert BriefingSectionName.PEOPLE_WAITING not in names
    assert BriefingSectionName.COMMITMENTS_AT_RISK not in names
    assert "`Work Gmail`: complete" in result.rendered.text


class _UnauthorizedGmail:
    source_name = "gmail"
    approved_scope = GMAIL_READONLY_SCOPE

    def retrieve(self, request: ConnectorRequest) -> ConnectorResult:
        del request
        raise GmailAuthenticationError("synthetic authorization failure")


def test_authorization_failure_is_distinct_from_an_empty_work_mailbox() -> None:
    context = resolve_context(
        run_id="gmail-auth-status",
        briefing_date=date(2026, 7, 28),
        timezone="America/New_York",
    )
    unauthorized = ConnectorInstance(
        identity=ConnectorInstanceIdentity(
            id=GMAIL_WORK_INSTANCE,
            provider="gmail",
            alias=GMAIL_WORK_ALIAS,
            domain_classification=ConnectorDomain.WORK,
        ),
        connector=_UnauthorizedGmail(),
    )

    failed = DeterministicBriefingPipeline().run(context, (unauthorized,))
    empty = DeterministicBriefingPipeline().run(context, (_gmail_connector(),))

    assert "`Work Gmail`: unauthorized" in failed.rendered.text
    assert "`Work Gmail`: complete" in empty.rendered.text
