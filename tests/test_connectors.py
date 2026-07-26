"""Contract and integration tests for the first safe connectors."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import pytest

from chief_of_staff.connectors import (
    GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE,
    CalendarAuthorization,
    CalendarAuthorizationUnavailable,
    CalendarRetrievalError,
    ConnectorRequest,
    GoogleCalendarConnector,
    GoogleCalendarEvent,
    GoogleCalendarListRequest,
    GoogleCalendarPage,
    RepositoryContextConnector,
)
from chief_of_staff.connectors.repository import MAX_FILE_BYTES
from chief_of_staff.domain import CoverageStatus
from chief_of_staff.pipeline import (
    BriefingSectionName,
    DeterministicBriefingPipeline,
    resolve_context,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
BRIEFING_DATE = date(2026, 7, 27)
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "google_calendar_pages.json"


def _request(scope: str) -> ConnectorRequest:
    context = resolve_context(
        run_id="connector-test",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )
    return ConnectorRequest(
        run_id=context.run_id,
        briefing_date=context.briefing_date,
        timezone=context.timezone,
        approved_scope=scope,
        window=context.retrieval_window,
    )


def _fixture_pages() -> tuple[GoogleCalendarPage, ...]:
    root = cast(
        dict[str, object],
        json.loads(FIXTURE_PATH.read_text(encoding="utf-8")),
    )
    raw_pages = cast(list[dict[str, object]], root["pages"])
    pages: list[GoogleCalendarPage] = []
    for raw_page in raw_pages:
        raw_events = cast(list[dict[str, object]], raw_page["events"])
        events = tuple(
            GoogleCalendarEvent(
                id=cast(str, raw_event["id"]),
                title=cast(str, raw_event["title"]),
                start=cast(str, raw_event["start"]),
                end=cast(str, raw_event["end"]),
                updated_at=datetime.fromisoformat(cast(str, raw_event["updated_at"])),
                html_link=cast(str | None, raw_event["html_link"]),
                status=cast(str, raw_event["status"]),
                location=cast(str | None, raw_event["location"]),
                all_day=cast(bool, raw_event["all_day"]),
            )
            for raw_event in raw_events
        )
        pages.append(
            GoogleCalendarPage(
                events=events,
                next_page_token=cast(
                    str | None,
                    raw_page["next_page_token"],
                ),
            )
        )
    return tuple(pages)


@dataclass(frozen=True, slots=True)
class _MockAuthorizationProvider:
    scopes: frozenset[str] = frozenset({GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE})

    def get_calendar_authorization(
        self,
        account_reference: str,
    ) -> CalendarAuthorization:
        return CalendarAuthorization(
            account_reference=account_reference,
            granted_scopes=self.scopes,
            credential_reference="mock-calendar-grant",
        )


@dataclass(frozen=True, slots=True)
class _UnavailableAuthorizationProvider:
    def get_calendar_authorization(
        self,
        account_reference: str,
    ) -> CalendarAuthorization:
        del account_reference
        raise CalendarAuthorizationUnavailable


@dataclass(slots=True)
class _PagedTransport:
    pages: tuple[GoogleCalendarPage, ...]
    fail_on_call: int | None = field(default=None, kw_only=True)
    calls: list[GoogleCalendarListRequest] = field(default_factory=list, init=False)

    def list_events(
        self,
        authorization: CalendarAuthorization,
        request: GoogleCalendarListRequest,
    ) -> GoogleCalendarPage:
        assert authorization.credential_reference == "mock-calendar-grant"
        self.calls.append(request)
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise CalendarRetrievalError
        index = 0 if request.page_token is None else 1
        return self.pages[index]


def _calendar_connector(
    transport: _PagedTransport,
    *,
    authorization_provider: (
        _MockAuthorizationProvider | _UnavailableAuthorizationProvider | None
    ) = None,
) -> GoogleCalendarConnector:
    return GoogleCalendarConnector(
        account_reference="primary-user",
        authorization_provider=(
            _MockAuthorizationProvider()
            if authorization_provider is None
            else authorization_provider
        ),
        transport=transport,
        clock=lambda: NOW,
    )


def test_repository_connector_reads_only_exact_approved_markdown(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "approved.md"
    unapproved = tmp_path / "unapproved.md"
    approved.write_text(
        "# Approved Context\n\nThis is safe synthetic context.\n",
        encoding="utf-8",
    )
    unapproved.write_text(
        "# Unapproved Context\n\nThis must not be retrieved.\n",
        encoding="utf-8",
    )
    before = approved.read_bytes()
    connector = RepositoryContextConnector(
        root=tmp_path,
        approved_paths=(Path("approved.md"),),
        clock=lambda: NOW,
    )

    result = connector.retrieve(_request(connector.approved_scope))

    assert result.coverage.status is CoverageStatus.COMPLETE
    assert result.coverage.record_count == 1
    assert result.items[0].source_record_id == "approved.md"
    assert result.items[0].facts["title"] == "Approved Context"
    assert result.items[0].facts["summary"] == "This is safe synthetic context."
    assert "Unapproved" not in str(result.items)
    assert approved.read_bytes() == before


def test_repository_connector_reads_repository_owned_context() -> None:
    connector = RepositoryContextConnector(
        root=REPOSITORY_ROOT,
        approved_paths=(
            Path("docs/product/requirements.md"),
            Path("docs/roadmap.md"),
        ),
        clock=lambda: NOW,
    )

    result = connector.retrieve(_request(connector.approved_scope))

    assert result.coverage.status is CoverageStatus.COMPLETE
    assert {item.source_record_id for item in result.items} == {
        "docs/product/requirements.md",
        "docs/roadmap.md",
    }
    assert all(
        item.display_url is not None and item.display_url.startswith("repository://")
        for item in result.items
    )


@pytest.mark.parametrize(
    "configured_path",
    [
        Path(".private.md"),
        Path("notes.txt"),
        Path("."),
    ],
)
def test_repository_connector_rejects_unsafe_or_broad_paths(
    tmp_path: Path,
    configured_path: Path,
) -> None:
    (tmp_path / ".private.md").write_text("private", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not markdown", encoding="utf-8")

    with pytest.raises(ValueError):
        RepositoryContextConnector(
            root=tmp_path,
            approved_paths=(configured_path,),
        )


def test_repository_connector_rejects_paths_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside", encoding="utf-8")

    with pytest.raises(ValueError, match="inside the root"):
        RepositoryContextConnector(
            root=root,
            approved_paths=(outside,),
        )


def test_repository_connector_rejects_symlink_escape_duplicate_and_oversize(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    approved = root / "approved.md"
    approved.write_text("# Approved", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside", encoding="utf-8")
    link = root / "link.md"
    link.symlink_to(outside)

    with pytest.raises(ValueError, match="inside the root"):
        RepositoryContextConnector(
            root=root,
            approved_paths=(link,),
        )
    with pytest.raises(ValueError, match="unique"):
        RepositoryContextConnector(
            root=root,
            approved_paths=(approved, approved),
        )

    oversized = root / "oversized.md"
    oversized.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(ValueError, match="may not exceed"):
        RepositoryContextConnector(
            root=root,
            approved_paths=(oversized,),
        )


def test_repository_connector_discloses_file_failure_after_approval(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "approved.md"
    approved.write_text("# Approved", encoding="utf-8")
    connector = RepositoryContextConnector(
        root=tmp_path,
        approved_paths=(approved,),
        clock=lambda: NOW,
    )
    approved.unlink()

    result = connector.retrieve(_request(connector.approved_scope))

    assert result.coverage.status is CoverageStatus.UNAVAILABLE
    assert result.coverage.error_category == "RepositoryFileUnavailable"
    assert result.coverage.record_count == 0


def test_repository_connector_retains_readable_files_during_partial_failure(
    tmp_path: Path,
) -> None:
    available = tmp_path / "available.md"
    unavailable = tmp_path / "unavailable.md"
    available.write_text("# Available", encoding="utf-8")
    unavailable.write_text("# Unavailable", encoding="utf-8")
    connector = RepositoryContextConnector(
        root=tmp_path,
        approved_paths=(available, unavailable),
        clock=lambda: NOW,
    )
    unavailable.unlink()

    result = connector.retrieve(_request(connector.approved_scope))

    assert result.coverage.status is CoverageStatus.PARTIAL
    assert result.coverage.record_count == 1
    assert result.items[0].source_record_id == "available.md"


def test_repository_connector_rejects_target_changed_after_approval(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    approved = root / "approved.md"
    approved.write_text("# Approved", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside", encoding="utf-8")
    connector = RepositoryContextConnector(
        root=root,
        approved_paths=(approved,),
        clock=lambda: NOW,
    )
    approved.unlink()
    approved.symlink_to(outside)

    result = connector.retrieve(_request(connector.approved_scope))

    assert result.coverage.status is CoverageStatus.UNAVAILABLE
    assert result.items == ()


def test_google_calendar_paginates_and_normalizes_synthetic_fixtures() -> None:
    pages = _fixture_pages()
    transport = _PagedTransport(pages)
    connector = _calendar_connector(transport)

    result = connector.retrieve(_request(connector.approved_scope))

    assert result.coverage.status is CoverageStatus.COMPLETE
    assert result.coverage.record_count == 3
    assert [call.page_token for call in transport.calls] == [
        None,
        "synthetic-page-2",
    ]
    assert all(call.single_events for call in transport.calls)
    assert all(not call.show_deleted for call in transport.calls)
    assert all(call.order_by == "startTime" for call in transport.calls)
    all_day = next(item for item in result.items if item.id == "synthetic-event-2")
    assert all_day.facts["start_at"] == "2026-07-27T00:00:00-04:00"
    assert all_day.facts["all_day"] is True
    assert result.coverage.freshness_at == datetime(
        2026,
        7,
        26,
        18,
        0,
        tzinfo=UTC,
    )


def test_google_calendar_preserves_first_page_during_partial_failure() -> None:
    pages = _fixture_pages()
    transport = _PagedTransport(
        pages,
        fail_on_call=2,
    )
    connector = _calendar_connector(transport)

    result = connector.retrieve(_request(connector.approved_scope))

    assert result.coverage.status is CoverageStatus.PARTIAL
    assert result.coverage.record_count == 2
    assert result.coverage.error_category == "CalendarRetrievalError"
    assert "stopped before page 2" in result.coverage.warnings[0]


def test_google_calendar_first_page_failure_is_unavailable() -> None:
    transport = _PagedTransport(
        _fixture_pages(),
        fail_on_call=1,
    )
    connector = _calendar_connector(transport)

    result = connector.retrieve(_request(connector.approved_scope))

    assert result.coverage.status is CoverageStatus.UNAVAILABLE
    assert result.coverage.record_count == 0
    assert result.coverage.error_category == "CalendarRetrievalError"


def test_google_calendar_distinguishes_unauthorized_from_empty() -> None:
    pages = (GoogleCalendarPage(events=()),)
    unauthorized_transport = _PagedTransport(pages)
    unauthorized = _calendar_connector(
        unauthorized_transport,
        authorization_provider=_UnavailableAuthorizationProvider(),
    )
    empty_transport = _PagedTransport(pages)
    empty = _calendar_connector(empty_transport)

    unauthorized_result = unauthorized.retrieve(_request(unauthorized.approved_scope))
    empty_result = empty.retrieve(_request(empty.approved_scope))

    assert unauthorized_result.coverage.status is CoverageStatus.UNAUTHORIZED
    assert unauthorized_result.coverage.error_category == (
        "CalendarAuthorizationUnavailable"
    )
    assert unauthorized_transport.calls == []
    assert empty_result.coverage.status is CoverageStatus.COMPLETE
    assert empty_result.coverage.record_count == 0


def test_google_calendar_rejects_any_scope_expansion() -> None:
    transport = _PagedTransport((GoogleCalendarPage(events=()),))
    authorization = _MockAuthorizationProvider(
        scopes=frozenset(
            {
                GOOGLE_CALENDAR_EVENTS_OWNED_READONLY_SCOPE,
                "https://www.googleapis.com/auth/calendar.events",
            }
        )
    )
    connector = _calendar_connector(
        transport,
        authorization_provider=authorization,
    )

    result = connector.retrieve(_request(connector.approved_scope))

    assert result.coverage.status is CoverageStatus.UNAUTHORIZED
    assert result.coverage.error_category == "CalendarAuthorizationScopeMismatch"
    assert transport.calls == []


def test_google_calendar_discloses_invalid_events_and_pagination_loops() -> None:
    invalid_event = GoogleCalendarEvent(
        id="invalid-event",
        title="",
        start="2026-07-27T09:00:00-04:00",
        end="2026-07-27T10:00:00-04:00",
        updated_at=NOW,
    )
    invalid_transport = _PagedTransport((GoogleCalendarPage(events=(invalid_event,)),))
    invalid_connector = _calendar_connector(invalid_transport)

    invalid_result = invalid_connector.retrieve(
        _request(invalid_connector.approved_scope)
    )

    assert invalid_result.coverage.status is CoverageStatus.PARTIAL
    assert invalid_result.coverage.record_count == 0
    assert invalid_result.coverage.error_category == ("CalendarEventValidationError")

    repeated_marker = "repeated-page"
    loop_transport = _PagedTransport(
        (
            GoogleCalendarPage(events=(), next_page_token=repeated_marker),
            GoogleCalendarPage(events=(), next_page_token=repeated_marker),
        )
    )
    loop_connector = _calendar_connector(loop_transport)

    loop_result = loop_connector.retrieve(_request(loop_connector.approved_scope))

    assert loop_result.coverage.status is CoverageStatus.PARTIAL
    assert loop_result.coverage.error_category == "CalendarPaginationLoop"


def test_connector_contracts_expose_no_mutation_operations(tmp_path: Path) -> None:
    repository_file = tmp_path / "context.md"
    repository_file.write_text("# Context", encoding="utf-8")
    repository = RepositoryContextConnector(
        root=tmp_path,
        approved_paths=(repository_file,),
    )
    calendar = _calendar_connector(_PagedTransport((GoogleCalendarPage(events=()),)))

    for connector in (repository, calendar, calendar.transport):
        for operation in (
            "create",
            "update",
            "delete",
            "insert",
            "patch",
            "send",
            "write",
        ):
            assert not hasattr(connector, operation)


def test_connector_briefing_reports_repository_and_partial_calendar() -> None:
    repository = RepositoryContextConnector(
        root=REPOSITORY_ROOT,
        approved_paths=(Path("docs/product/features/daily-briefing-v1.md"),),
        clock=lambda: NOW,
    )
    pages = _fixture_pages()
    calendar = _calendar_connector(_PagedTransport(pages, fail_on_call=2))
    context = resolve_context(
        run_id="connector-integration",
        briefing_date=BRIEFING_DATE,
        timezone="America/New_York",
    )

    result = DeterministicBriefingPipeline().run(
        context,
        (repository, calendar),
    )

    assert "Feature: Daily Briefing v1" in result.rendered.text
    assert "repository://docs/product/features/daily-briefing-v1.md" in (
        result.rendered.text
    )
    assert "Planning Session" in result.rendered.text
    assert "**Focus Day** — All day" in result.rendered.text
    assert "google_calendar partial" in result.rendered.text
    assert result.rendered.word_count <= 800
    names = tuple(section.name for section in result.plan.sections)
    assert names == (
        BriefingSectionName.CHIEF_OF_STAFF_NOTE,
        BriefingSectionName.TODAYS_CALENDAR,
    )
