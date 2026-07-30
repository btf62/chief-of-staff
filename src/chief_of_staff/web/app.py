"""Flask application for the local-only briefing and correction experience."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Final, cast
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    Response,
    abort,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.wrappers import Response as WerkzeugResponse

from chief_of_staff.domain import (
    BriefingPresentationItem,
    BriefingPresentationState,
    ConclusionState,
    CoverageStatus,
    DispositionKind,
)
from chief_of_staff.persistence import (
    Database,
    InvalidDispositionError,
    StaleConclusionVersionError,
    StateStore,
)

DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8765
MAX_REQUEST_BYTES: Final = 32 * 1024
MAX_FORM_MEMORY_BYTES: Final = 16 * 1024
SESSION_LIFETIME: Final = timedelta(minutes=30)
_FORWARDED_HEADERS: Final = frozenset(
    {
        "Forwarded",
        "X-Forwarded-For",
        "X-Forwarded-Host",
        "X-Forwarded-Port",
        "X-Forwarded-Proto",
        "X-Forwarded-Server",
    }
)
_ACTIONS: Final = {
    "confirm": DispositionKind.CONFIRMED,
    "correct": DispositionKind.CORRECTED,
    "dismiss": DispositionKind.DISMISSED,
    "delegate": DispositionKind.DELEGATED,
    "reschedule": DispositionKind.RESCHEDULED,
    "complete": DispositionKind.COMPLETED,
    "abandon": DispositionKind.INTENTIONALLY_ABANDONED,
}
_COMMON_FORM_FIELDS: Final = frozenset({"csrf_token", "version", "submission_token"})
_ACTION_FORM_FIELDS: Final = {
    "confirm": frozenset({"note"}),
    "correct": frozenset({"replacement_text", "explanation"}),
    "dismiss": frozenset({"explanation"}),
    "delegate": frozenset({"delegate_description", "follow_up_date", "explanation"}),
    "reschedule": frozenset({"rescheduled_for", "explanation"}),
    "complete": frozenset({"note"}),
    "abandon": frozenset({"explanation"}),
    "delete": frozenset({"delete_confirmation"}),
}


@dataclass(frozen=True, slots=True)
class ConclusionReference:
    """Process-local opaque route reference for one conclusion."""

    conclusion_id: str
    briefing_run_id: str


class HandleRegistry:
    """Keep database identifiers out of browser-visible URLs and forms."""

    def __init__(self) -> None:
        self._references: dict[str, ConclusionReference] = {}
        self._handles: dict[ConclusionReference, str] = {}

    def issue(self, reference: ConclusionReference) -> str:
        """Return a process-local opaque handle for a reference."""

        existing = self._handles.get(reference)
        if existing is not None:
            return existing
        handle = secrets.token_urlsafe(18)
        self._references[handle] = reference
        self._handles[reference] = handle
        return handle

    def resolve(self, handle: str) -> ConclusionReference | None:
        """Resolve an opaque handle without accepting a database identifier."""

        return self._references.get(handle)

    def remove(self, handle: str) -> None:
        """Forget a deleted conclusion's process-local handle."""

        reference = self._references.pop(handle, None)
        if reference is not None:
            self._handles.pop(reference, None)


def create_app(
    database_path: Path,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    session_secret: bytes | None = None,
    testing: bool = False,
) -> Flask:
    """Create a loopback-only Flask application over one validated database."""

    if host != DEFAULT_HOST:
        raise ValueError("the local web interface must bind to 127.0.0.1")
    if not 1024 <= port <= 65535:
        raise ValueError("the local web port must be between 1024 and 65535")

    database = Database.open(database_path)
    state_store = StateStore(database)
    secret = session_secret or secrets.token_bytes(32)
    app = Flask(__name__)
    app.config.update(
        DEBUG=False,
        TESTING=testing,
        SECRET_KEY=secret,
        MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,
        MAX_FORM_MEMORY_SIZE=MAX_FORM_MEMORY_BYTES,
        MAX_FORM_PARTS=20,
        PERMANENT_SESSION_LIFETIME=SESSION_LIFETIME,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        # The accepted interface is plain HTTP on IPv4 loopback. Marking this
        # cookie Secure would prevent it from operating in that boundary.
        SESSION_COOKIE_SECURE=False,
        TRUSTED_HOSTS=[f"{host}:{port}"],
    )
    app.extensions["chief_of_staff_database"] = database
    app.extensions["chief_of_staff_store"] = state_store
    app.extensions["chief_of_staff_handles"] = HandleRegistry()
    app.extensions["chief_of_staff_host"] = host
    app.extensions["chief_of_staff_port"] = port
    app.extensions["chief_of_staff_secret"] = secret

    @app.before_request
    def enforce_local_request_boundary() -> Response | None:
        raw_host = request.environ.get("HTTP_HOST", "")
        expected_host = f"{host}:{port}"
        if raw_host != expected_host:
            return _plain_boundary_error(status=400)
        if request.remote_addr != DEFAULT_HOST:
            abort(403, description="The interface is available only on loopback.")
        if any(header in request.headers for header in _FORWARDED_HEADERS):
            abort(400, description="Forwarded headers are not accepted.")
        origin = request.headers.get("Origin")
        expected_origin = f"http://{expected_host}"
        opaque_same_origin_navigation = (
            origin == "null"
            and request.headers.get("Sec-Fetch-Site") == "same-origin"
            and request.headers.get("Sec-Fetch-Mode") == "navigate"
        )
        if (
            origin is not None
            and origin != expected_origin
            and not opaque_same_origin_navigation
        ):
            abort(403, description="Unexpected request origin.")
        return None

    @app.after_request
    def apply_security_headers(response: Response) -> Response:
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "style-src 'self'; "
            "img-src 'self'; "
            "font-src 'none'; "
            "script-src 'none'; "
            "connect-src 'none'; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        response.headers.pop("Server", None)
        return response

    @app.get("/")
    def home() -> str:
        briefing = state_store.latest_briefing_presentation()
        if briefing is None:
            return render_template(
                "home.html",
                briefing=None,
                sections=(),
                status=request.args.get("status"),
            )
        return render_template(
            "home.html",
            briefing=briefing,
            sections=_presentation_sections(briefing, state_store, _handles(app)),
            generation_mode=_generation_mode_display(
                briefing.presentation.generation_mode,
                has_reduced_coverage=any(
                    item.coverage_status is not CoverageStatus.COMPLETE
                    for item in briefing.coverage
                ),
            ),
            generated_at=_format_generated_at(
                briefing.run.generated_at or briefing.presentation.created_at,
                timezone=briefing.run.timezone,
            ),
            historical_disclosure=_web_historical_disclosure(briefing),
            coverage=_coverage_view(briefing),
            status=request.args.get("status"),
        )

    @app.get("/conclusions/<handle>")
    def conclusion_detail(handle: str) -> str:
        reference = _handles(app).resolve(handle)
        if reference is None:
            abort(404)
        conclusion = state_store.inspect_conclusion(reference.conclusion_id)
        if conclusion is None or conclusion.projection is None:
            abort(404)
        csrf_token = _csrf_token()
        form_tokens = {
            action: _form_token(
                app,
                csrf_token=csrf_token,
                conclusion_id=reference.conclusion_id,
                version=conclusion.projection.version,
                action=action,
            )
            for action in (*_ACTIONS, "delete")
        }
        return render_template(
            "conclusion.html",
            conclusion=_conclusion_view(conclusion, state_store),
            csrf_token=csrf_token,
            form_tokens=form_tokens,
            handle=handle,
            status=request.args.get("status"),
        )

    @app.post("/conclusions/<handle>/actions/<action>")
    def apply_conclusion_action(handle: str, action: str) -> WerkzeugResponse:
        reference = _handles(app).resolve(handle)
        if reference is None:
            abort(404)
        if action not in {*_ACTIONS, "delete"}:
            abort(404)
        _validate_form_fields(action)
        _validate_csrf()
        expected_version = _parse_version(request.form.get("version"))
        expected_form_token = _form_token(
            app,
            csrf_token=cast(str, session["csrf_token"]),
            conclusion_id=reference.conclusion_id,
            version=expected_version,
            action=action,
        )
        submitted_form_token = request.form.get("submission_token", "")
        if not hmac.compare_digest(expected_form_token, submitted_form_token):
            abort(400, description="The form token is invalid.")

        try:
            if action == "delete":
                if request.form.get("delete_confirmation") != "delete-local-only":
                    raise InvalidDispositionError(
                        "confirm the local-only deletion before continuing"
                    )
                state_store.delete_local_conclusion(
                    conclusion_id=reference.conclusion_id,
                    expected_version=expected_version,
                    idempotency_key=submitted_form_token,
                    deleted_at=datetime.now(UTC),
                )
                _handles(app).remove(handle)
                return redirect(url_for("home", status="deleted"), code=303)

            disposition = _ACTIONS[action]
            latest_briefing = state_store.get_briefing_presentation(
                reference.briefing_run_id
            )
            timezone = (
                ZoneInfo(latest_briefing.run.timezone)
                if latest_briefing is not None
                else ZoneInfo("America/New_York")
            )
            follow_up_at = _parse_local_date(
                request.form.get("follow_up_date"),
                timezone=timezone,
            )
            rescheduled_for = _parse_local_datetime(
                request.form.get("rescheduled_for"),
                timezone=timezone,
            )
            result = state_store.apply_disposition(
                conclusion_id=reference.conclusion_id,
                disposition=disposition,
                expected_version=expected_version,
                idempotency_key=submitted_form_token,
                created_at=datetime.now(UTC),
                briefing_run_id=reference.briefing_run_id,
                replacement_text=request.form.get("replacement_text"),
                explanation=request.form.get("explanation") or request.form.get("note"),
                delegate_description=request.form.get("delegate_description"),
                follow_up_at=follow_up_at,
                rescheduled_for=rescheduled_for,
            )
        except InvalidDispositionError as error:
            return _safe_error(str(error), status=400)
        except StaleConclusionVersionError:
            return _safe_error(
                "This conclusion changed in another form. Reload and try again.",
                status=409,
            )
        except KeyError:
            abort(404)

        status = "updated" if result.applied else "unchanged"
        return redirect(
            url_for("conclusion_detail", handle=handle, status=status),
            code=303,
        )

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(413)
    def safe_http_error(error: object) -> tuple[str, int]:
        status = int(getattr(error, "code", 500))
        description = str(getattr(error, "description", ""))
        messages = {
            400: "The request could not be accepted.",
            403: "The request is outside the local security boundary.",
            404: "That local record is no longer available.",
            409: "The local state changed. Reload and try again.",
            413: "The submitted form is too large.",
        }
        safe_boundary_details = {
            "The interface is available only on loopback.": (
                "Only a direct IPv4 loopback request is accepted."
            ),
            "Unexpected request origin.": (
                "The form origin does not match the local application."
            ),
            "Forwarded headers are not accepted.": (
                "Proxy and forwarded request headers are not accepted."
            ),
        }
        return render_template(
            "error.html",
            message=safe_boundary_details.get(
                description,
                messages.get(status, "The request could not be completed."),
            ),
        ), status

    return app


def close_application(app: Flask) -> None:
    """Close the application-owned database exactly once."""

    database = app.extensions.pop("chief_of_staff_database", None)
    if isinstance(database, Database):
        database.close()


def _handles(app: Flask) -> HandleRegistry:
    registry = app.extensions["chief_of_staff_handles"]
    if not isinstance(registry, HandleRegistry):
        raise RuntimeError("handle registry is unavailable")
    return registry


def _csrf_token() -> str:
    token = session.get("csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session.clear()
        session["csrf_token"] = token
    session.permanent = True
    return token


def _validate_csrf() -> None:
    stored = session.get("csrf_token")
    submitted = request.form.get("csrf_token", "")
    if (
        not isinstance(stored, str)
        or not submitted
        or not hmac.compare_digest(stored, submitted)
    ):
        abort(400, description="The CSRF token is invalid.")


def _validate_form_fields(action: str) -> None:
    allowed = _COMMON_FORM_FIELDS | _ACTION_FORM_FIELDS[action]
    if set(request.form) - allowed:
        abort(400, description="The form includes an unexpected field.")


def _form_token(
    app: Flask,
    *,
    csrf_token: str,
    conclusion_id: str,
    version: int,
    action: str,
) -> str:
    secret = app.extensions["chief_of_staff_secret"]
    if not isinstance(secret, bytes):
        raise RuntimeError("session secret is unavailable")
    message = f"{csrf_token}\x00{conclusion_id}\x00{version}\x00{action}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _parse_version(raw_value: str | None) -> int:
    if raw_value is None or not raw_value.isascii() or not raw_value.isdigit():
        abort(400, description="The conclusion version is invalid.")
    value = int(raw_value)
    if value < 0:
        abort(400, description="The conclusion version is invalid.")
    return value


def _parse_local_date(
    raw_value: str | None,
    *,
    timezone: ZoneInfo,
) -> datetime | None:
    if raw_value is None or not raw_value.strip():
        return None
    try:
        selected_date = date.fromisoformat(raw_value)
    except ValueError as error:
        raise InvalidDispositionError("follow-up date is invalid") from error
    return datetime.combine(selected_date, time(9), tzinfo=timezone)


def _parse_local_datetime(
    raw_value: str | None,
    *,
    timezone: ZoneInfo,
) -> datetime | None:
    if raw_value is None or not raw_value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError as error:
        raise InvalidDispositionError(
            "rescheduled date and time are invalid"
        ) from error
    if parsed.tzinfo is not None:
        raise InvalidDispositionError("use a local date and time")
    return parsed.replace(tzinfo=timezone)


def _presentation_sections(
    briefing: BriefingPresentationState,
    state_store: StateStore,
    registry: HandleRegistry,
) -> tuple[dict[str, object], ...]:
    sections: list[dict[str, object]] = []
    for section in briefing.presentation.sections:
        items: list[dict[str, object]] = []
        for item in section.items:
            conclusion = (
                None
                if item.conclusion_id is None
                else state_store.inspect_conclusion(item.conclusion_id)
            )
            original_headline = item.headline
            headline = original_headline
            handle = None
            local_state = None
            if conclusion is not None and conclusion.projection is not None:
                headline = conclusion.projection.display_statement
                handle = registry.issue(
                    ConclusionReference(
                        conclusion_id=conclusion.conclusion.id,
                        briefing_run_id=briefing.run.id,
                    )
                )
                local_state = _state_display_name(conclusion.projection.current_state)
            items.append(
                {
                    "headline": headline,
                    "original_headline": (
                        original_headline if headline != original_headline else None
                    ),
                    "detail": item.detail,
                    "role": _content_role(item),
                    "uncertainty": item.uncertainty,
                    "explanation": item.explanation,
                    "sources": tuple(
                        {
                            "name": _source_display_name(source.source),
                            "url": _safe_source_url(source.display_url),
                            "freshness": _format_datetime(source.freshness_at),
                        }
                        for source in item.sources
                    ),
                    "handle": handle,
                    "local_state": local_state,
                    "temporal_state": item.temporal_state,
                    "temporal_class": (
                        None
                        if item.temporal_state is None
                        else item.temporal_state.casefold().replace(" ", "-")
                    ),
                }
            )
        if items or section.summary:
            sections.append(
                {
                    "name": section.name,
                    "summary": section.summary,
                    "items": tuple(items),
                }
            )
    return tuple(sections)


def _conclusion_view(
    state: ConclusionState,
    state_store: StateStore,
) -> dict[str, object]:
    conclusion = state.conclusion
    projection = state.projection
    if projection is None:
        raise RuntimeError("conclusion projection is unavailable")
    history = []
    for event in reversed(state.history):
        briefing_date = None
        if event.briefing_run_id is not None:
            briefing = state_store.get_briefing_presentation(event.briefing_run_id)
            if briefing is not None:
                briefing_date = briefing.run.briefing_date.isoformat()
        history.append(
            {
                "action": _state_display_name(event.disposition.value),
                "previous_state": _state_display_name(event.previous_state),
                "new_state": _state_display_name(
                    event.new_state or event.disposition.value
                ),
                "created_at": _format_datetime(event.created_at),
                "briefing_date": briefing_date or "Briefing no longer retained",
                "evidence_version": _short_fingerprint(event.evidence_fingerprint),
                "processing_version": event.processing_version,
                "explanation": event.note,
                "replacement_text": event.replacement_text,
                "delegate_description": event.delegate_description,
                "follow_up_at": _format_datetime(event.follow_up_at),
                "rescheduled_for": _format_datetime(event.rescheduled_for),
            }
        )
    evidence = tuple(
        {
            "source": _source_display_name(item.source),
            "excerpt": _safe_excerpt(item.excerpt),
            "url": _safe_source_url(item.display_url),
            "freshness": _format_datetime(item.freshness_at or item.retrieved_at),
            "evidence_version": _short_fingerprint(item.evidence_fingerprint),
        }
        for item in state.evidence
    )
    return {
        "statement": projection.display_statement,
        "role": _conclusion_role(state),
        "kind": conclusion.kind.value.replace("_", " ").title(),
        "state": _state_display_name(projection.current_state),
        "version": projection.version,
        "explanation": conclusion.explanation,
        "uncertainty": _confidence_display(conclusion.confidence),
        "processing_version": conclusion.processing_version,
        "evidence_version": _short_fingerprint(conclusion.evidence_fingerprint),
        "evidence": evidence,
        "history": tuple(history),
        "delegate_description": projection.delegate_description,
        "follow_up_at": _format_datetime(projection.follow_up_at),
        "rescheduled_for": _format_datetime(projection.rescheduled_for),
    }


def _coverage_view(
    briefing: BriefingPresentationState,
) -> tuple[dict[str, object], ...]:
    limitations = {
        "bounded_candidate_cap": (
            "The approved candidate limit was reached; some eligible messages "
            "were omitted."
        ),
        "body_candidate_cap_exceeded": (
            "The approved body-review limit was reached; later candidates were omitted."
        ),
        "synthetic_unavailable": (
            "The connector was unavailable during this synthetic briefing."
        ),
    }
    return tuple(
        {
            "source": _source_display_name(item.source),
            "status": item.coverage_status.value.title(),
            "freshness": _format_datetime(item.freshness_at),
            "limitation": (
                None
                if item.error_category is None
                else limitations.get(
                    item.error_category,
                    "Coverage was limited; inspect the local operational record.",
                )
            ),
        }
        for item in briefing.coverage
    )


def _generation_mode_display(
    value: str,
    *,
    has_reduced_coverage: bool = False,
) -> str:
    labels = {
        "deterministic": "Deterministic briefing",
        "deterministic_full": "Deterministic briefing",
        "deterministic_reduced": "Deterministic briefing",
        "degraded": "Deterministic briefing",
    }
    label = labels.get(value, "Deterministic briefing")
    if value == "degraded" or has_reduced_coverage:
        return f"{label} · reduced source coverage"
    return label


def _content_role(item: BriefingPresentationItem) -> str:
    labels = {
        "authoritative_source_fact": "Source record",
        "explicit_detection": "Directly supported",
        "inferred_conclusion": "Inferred",
        "recommendation": "Suggested action",
        "presentation_only_synthesis": "Schedule context",
    }
    return labels.get(item.content_kind, "Briefing item")


def _conclusion_role(state: ConclusionState) -> str:
    if state.conclusion.kind.value == "recommendation":
        return "Suggested action"
    if state.conclusion.classification.value == "inferred":
        return "Inferred"
    return "Directly supported"


def _confidence_display(confidence: float | None) -> str | None:
    if confidence is None:
        return None
    if confidence >= 0.9:
        return "Low uncertainty"
    if confidence >= 0.75:
        return "Moderate uncertainty"
    return "High uncertainty"


def _safe_source_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return value


def _safe_excerpt(value: str | None) -> str | None:
    if value is None:
        return None
    return "".join(
        character
        for character in value[:2000]
        if character in {"\n", "\t"} or ord(character) >= 32
    )


def _source_display_name(value: str) -> str:
    names = {
        "google_calendar": "Google Calendar",
        "todoist": "Todoist",
        "jira": "Jira",
        "gmail": "Work Gmail",
        "gmail_work": "Work Gmail",
        "repository": "Repository context",
        "synthetic": "Synthetic source",
        "synthetic_tasks": "Synthetic tasks",
    }
    return names.get(value, value.replace("_", " ").title())


def _state_display_name(value: str) -> str:
    names = {
        "active": "Not reviewed",
        "confirmed": "Confirmed",
        "corrected": "Corrected",
        "dismissed": "Dismissed",
        "delegated": "Delegated",
        "rescheduled": "Rescheduled",
        "completed": "Completed",
        "intentionally_abandoned": "Intentionally abandoned",
        "deleted": "Deleted locally",
    }
    return names.get(value, value.replace("_", " ").title())


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone().strftime("%b %-d, %Y at %-I:%M %p")


def _format_generated_at(value: datetime, *, timezone: str) -> str:
    local = value.astimezone(ZoneInfo(timezone))
    period = "a.m." if local.hour < 12 else "p.m."
    return f"Generated {local:%A, %B %-d} at {local:%-I:%M} {period}"


def _web_historical_disclosure(
    briefing: BriefingPresentationState,
) -> str | None:
    mode = briefing.run.historical_mode
    if mode == "recorded":
        return "Recorded briefing shown exactly as originally generated."
    if mode == "replay":
        return (
            "Replay using current product logic and archived normalized facts. "
            "This is not the briefing originally shown."
        )
    if mode == "reconstructed":
        return (
            "Reconstructed from available source history. Later source changes "
            "and unavailable historical state may affect accuracy."
        )
    if mode == "synthetic":
        return "Synthetic evaluation scenario; no live personal data."
    return None


def _short_fingerprint(value: str) -> str:
    return value[:12] if value else "Not recorded"


def _safe_error(message: str, *, status: int) -> Response:
    return Response(
        render_template("error.html", message=message),
        status=status,
        content_type="text/html; charset=utf-8",
    )


def _plain_boundary_error(*, status: int) -> Response:
    """Return an error that does not build URLs from an untrusted Host."""

    return Response(
        (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            "<title>Request rejected</title></head><body>"
            "<main><h1>Local request rejected</h1>"
            "<p>The request is outside the approved loopback boundary.</p>"
            "</main></body></html>"
        ),
        status=status,
        content_type="text/html; charset=utf-8",
    )
