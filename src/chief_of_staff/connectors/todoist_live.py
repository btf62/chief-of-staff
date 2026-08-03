"""Live read-only Todoist HTTP and stored-authorization boundaries."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Protocol, cast

from chief_of_staff.auth.keychain import (
    KeychainSecretNotFound,
    KeychainSecretReference,
    MacOSKeychain,
)
from chief_of_staff.connectors.todoist import (
    DEFAULT_MAX_PAGES,
    TODOIST_DATA_READ_SCOPE,
    TodoistAuthenticationError,
    TodoistAuthorization,
    TodoistAuthorizationUnavailable,
    TodoistFilterRequest,
    TodoistLabel,
    TodoistLabelPage,
    TodoistPageRequest,
    TodoistProject,
    TodoistRateLimitError,
    TodoistRetrievalError,
    TodoistSection,
    TodoistTask,
    TodoistTaskPage,
    TodoistUser,
)
from chief_of_staff.domain import (
    AuthorizationStatus,
    ConnectorAuthorizationMetadata,
    CredentialHealth,
)
from chief_of_staff.persistence import StateStore

TODOIST_API_ROOT: Final = "https://api.todoist.com/api/v1"
MAX_TODOIST_RESPONSE_BYTES: Final = 4 * 1024 * 1024


class TodoistPrioritySemanticConflict(RuntimeError):
    """Raised when live endpoint values do not prove the accepted P1/P2 mapping."""


@dataclass(frozen=True, slots=True)
class TodoistPriorityProbeResult:
    """Privacy-safe result of endpoint-specific P1/P2 semantic verification."""

    p1_task_count: int
    p2_task_count: int
    p1_api_values: tuple[int, ...]
    p2_api_values: tuple[int, ...]
    page_count: int

    @property
    def mapping(self) -> tuple[tuple[str, int], ...]:
        """Return the verified user-facing to API mapping."""

        return (("P1", 4), ("P2", 3), ("P3", 2), ("P4", 1))


class TodoistAuthorizationRefresher(Protocol):
    """Refresh an expired approved grant without broadening its scope."""

    def refresh_authorization(
        self,
        *,
        account_reference: str,
    ) -> ConnectorAuthorizationMetadata:
        """Rotate access and refresh tokens in Keychain."""


class TodoistHttpResponse(Protocol):
    """Minimal response surface used by the read-only transport."""

    def read(self, amount: int = -1) -> bytes:
        """Read a bounded response body."""

    def __enter__(self) -> TodoistHttpResponse:
        """Enter the response context."""

    def __exit__(self, *args: object) -> None:
        """Close the response context."""


class TodoistUrlOpener(Protocol):
    """Injectable HTTPS opener for contract tests."""

    def __call__(
        self,
        request: urllib.request.Request,
        *,
        timeout: int,
    ) -> TodoistHttpResponse:
        """Open one GET request."""


def _open_url(
    request: urllib.request.Request,
    *,
    timeout: int,
) -> TodoistHttpResponse:
    return cast(
        TodoistHttpResponse,
        urllib.request.urlopen(  # noqa: S310 - fixed HTTPS request
            request,
            timeout=timeout,
        ),
    )


@dataclass(frozen=True, slots=True)
class StoredTodoistAuthorizationProvider:
    """Resolve exact-scope metadata and verify Keychain credential presence."""

    state_store: StateStore
    keychain: MacOSKeychain
    refresher: TodoistAuthorizationRefresher | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def get_todoist_authorization(
        self,
        account_reference: str,
    ) -> TodoistAuthorization:
        metadata = self.state_store.get_connector_authorization("todoist")
        access_present = bool(
            metadata is not None
            and self.keychain.exists(
                KeychainSecretReference(
                    service=metadata.credential_service,
                    account=metadata.access_token_account,
                )
            )
        )
        if (
            metadata is not None
            and metadata.account_reference == account_reference
            and metadata.granted_scope == TODOIST_DATA_READ_SCOPE
            and metadata.authorization_status is AuthorizationStatus.AUTHORIZED
            and metadata.credential_health is CredentialHealth.HEALTHY
            and (metadata.token_expires_at <= self.clock() or not access_present)
            and metadata.refresh_token_account is not None
            and metadata.refresh_health is CredentialHealth.HEALTHY
            and self.refresher is not None
        ):
            metadata = self.refresher.refresh_authorization(
                account_reference=account_reference,
            )
            access_present = self.keychain.exists(
                KeychainSecretReference(
                    service=metadata.credential_service,
                    account=metadata.access_token_account,
                )
            )

        if (
            metadata is None
            or metadata.account_reference != account_reference
            or metadata.granted_scope != TODOIST_DATA_READ_SCOPE
            or metadata.authorization_status is not AuthorizationStatus.AUTHORIZED
            or metadata.credential_health is not CredentialHealth.HEALTHY
            or metadata.token_expires_at <= self.clock()
            or not access_present
        ):
            raise TodoistAuthorizationUnavailable
        reference = KeychainSecretReference(
            service=metadata.credential_service,
            account=metadata.access_token_account,
        )
        return TodoistAuthorization(
            account_reference=metadata.account_reference,
            account_identity=metadata.account_identity,
            granted_scopes=frozenset({metadata.granted_scope}),
            credential_reference=reference.identifier,
        )


@dataclass(frozen=True, slots=True)
class TodoistHttpTransport:
    """Call only approved Todoist read endpoints."""

    keychain: MacOSKeychain
    access_token_reference: KeychainSecretReference
    url_opener: TodoistUrlOpener = field(
        default=_open_url,
        repr=False,
        compare=False,
    )

    def get_authenticated_user(
        self,
        authorization: TodoistAuthorization,
    ) -> TodoistUser:
        payload = self._get_json(authorization, "/user")
        if not isinstance(payload, dict):
            raise TodoistRetrievalError
        try:
            user_id = _required_identifier(payload.get("id"))
            email = _required_string(payload.get("email"))
            tz_info = payload.get("tz_info")
            timezone = None
            if isinstance(tz_info, dict):
                value = tz_info.get("timezone")
                if isinstance(value, str) and value.strip():
                    timezone = value.strip()
            return TodoistUser(id=user_id, email=email, timezone=timezone)
        finally:
            payload.clear()

    def filter_tasks(
        self,
        authorization: TodoistAuthorization,
        request: TodoistFilterRequest,
    ) -> TodoistTaskPage:
        query = {
            "limit": str(request.limit),
            "query": request.query,
        }
        if request.cursor is not None:
            query["cursor"] = request.cursor
        payload = self._get_json(
            authorization,
            "/tasks/filter?" + urllib.parse.urlencode(query),
        )
        if not isinstance(payload, dict):
            raise TodoistRetrievalError
        try:
            raw_results = payload.get("results")
            next_cursor = payload.get("next_cursor")
            if not isinstance(raw_results, list) or not (
                next_cursor is None or isinstance(next_cursor, str)
            ):
                raise TodoistRetrievalError
            tasks = tuple(_task_from_payload(item) for item in raw_results)
            raw_results.clear()
            return TodoistTaskPage(tasks=tasks, next_cursor=next_cursor)
        finally:
            payload.clear()

    def list_tasks(
        self,
        authorization: TodoistAuthorization,
        request: TodoistPageRequest,
    ) -> TodoistTaskPage:
        query = {"limit": str(request.limit)}
        if request.cursor is not None:
            query["cursor"] = request.cursor
        payload = self._get_json(
            authorization,
            "/tasks?" + urllib.parse.urlencode(query),
        )
        if not isinstance(payload, dict):
            raise TodoistRetrievalError
        try:
            raw_results = payload.get("results")
            next_cursor = payload.get("next_cursor")
            if not isinstance(raw_results, list) or not (
                next_cursor is None or isinstance(next_cursor, str)
            ):
                raise TodoistRetrievalError
            tasks = tuple(_task_from_payload(item) for item in raw_results)
            raw_results.clear()
            return TodoistTaskPage(tasks=tasks, next_cursor=next_cursor)
        finally:
            payload.clear()

    def get_project(
        self,
        authorization: TodoistAuthorization,
        project_id: str,
    ) -> TodoistProject:
        safe_id = urllib.parse.quote(project_id, safe="")
        payload = self._get_json(authorization, f"/projects/{safe_id}")
        if not isinstance(payload, dict):
            raise TodoistRetrievalError
        try:
            return TodoistProject(
                id=_required_identifier(payload.get("id")),
                name=_required_string(payload.get("name")),
                is_shared=_optional_bool(payload.get("is_shared")),
                can_assign_tasks=_optional_bool(payload.get("can_assign_tasks")),
            )
        finally:
            payload.clear()

    def get_section(
        self,
        authorization: TodoistAuthorization,
        section_id: str,
    ) -> TodoistSection:
        safe_id = urllib.parse.quote(section_id, safe="")
        payload = self._get_json(authorization, f"/sections/{safe_id}")
        if not isinstance(payload, dict):
            raise TodoistRetrievalError
        try:
            return TodoistSection(
                id=_required_identifier(payload.get("id")),
                project_id=_required_identifier(payload.get("project_id")),
                name=_required_string(payload.get("name")),
            )
        finally:
            payload.clear()

    def list_labels(
        self,
        authorization: TodoistAuthorization,
        request: TodoistPageRequest,
    ) -> TodoistLabelPage:
        query = {"limit": str(request.limit)}
        if request.cursor is not None:
            query["cursor"] = request.cursor
        payload = self._get_json(
            authorization,
            "/labels?" + urllib.parse.urlencode(query),
        )
        if not isinstance(payload, dict):
            raise TodoistRetrievalError
        try:
            raw_results = payload.get("results")
            next_cursor = payload.get("next_cursor")
            if not isinstance(raw_results, list) or not (
                next_cursor is None or isinstance(next_cursor, str)
            ):
                raise TodoistRetrievalError
            labels = tuple(_label_from_payload(item) for item in raw_results)
            raw_results.clear()
            return TodoistLabelPage(labels=labels, next_cursor=next_cursor)
        finally:
            payload.clear()

    def _get_json(
        self,
        authorization: TodoistAuthorization,
        path: str,
    ) -> object:
        if authorization.credential_reference != (
            self.access_token_reference.identifier
        ):
            raise TodoistAuthenticationError
        if not path.startswith("/") or "://" in path:
            raise TodoistRetrievalError
        try:
            access_token = self.keychain.read(self.access_token_reference)
        except KeychainSecretNotFound:
            raise TodoistAuthenticationError from None
        request = urllib.request.Request(  # noqa: S310 - fixed HTTPS root
            TODOIST_API_ROOT + path,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
            method="GET",
        )
        try:
            with self.url_opener(request, timeout=30) as response:
                raw_response = bytearray(response.read(MAX_TODOIST_RESPONSE_BYTES + 1))
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                raise TodoistAuthenticationError from None
            if error.code == 429:
                raise TodoistRateLimitError from None
            raise TodoistRetrievalError from None
        except urllib.error.URLError, TimeoutError:
            raise TodoistRetrievalError from None
        finally:
            access_token = ""
        try:
            if len(raw_response) > MAX_TODOIST_RESPONSE_BYTES:
                raise TodoistRetrievalError
            return json.loads(raw_response)
        except json.JSONDecodeError, UnicodeDecodeError:
            raise TodoistRetrievalError from None
        finally:
            raw_response[:] = b"\x00" * len(raw_response)


def verify_todoist_priority_semantics(
    transport: TodoistHttpTransport,
    authorization: TodoistAuthorization,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> TodoistPriorityProbeResult:
    """Prove the API values returned by the endpoint's P1 and P2 filters."""

    if max_pages < 1:
        raise ValueError("Todoist priority probe max_pages must be positive")
    p1_tasks, p1_pages = _collect_priority_filter(
        transport,
        authorization,
        query="p1",
        max_pages=max_pages,
    )
    p2_tasks, p2_pages = _collect_priority_filter(
        transport,
        authorization,
        query="p2",
        max_pages=max_pages,
    )
    result = TodoistPriorityProbeResult(
        p1_task_count=len(p1_tasks),
        p2_task_count=len(p2_tasks),
        p1_api_values=tuple(sorted({task.priority for task in p1_tasks})),
        p2_api_values=tuple(sorted({task.priority for task in p2_tasks})),
        page_count=p1_pages + p2_pages,
    )
    if result.p1_api_values != (4,) or result.p2_api_values != (3,):
        raise TodoistPrioritySemanticConflict(
            "Todoist P1/P2 filter values do not prove the accepted endpoint mapping"
        )
    return result


def _collect_priority_filter(
    transport: TodoistHttpTransport,
    authorization: TodoistAuthorization,
    *,
    query: str,
    max_pages: int,
) -> tuple[tuple[TodoistTask, ...], int]:
    tasks: dict[str, TodoistTask] = {}
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for page_number in range(1, max_pages + 1):
        page = transport.filter_tasks(
            authorization,
            TodoistFilterRequest(query=query, cursor=cursor),
        )
        tasks.update((task.id, task) for task in page.tasks)
        if page.next_cursor is None:
            return tuple(tasks.values()), page_number
        if page.next_cursor in seen_cursors:
            raise TodoistRetrievalError
        seen_cursors.add(page.next_cursor)
        cursor = page.next_cursor
    raise TodoistRetrievalError


def _task_from_payload(payload: object) -> TodoistTask:
    if not isinstance(payload, dict):
        raise TodoistRetrievalError
    due = payload.get("due")
    due_date: str | None = None
    due_datetime: str | None = None
    due_timezone: str | None = None
    recurring = False
    if due is not None:
        if not isinstance(due, dict):
            raise TodoistRetrievalError
        raw_due = due.get("date")
        if not isinstance(raw_due, str) or not raw_due:
            raise TodoistRetrievalError
        if "T" in raw_due:
            due_datetime = raw_due
        else:
            due_date = raw_due
        raw_timezone = due.get("timezone")
        if isinstance(raw_timezone, str) and raw_timezone:
            due_timezone = raw_timezone
        raw_recurring = due.get("is_recurring", False)
        if not isinstance(raw_recurring, bool):
            raise TodoistRetrievalError
        recurring = raw_recurring

    labels = payload.get("labels", [])
    if not isinstance(labels, list) or not all(
        isinstance(label, str) for label in labels
    ):
        raise TodoistRetrievalError
    raw_priority = payload.get("priority")
    if isinstance(raw_priority, bool) or not isinstance(raw_priority, int):
        raise TodoistRetrievalError
    return TodoistTask(
        id=_required_identifier(payload.get("id")),
        content=_required_string(payload.get("content")),
        priority=raw_priority,
        project_id=_optional_identifier(payload.get("project_id")),
        section_id=_optional_identifier(payload.get("section_id")),
        label_names=tuple(label for label in labels if label.strip()),
        responsible_user_id=_optional_identifier(payload.get("responsible_uid")),
        parent_id=_optional_identifier(payload.get("parent_id")),
        created_at=_optional_datetime(payload.get("added_at")),
        updated_at=_optional_datetime(payload.get("updated_at")),
        due_date=due_date,
        due_datetime=due_datetime,
        due_timezone=due_timezone,
        recurring=recurring,
    )


def _label_from_payload(payload: object) -> TodoistLabel:
    if not isinstance(payload, dict):
        raise TodoistRetrievalError
    return TodoistLabel(
        id=_required_identifier(payload.get("id")),
        name=_required_string(payload.get("name")),
    )


def _required_string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TodoistRetrievalError
    return value.strip()


def _required_identifier(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TodoistRetrievalError
    normalized = str(value).strip()
    if not normalized:
        raise TodoistRetrievalError
    return normalized


def _optional_bool(value: object) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise TodoistRetrievalError
    return value


def _optional_identifier(value: object) -> str | None:
    if value is None:
        return None
    return _required_identifier(value)


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TodoistRetrievalError
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise TodoistRetrievalError from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TodoistRetrievalError
    return parsed.astimezone(UTC)
