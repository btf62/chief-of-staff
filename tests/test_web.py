"""Synthetic security, presentation, and correction-loop tests."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from flask import Flask

from chief_of_staff.domain import (
    BriefingPresentation,
    BriefingPresentationItem,
    BriefingPresentationSection,
    BriefingPresentationSource,
    BriefingRun,
    BriefingStatus,
    Classification,
    Conclusion,
    ConclusionKind,
    ConnectorRun,
    ConnectorStatus,
    CoverageStatus,
    DispositionKind,
    SourceEvidence,
)
from chief_of_staff.persistence import (
    Database,
    StateStore,
)
from chief_of_staff.web.app import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    _content_role,
    _generation_mode_display,
    close_application,
    create_app,
)
from chief_of_staff.web.server import main as web_main

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
BASE_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
ORIGIN_HEADERS = {"Origin": BASE_URL}
MALICIOUS_TEXT = '<script>alert("synthetic")</script><img src=x onerror=alert(1)>'


class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: dict[str, dict[str, str]] = {}
        self._current_action: str | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "form":
            self._current_action = values.get("action")
            if self._current_action is not None:
                self.forms[self._current_action] = {}
        elif tag == "input" and self._current_action is not None:
            name = values.get("name")
            if name:
                self.forms[self._current_action][name] = values.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._current_action = None


def _seed_database(
    path: Path,
    *,
    coverage_status: CoverageStatus = CoverageStatus.COMPLETE,
    include_briefing: bool = True,
    malicious: bool = False,
    long_content: bool = False,
) -> None:
    with Database.open(path) as database:
        store = StateStore(database)
        connector_runs = (
            ConnectorRun(
                id="calendar-run",
                source="google_calendar",
                approved_scope="synthetic primary calendar",
                started_at=NOW - timedelta(minutes=2),
                completed_at=NOW - timedelta(minutes=1),
                status=(
                    ConnectorStatus.FAILED
                    if coverage_status is CoverageStatus.UNAVAILABLE
                    else ConnectorStatus.SUCCEEDED
                ),
                coverage_status=coverage_status,
                freshness_at=NOW - timedelta(minutes=3),
                error_category=(
                    "synthetic_unavailable"
                    if coverage_status is CoverageStatus.UNAVAILABLE
                    else None
                ),
            ),
            ConnectorRun(
                id="gmail-run",
                source="gmail_work",
                approved_scope="synthetic minimized conclusions",
                started_at=NOW - timedelta(minutes=2),
                completed_at=NOW - timedelta(minutes=1),
                status=ConnectorStatus.SUCCEEDED,
                coverage_status=CoverageStatus.PARTIAL,
                freshness_at=NOW - timedelta(minutes=4),
                error_category="bounded_candidate_cap",
            ),
        )
        for connector_run in connector_runs:
            store.add_connector_run(connector_run)

        run = BriefingRun(
            id="briefing-run",
            briefing_date=date(2026, 7, 30),
            timezone="America/New_York",
            invocation_mode="synthetic_review",
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=1),
            status=BriefingStatus.SUCCEEDED,
        )
        store.add_briefing_run(run)
        for connector_run in connector_runs:
            store.link_connector_run(run.id, connector_run.id)

        waiting_statement = (
            MALICIOUS_TEXT if malicious else "Reply to a pending request."
        )
        waiting_excerpt = (
            MALICIOUS_TEXT
            if malicious
            else "A direct request remains unanswered in the bounded window."
        )
        evidence = (
            SourceEvidence(
                id="waiting-evidence",
                connector_run_id="gmail-run",
                source="gmail_work",
                source_record_id="synthetic-message",
                display_url="https://mail.google.com/mail/u/0/#inbox/synthetic",
                excerpt=waiting_excerpt,
                evidence_fingerprint="waiting-fingerprint-v1",
                retrieved_at=NOW,
                freshness_at=NOW,
            ),
            SourceEvidence(
                id="commitment-evidence",
                connector_run_id="calendar-run",
                source="google_calendar",
                source_record_id="synthetic-event",
                display_url="https://calendar.google.com/calendar/event?eid=synthetic",
                excerpt="A confirmed preparation block begins at 9:00 a.m.",
                evidence_fingerprint="commitment-fingerprint-v1",
                retrieved_at=NOW,
                freshness_at=NOW,
            ),
            SourceEvidence(
                id="conflict-evidence",
                connector_run_id="gmail-run",
                source="gmail_work",
                source_record_id="synthetic-conflict",
                display_url="javascript:alert('not allowed')",
                excerpt="One source gives a later deadline.",
                evidence_fingerprint="conflict-fingerprint-v1",
                retrieved_at=NOW,
                freshness_at=NOW,
            ),
        )
        for item in evidence:
            store.add_source_evidence(item)

        conclusions = (
            Conclusion(
                id="waiting-conclusion",
                kind=ConclusionKind.WAITING_ITEM,
                classification=Classification.INFERRED,
                statement=waiting_statement,
                explanation="The minimized evidence supports a likely pending reply.",
                confidence=0.82,
                evidence_fingerprint="waiting-fingerprint-v1",
                processing_version="synthetic-inference-v1",
                created_at=NOW,
                evidence_ids=("waiting-evidence",),
            ),
            Conclusion(
                id="commitment-conclusion",
                kind=ConclusionKind.COMMITMENT,
                classification=Classification.EXPLICIT,
                statement="Prepare for the confirmed morning commitment.",
                explanation="The calendar record explicitly fixes the start time.",
                confidence=1.0,
                evidence_fingerprint="commitment-fingerprint-v1",
                processing_version="synthetic-rules-v1",
                created_at=NOW,
                evidence_ids=("commitment-evidence",),
            ),
            Conclusion(
                id="conflict-conclusion",
                kind=ConclusionKind.RECOMMENDATION,
                classification=Classification.INFERRED,
                statement="Verify the conflicting deadline before acting.",
                explanation="Two source statements conflict; neither was reconciled.",
                confidence=0.7,
                evidence_fingerprint="conflict-fingerprint-v1",
                processing_version="synthetic-conflict-v1",
                created_at=NOW,
                evidence_ids=("commitment-evidence", "conflict-evidence"),
            ),
        )
        for conclusion in conclusions:
            store.add_conclusion(conclusion)

        if not include_briefing:
            return
        detail = (
            "A bounded but deliberately long synthetic detail. " * 45
            if long_content
            else "Keep the response concise and evidence-based."
        )
        presentation = BriefingPresentation(
            briefing_run_id=run.id,
            generation_mode="deterministic_reduced",
            chief_of_staff_note=(
                "Protect the morning preparation window and handle only the "
                "supported commitments shown below."
            ),
            created_at=NOW + timedelta(seconds=1),
            sections=(
                BriefingPresentationSection(
                    name="Today's Outcomes",
                    items=(
                        BriefingPresentationItem(
                            id="commitment-item",
                            conclusion_id="commitment-conclusion",
                            headline="Prepare for the confirmed morning commitment.",
                            detail=detail,
                            content_kind="explicit_detection",
                            explanation="Calendar-bound today.",
                            sources=(
                                BriefingPresentationSource(
                                    source="google_calendar",
                                    display_url=(
                                        "https://calendar.google.com/calendar/"
                                        "event?eid=synthetic"
                                    ),
                                    freshness_at=NOW,
                                ),
                            ),
                        ),
                    ),
                ),
                BriefingPresentationSection(
                    name="People Waiting on Brad",
                    items=(
                        BriefingPresentationItem(
                            id="waiting-item",
                            conclusion_id="waiting-conclusion",
                            headline=waiting_statement,
                            detail="A direct request appears unanswered.",
                            content_kind="inferred_conclusion",
                            uncertainty="Moderate uncertainty",
                            explanation="A direct request has no observed reply.",
                            sources=(
                                BriefingPresentationSource(
                                    source="gmail_work",
                                    display_url=(
                                        "https://mail.google.com/mail/u/0/"
                                        "#inbox/synthetic"
                                    ),
                                    freshness_at=NOW,
                                ),
                            ),
                        ),
                    ),
                ),
                BriefingPresentationSection(
                    name="Commitments at Risk",
                    summary="Conflicting source claims remain attributed.",
                    items=(
                        BriefingPresentationItem(
                            id="conflict-item",
                            conclusion_id="conflict-conclusion",
                            headline="Verify the conflicting deadline before acting.",
                            detail=(
                                "The sources disagree, so no deadline was chosen "
                                "automatically."
                            ),
                            content_kind="recommendation",
                            uncertainty="Verify the source deadline before acting.",
                            explanation=(
                                "Google Calendar and Work Gmail show different "
                                "deadlines."
                            ),
                            sources=(
                                BriefingPresentationSource(
                                    source="google_calendar",
                                    display_url="https://calendar.google.com/",
                                    freshness_at=NOW,
                                ),
                                BriefingPresentationSource(
                                    source="gmail_work",
                                    display_url="javascript:alert('not allowed')",
                                    freshness_at=NOW,
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
        store.save_briefing_presentation(presentation)


@pytest.fixture
def web_app(tmp_path: Path) -> Any:
    database_path = tmp_path / "state.sqlite3"
    _seed_database(database_path)
    app = create_app(
        database_path,
        port=DEFAULT_PORT,
        session_secret=b"s" * 32,
        testing=True,
    )
    try:
        yield app
    finally:
        close_application(app)


def _get(client: Any, path: str) -> Any:
    return client.get(path, base_url=BASE_URL)


def _post(client: Any, path: str, data: dict[str, str]) -> Any:
    return client.post(
        path,
        base_url=BASE_URL,
        headers=ORIGIN_HEADERS,
        data=data,
    )


def _first_conclusion_path(client: Any) -> str:
    response = _get(client, "/")
    match = re.search(rb'href="(/conclusions/[^"]+)"', response.data)
    assert match is not None
    return match.group(1).decode()


def _form(client: Any, detail_path: str, action: str) -> tuple[str, dict[str, str]]:
    response = _get(client, detail_path)
    parser = _FormParser()
    parser.feed(response.get_data(as_text=True))
    suffix = f"/actions/{action}"
    matching = [
        (path, values) for path, values in parser.forms.items() if path.endswith(suffix)
    ]
    assert len(matching) == 1
    return matching[0]


def test_application_accepts_only_exact_ipv4_loopback_host(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    with pytest.raises(ValueError, match=r"127\.0\.0\.1"):
        create_app(path, host="0.0.0.0", testing=True)  # noqa: S104


def test_supported_server_uses_waitress_loopback_and_debug_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    _seed_database(database_path, include_briefing=False)
    captured: dict[str, object] = {}

    class FakeServer:
        def run(self) -> None:
            captured["ran"] = True

        def close(self) -> None:
            captured["closed"] = True

    def fake_create_server(app: Flask, **kwargs: object) -> FakeServer:
        captured["host"] = kwargs["host"]
        captured["port"] = kwargs["port"]
        captured["threads"] = kwargs["threads"]
        captured["debug"] = app.debug
        captured["tracebacks"] = kwargs["expose_tracebacks"]
        return FakeServer()

    monkeypatch.setattr(
        "chief_of_staff.web.server.create_server",
        fake_create_server,
    )
    result = web_main(["--database", str(database_path)])

    assert result == 0
    assert captured == {
        "host": "127.0.0.1",
        "port": 8765,
        "threads": 1,
        "debug": False,
        "tracebacks": False,
        "ran": True,
        "closed": True,
    }


def test_single_waitress_worker_can_use_the_validated_database(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state.sqlite3"
    _seed_database(database_path)
    app = create_app(
        database_path,
        session_secret=b"s" * 32,
        testing=True,
    )
    try:

        def request_from_worker() -> int:
            return int(_get(app.test_client(), "/").status_code)

        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(request_from_worker).result() == 200
    finally:
        close_application(app)


@pytest.mark.parametrize(
    ("base_url", "headers", "expected_status"),
    [
        ("http://localhost:8765", {}, 400),
        (BASE_URL, {"Origin": "http://evil.invalid"}, 403),
        (BASE_URL, {"Forwarded": "host=evil.invalid"}, 400),
        (BASE_URL, {"X-Forwarded-Host": "evil.invalid"}, 400),
    ],
)
def test_unexpected_host_origin_and_forwarded_headers_are_rejected(
    web_app: Flask,
    base_url: str,
    headers: dict[str, str],
    expected_status: int,
) -> None:
    response = web_app.test_client().get("/", base_url=base_url, headers=headers)
    assert response.status_code == expected_status


def test_security_headers_cookie_settings_and_no_external_assets(
    web_app: Flask,
) -> None:
    client = web_app.test_client()
    response = _get(client, "/")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert "script-src 'none'" in response.headers["Content-Security-Policy"]
    assert b"https://fonts." not in response.data
    assert b"<script" not in response.data

    detail = _get(client, _first_conclusion_path(client))
    cookie = detail.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert "Secure" not in cookie
    assert b"localStorage" not in detail.data
    assert b"sessionStorage" not in detail.data
    assert b"serviceWorker" not in detail.data


def test_interface_language_actions_and_diagnostics_are_user_facing(
    web_app: Flask,
) -> None:
    client = web_app.test_client()
    home = _get(client, "/").get_data(as_text=True)
    assert "Deterministic briefing · reduced source coverage" in home
    assert "Directly supported" in home
    assert "Inferred" in home
    assert "Suggested action" in home
    assert "Not reviewed" in home
    assert "Review why this appeared or update it" in home
    assert "A direct request appears unanswered." in home
    assert "The sources disagree, so no deadline was chosen automatically." in home
    assert "Verify the source deadline before acting." in home
    assert "Google Calendar and Work Gmail show different deadlines." in home
    assert "No local disposition" not in home
    assert "high-precision inferred" not in home
    assert "silently reconcile" not in home
    assert "source-attributed" not in home

    detail = _get(client, _first_conclusion_path(client)).get_data(as_text=True)
    assert "Update this item" in detail
    assert (
        "These choices change only how Chief of Staff treats this item. Gmail,"
        in detail
    )
    assert "Common choices" in detail
    assert "Plan or hand off" in detail
    assert "Delete local data" in detail
    assert detail.index("Common choices") < detail.index("Plan or hand off")
    assert detail.index("Plan or hand off") < detail.index("Delete local data")
    for button_text in (
        "Confirm this",
        "Save correction",
        "Dismiss this",
        "Record delegation",
        "Save new date",
        "Mark complete",
        "Intentionally abandon",
        "Delete local item",
    ):
        assert button_text in detail
    assert "What should this say?" in detail
    assert "Who will handle it?" in detail
    assert "New date and time" in detail
    assert "disposition" not in detail.lower()
    assert '<details class="technical-details">' in detail
    assert '<details class="technical-details" open>' not in detail
    assert "Technical details" in detail
    evidence_item = re.search(
        r'<article class="evidence-item">(.*?)</article>',
        detail,
        flags=re.DOTALL,
    )
    assert evidence_item is not None
    assert "Evidence version" not in evidence_item.group(1)

    action_path, form = _form(client, _first_conclusion_path(client), "correct")
    form["replacement_text"] = "Prepare the agenda for the morning commitment."
    response = _post(client, action_path, form)
    assert response.status_code == 303
    updated = _get(client, response.headers["Location"]).get_data(as_text=True)
    assert "Chief of Staff updated this item." in updated
    corrected_home = _get(client, "/").get_data(as_text=True)
    assert "Prepare the agenda for the morning commitment." in corrected_home
    assert "Originally recorded as:" in corrected_home


@pytest.mark.parametrize(
    ("content_kind", "expected"),
    [
        ("authoritative_source_fact", "Source record"),
        ("explicit_detection", "Directly supported"),
        ("inferred_conclusion", "Inferred"),
        ("recommendation", "Suggested action"),
        ("presentation_only_synthesis", "Schedule context"),
    ],
)
def test_content_roles_use_plain_language(
    content_kind: str,
    expected: str,
) -> None:
    item = BriefingPresentationItem(
        id="plain-language-role",
        headline="Synthetic item",
        detail="",
        content_kind=content_kind,
        sources=(),
    )
    assert _content_role(item) == expected


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("deterministic", "Deterministic briefing"),
        (
            "deterministic_reduced",
            "Deterministic briefing · reduced source coverage",
        ),
        ("degraded", "Deterministic briefing · reduced source coverage"),
    ],
)
def test_generation_modes_read_naturally(mode: str, expected: str) -> None:
    assert _generation_mode_display(mode) == expected


def test_request_size_limit_rejects_oversized_form(web_app: Flask) -> None:
    client = web_app.test_client()
    detail_path = _first_conclusion_path(client)
    action_path, form = _form(client, detail_path, "correct")
    form["replacement_text"] = "x" * (33 * 1024)
    response = _post(client, action_path, form)
    assert response.status_code == 413


def test_unexpected_form_fields_are_rejected(web_app: Flask) -> None:
    client = web_app.test_client()
    detail_path = _first_conclusion_path(client)
    action_path, form = _form(client, detail_path, "confirm")
    form["provider_payload"] = "must not be accepted"
    response = _post(client, action_path, form)
    assert response.status_code == 400


def test_source_and_user_text_are_escaped(tmp_path: Path) -> None:
    path = tmp_path / "malicious.sqlite3"
    _seed_database(path, malicious=True)
    app = create_app(path, session_secret=b"s" * 32, testing=True)
    try:
        client = app.test_client()
        response = _get(client, "/")
        assert MALICIOUS_TEXT.encode() not in response.data
        assert b"&lt;script&gt;" in response.data
        assert b"javascript:alert" not in response.data

        detail_path = _first_conclusion_path(client)
        action_path, form = _form(client, detail_path, "correct")
        form["replacement_text"] = MALICIOUS_TEXT
        result = _post(client, action_path, form)
        assert result.status_code == 303
        corrected = _get(client, detail_path)
        assert MALICIOUS_TEXT.encode() not in corrected.data
        assert b"&lt;script&gt;" in corrected.data
    finally:
        close_application(app)


@pytest.mark.parametrize(
    "action",
    [
        "confirm",
        "correct",
        "dismiss",
        "delegate",
        "reschedule",
        "complete",
        "abandon",
        "delete",
    ],
)
def test_every_mutation_requires_csrf(web_app: Flask, action: str) -> None:
    client = web_app.test_client()
    detail_path = _first_conclusion_path(client)
    action_path, form = _form(client, detail_path, action)
    form.pop("csrf_token")
    response = _post(client, action_path, form)
    assert response.status_code == 400


def test_post_without_origin_still_requires_valid_session_csrf(
    web_app: Flask,
) -> None:
    client = web_app.test_client()
    detail_path = _first_conclusion_path(client)
    action_path, form = _form(client, detail_path, "confirm")

    same_origin_form = client.post(
        action_path,
        base_url=BASE_URL,
        data=form,
    )
    assert same_origin_form.status_code == 303

    missing_csrf = client.post(
        action_path,
        base_url=BASE_URL,
        data={key: value for key, value in form.items() if key != "csrf_token"},
    )
    assert missing_csrf.status_code == 400


def test_opaque_origin_requires_same_origin_navigation_metadata(
    web_app: Flask,
) -> None:
    rejected_client = web_app.test_client()
    rejected_detail = _first_conclusion_path(rejected_client)
    rejected_action, rejected_form = _form(
        rejected_client,
        rejected_detail,
        "confirm",
    )
    for headers in (
        {"Origin": "null"},
        {
            "Origin": "null",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "navigate",
        },
        {
            "Origin": "null",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
        },
    ):
        response = rejected_client.post(
            rejected_action,
            base_url=BASE_URL,
            headers=headers,
            data=rejected_form,
        )
        assert response.status_code == 403

    accepted_client = web_app.test_client()
    accepted_detail = _first_conclusion_path(accepted_client)
    accepted_action, accepted_form = _form(
        accepted_client,
        accepted_detail,
        "confirm",
    )
    response = accepted_client.post(
        accepted_action,
        base_url=BASE_URL,
        headers={
            "Origin": "null",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
        },
        data=accepted_form,
    )
    assert response.status_code == 303


def test_get_cannot_mutate_state(web_app: Flask) -> None:
    client = web_app.test_client()
    detail_path = _first_conclusion_path(client)
    action_path, _ = _form(client, detail_path, "dismiss")
    response = _get(client, action_path)
    assert response.status_code == 405
    store = web_app.extensions["chief_of_staff_store"]
    assert isinstance(store, StateStore)
    assert store.inspect_state().disposition_events == 0


def test_duplicate_submission_is_idempotent_and_stale_version_is_rejected(
    web_app: Flask,
) -> None:
    client = web_app.test_client()
    detail_path = _first_conclusion_path(client)
    action_path, form = _form(client, detail_path, "confirm")
    stale_action, stale_form = _form(client, detail_path, "dismiss")

    first = _post(client, action_path, form)
    second = _post(client, action_path, form)
    assert first.status_code == 303
    assert second.status_code == 303

    response = _post(client, stale_action, stale_form)
    assert response.status_code == 409

    store = web_app.extensions["chief_of_staff_store"]
    assert isinstance(store, StateStore)
    assert store.inspect_state().disposition_events == 1


@pytest.mark.parametrize(
    ("action", "extra_fields", "expected_state"),
    [
        ("confirm", {"note": "Confirmed synthetically."}, "confirmed"),
        (
            "correct",
            {
                "replacement_text": "Use the corrected synthetic interpretation.",
                "explanation": "The earlier interpretation was too broad.",
            },
            "corrected",
        ),
        ("dismiss", {"explanation": "Not actionable."}, "dismissed"),
        (
            "delegate",
            {
                "delegate_description": "Synthetic teammate",
                "follow_up_date": "2026-08-03",
            },
            "delegated",
        ),
        (
            "reschedule",
            {"rescheduled_for": "2026-08-04T09:30"},
            "rescheduled",
        ),
        ("complete", {"note": "Completed synthetically."}, "completed"),
        (
            "abandon",
            {"explanation": "Intentionally out of scope."},
            "intentionally_abandoned",
        ),
    ],
)
def test_every_local_disposition_is_supported_and_history_is_inspectable(
    tmp_path: Path,
    action: str,
    extra_fields: dict[str, str],
    expected_state: str,
) -> None:
    path = tmp_path / f"{action}.sqlite3"
    _seed_database(path)
    app = create_app(path, session_secret=b"s" * 32, testing=True)
    try:
        client = app.test_client()
        detail_path = _first_conclusion_path(client)
        action_path, form = _form(client, detail_path, action)
        form.update(extra_fields)
        response = _post(client, action_path, form)
        assert response.status_code == 303

        store = app.extensions["chief_of_staff_store"]
        assert isinstance(store, StateStore)
        state = store.inspect_conclusion("commitment-conclusion")
        assert state is not None
        assert state.projection is not None
        assert state.projection.current_state == expected_state
        assert len(state.history) == 1
        event = state.history[0]
        assert event.previous_state == "active"
        assert event.new_state == expected_state
        assert event.evidence_fingerprint == "commitment-fingerprint-v1"
        assert event.processing_version == "synthetic-rules-v1"
        assert event.briefing_run_id == "briefing-run"

        html = _get(client, detail_path).get_data(as_text=True)
        assert "Your changes" in html
        assert "Not reviewed" in html
        assert "Originating briefing 2026-07-30" in html
        history = re.search(
            r'<section class="history".*?</section>',
            html,
            flags=re.DOTALL,
        )
        assert history is not None
        assert "synthetic-rules-v1" not in history.group(0)
        assert "Evidence version" not in history.group(0)
        assert '<details class="technical-details">' in html
        assert "synthetic-rules-v1" in html
    finally:
        close_application(app)


def test_recurrence_suppression_correction_and_material_change_are_explainable(
    web_app: Flask,
) -> None:
    store = web_app.extensions["chief_of_staff_store"]
    assert isinstance(store, StateStore)
    state = store.inspect_conclusion("waiting-conclusion")
    assert state is not None and state.projection is not None
    store.apply_disposition(
        conclusion_id="waiting-conclusion",
        disposition=DispositionKind.DISMISSED,
        expected_version=state.projection.version,
        idempotency_key="synthetic-dismiss-token",
        created_at=NOW + timedelta(minutes=1),
    )
    unchanged = store.recurrence_decision("waiting-fingerprint-v1")
    changed = store.recurrence_decision(
        "waiting-fingerprint-v2",
        source_records=(("gmail_work", "synthetic-message"),),
    )
    assert unchanged.action.value == "suppress"
    assert changed.action.value == "show"
    assert changed.material_evidence_changed
    assert changed.reappearance_explanation is not None
    assert "Material source evidence changed" in changed.reappearance_explanation

    corrected = store.inspect_conclusion("commitment-conclusion")
    assert corrected is not None and corrected.projection is not None
    store.apply_disposition(
        conclusion_id="commitment-conclusion",
        disposition=DispositionKind.CORRECTED,
        expected_version=corrected.projection.version,
        idempotency_key="synthetic-correct-token",
        replacement_text="Corrected synthetic commitment.",
        created_at=NOW + timedelta(minutes=2),
    )
    correction_decision = store.recurrence_decision("commitment-fingerprint-v1")
    assert correction_decision.action.value == "replace"
    assert correction_decision.replacement_text == "Corrected synthetic commitment."


def test_local_actions_preserve_authoritative_source_and_make_no_external_calls(
    web_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("external call is not allowed")

    monkeypatch.setattr("urllib.request.urlopen", forbidden_call)
    monkeypatch.setattr("openai.OpenAI", forbidden_call)
    client = web_app.test_client()
    detail_path = _first_conclusion_path(client)
    action_path, form = _form(client, detail_path, "dismiss")
    response = _post(client, action_path, form)
    assert response.status_code == 303

    store = web_app.extensions["chief_of_staff_store"]
    assert isinstance(store, StateStore)
    state = store.inspect_conclusion("commitment-conclusion")
    assert state is not None
    assert state.evidence[0].excerpt == (
        "A confirmed preparation block begins at 9:00 a.m."
    )
    rules = {
        rule.rule
        for rule in web_app.url_map.iter_rules()
        if "static" not in rule.endpoint
    }
    assert rules == {
        "/",
        "/conclusions/<handle>",
        "/conclusions/<handle>/actions/<action>",
    }


def test_deletion_removes_payload_history_indexes_and_keeps_minimal_tombstone(
    web_app: Flask,
) -> None:
    client = web_app.test_client()
    detail_path = _first_conclusion_path(client)
    dismiss_path, dismiss_form = _form(client, detail_path, "dismiss")
    assert _post(client, dismiss_path, dismiss_form).status_code == 303

    database = web_app.extensions["chief_of_staff_database"]
    store = web_app.extensions["chief_of_staff_store"]
    assert isinstance(database, Database)
    assert isinstance(store, StateStore)
    section_row = database.connection.execute(
        """
        SELECT section.id
        FROM briefing_sections AS section
        JOIN briefing_items AS item ON item.section_id = section.id
        WHERE item.id = 'commitment-item'
        """
    ).fetchone()
    assert section_row is not None
    deleted_section_id = int(section_row["id"])
    database.connection.execute(
        "UPDATE briefing_sections SET summary = ? WHERE id = ?",
        ("Sensitive synthetic derived summary.", deleted_section_id),
    )

    delete_path, delete_form = _form(client, detail_path, "delete")
    delete_form["delete_confirmation"] = "delete-local-only"
    result = _post(client, delete_path, delete_form)
    assert result.status_code == 303

    assert store.inspect_conclusion("commitment-conclusion") is None
    assert (
        database.connection.execute(
            "SELECT COUNT(*) FROM disposition_events"
        ).fetchone()[0]
        == 0
    )
    assert (
        database.connection.execute(
            "SELECT COUNT(*) FROM briefing_items WHERE id = 'commitment-item'"
        ).fetchone()[0]
        == 0
    )
    assert (
        database.connection.execute(
            "SELECT COUNT(*) FROM briefing_sections WHERE id = ?",
            (deleted_section_id,),
        ).fetchone()[0]
        == 0
    )
    assert (
        database.connection.execute(
            "SELECT COUNT(*) FROM source_evidence WHERE id = 'commitment-evidence'"
        ).fetchone()[0]
        == 1
    )
    tombstone = database.connection.execute(
        "SELECT * FROM conclusion_tombstones"
    ).fetchone()
    assert tombstone is not None
    assert set(tombstone.keys()) == {
        "evidence_fingerprint",
        "processing_version",
        "idempotency_key",
        "deleted_at",
    }
    assert (
        store.recurrence_decision("commitment-fingerprint-v1").disposition
        is DispositionKind.DELETED
    )


def test_deletion_removes_exclusive_sensitive_evidence(web_app: Flask) -> None:
    database = web_app.extensions["chief_of_staff_database"]
    store = web_app.extensions["chief_of_staff_store"]
    assert isinstance(database, Database)
    assert isinstance(store, StateStore)
    state = store.inspect_conclusion("waiting-conclusion")
    assert state is not None and state.projection is not None

    assert store.delete_local_conclusion(
        conclusion_id="waiting-conclusion",
        expected_version=state.projection.version,
        idempotency_key="synthetic-exclusive-delete",
        deleted_at=NOW,
    )
    assert store.inspect_conclusion("waiting-conclusion") is None
    assert (
        database.connection.execute(
            "SELECT COUNT(*) FROM source_evidence WHERE id = 'waiting-evidence'"
        ).fetchone()[0]
        == 0
    )
    assert (
        database.connection.execute(
            "SELECT COUNT(*) FROM briefing_items WHERE id = 'waiting-item'"
        ).fetchone()[0]
        == 0
    )


def test_failed_deletion_rolls_back_without_partial_tombstone(
    web_app: Flask,
) -> None:
    database = web_app.extensions["chief_of_staff_database"]
    store = web_app.extensions["chief_of_staff_store"]
    assert isinstance(database, Database)
    assert isinstance(store, StateStore)
    state = store.inspect_conclusion("commitment-conclusion")
    assert state is not None and state.projection is not None
    database.connection.execute(
        """
        CREATE TRIGGER synthetic_abort_conclusion_delete
        BEFORE DELETE ON conclusions
        BEGIN
            SELECT RAISE(ABORT, 'synthetic rollback');
        END
        """
    )
    with pytest.raises(Exception, match="synthetic rollback"):
        store.delete_local_conclusion(
            conclusion_id="commitment-conclusion",
            expected_version=state.projection.version,
            idempotency_key="synthetic-delete-rollback",
            deleted_at=NOW,
        )
    assert store.inspect_conclusion("commitment-conclusion") is not None
    assert store.inspect_state().conclusion_tombstones == 0


@pytest.mark.parametrize(
    ("coverage", "expected_text"),
    [
        (CoverageStatus.COMPLETE, "Complete"),
        (CoverageStatus.PARTIAL, "Partial"),
        (CoverageStatus.UNAVAILABLE, "Unavailable"),
    ],
)
def test_briefing_structure_links_coverage_and_health_remain_visible(
    tmp_path: Path,
    coverage: CoverageStatus,
    expected_text: str,
) -> None:
    path = tmp_path / f"{coverage}.sqlite3"
    _seed_database(path, coverage_status=coverage)
    app = create_app(path, session_secret=b"s" * 32, testing=True)
    try:
        response = _get(app.test_client(), "/")
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert html.index("Today&#39;s Outcomes") < html.index("People Waiting on Brad")
        assert html.index("People Waiting on Brad") < html.index("Commitments at Risk")
        assert "Open authoritative source" not in html
        assert "https://calendar.google.com/" in html
        assert "Source coverage and freshness" in html
        assert expected_text in html
        assert "approved candidate limit was reached" in html
        assert "bounded_candidate_cap" not in html
        assert "synthetic_review" not in html
        assert "javascript:alert" not in html
    finally:
        close_application(app)


def test_no_briefing_empty_history_long_content_and_private_fields_are_safe(
    tmp_path: Path,
) -> None:
    empty_path = tmp_path / "empty.sqlite3"
    _seed_database(empty_path, include_briefing=False)
    empty_app = create_app(empty_path, session_secret=b"s" * 32, testing=True)
    try:
        response = _get(empty_app.test_client(), "/")
        assert b"No briefing has been generated yet." in response.data
        assert b"make briefing" in response.data
    finally:
        close_application(empty_app)

    long_path = tmp_path / "long.sqlite3"
    _seed_database(long_path, long_content=True)
    long_app = create_app(long_path, session_secret=b"s" * 32, testing=True)
    try:
        client = long_app.test_client()
        home = _get(client, "/")
        assert home.status_code == 200
        assert len(home.data) < 100_000
        detail = _get(client, _first_conclusion_path(client))
        html = detail.get_data(as_text=True)
        assert "No changes have been recorded." in html
        assert "raw Gmail body" not in html
        assert "MIME" not in html
        assert "provider response" not in html
        assert "hidden reasoning" not in html
        assert "credential" not in html.lower()
        assert "commitment-conclusion" not in html
        assert "commitment-evidence" not in html
    finally:
        close_application(long_app)


def test_print_and_temporal_styles_preserve_written_structure() -> None:
    root = Path(__file__).resolve().parents[1]
    css = (root / "src/chief_of_staff/web/static/style.css").read_text(encoding="utf-8")

    assert "@media print" in css
    assert "break-inside: avoid" in css
    assert "break-after: avoid" in css
    assert ".temporal-earlier-today" in css
    assert ".temporal-in-progress" in css
