"""Fixed-endpoint live Work Gmail transport and stored authorization."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Final, Protocol, cast

from chief_of_staff.auth.keychain import (
    KeychainSecretNotFound,
    KeychainSecretReference,
    MacOSKeychain,
)
from chief_of_staff.connectors.gmail import (
    GMAIL_METADATA_HEADERS,
    GMAIL_READONLY_SCOPE,
    GMAIL_WORK_ACCOUNT,
    GMAIL_WORK_INSTANCE,
    GmailAuthenticationError,
    GmailAuthorization,
    GmailAuthorizationUnavailable,
    GmailFailureCategory,
    GmailFailureStage,
    GmailFullMessage,
    GmailMessageListPage,
    GmailMessageListRequest,
    GmailMessageMetadata,
    GmailMessageReference,
    GmailMimePart,
    GmailProfile,
    GmailRetrievalError,
)
from chief_of_staff.domain import (
    AuthorizationStatus,
    ConnectorAuthorizationMetadata,
    CredentialHealth,
)
from chief_of_staff.persistence import StateStore

GMAIL_API_ROOT: Final = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_PROFILE_URL: Final = f"{GMAIL_API_ROOT}/profile"
GMAIL_MESSAGES_URL: Final = f"{GMAIL_API_ROOT}/messages"
MAX_GMAIL_RESPONSE_BYTES: Final = 8 * 1024 * 1024


class GmailHttpResponse(Protocol):
    """Bounded HTTP response surface used by the live transport."""

    def read(self, amount: int = -1) -> bytes:
        """Read a bounded response."""

    def __enter__(self) -> GmailHttpResponse:
        """Enter the response context."""

    def __exit__(self, *args: object) -> None:
        """Close the response context."""


class GmailUrlOpener(Protocol):
    """Injectable fixed-endpoint URL opener."""

    def __call__(
        self,
        request: urllib.request.Request,
        *,
        timeout: int,
    ) -> GmailHttpResponse:
        """Open one read-only request."""


class GmailCredentialRefresher(Protocol):
    """Refresh one exact Work Gmail authorization."""

    def refresh(
        self,
        *,
        account_reference: str,
    ) -> ConnectorAuthorizationMetadata:
        """Return refreshed non-secret metadata."""


def _open_url(
    request: urllib.request.Request,
    *,
    timeout: int,
) -> GmailHttpResponse:
    return cast(
        GmailHttpResponse,
        urllib.request.urlopen(  # noqa: S310 - fixed HTTPS endpoints
            request,
            timeout=timeout,
        ),
    )


@dataclass(frozen=True, slots=True)
class StoredWorkGmailAuthorizationProvider:
    """Resolve and refresh exactly one Work Gmail grant."""

    state_store: StateStore
    keychain: MacOSKeychain
    refresher: GmailCredentialRefresher | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )

    def get_gmail_authorization(
        self,
        account_reference: str,
    ) -> GmailAuthorization:
        """Return a healthy exact-scope credential reference."""

        metadata = self.state_store.get_connector_authorization(GMAIL_WORK_INSTANCE)
        if (
            metadata is None
            or metadata.connector_instance_id != GMAIL_WORK_INSTANCE
            or metadata.account_reference != account_reference
            or metadata.account_identity.casefold() != GMAIL_WORK_ACCOUNT.casefold()
            or metadata.granted_scope != GMAIL_READONLY_SCOPE
            or metadata.authorization_status is not AuthorizationStatus.AUTHORIZED
        ):
            raise GmailAuthorizationUnavailable

        if (
            metadata.token_expires_at <= self.clock()
            or metadata.credential_health is not CredentialHealth.HEALTHY
        ):
            if self.refresher is None:
                raise GmailAuthorizationUnavailable
            metadata = self.refresher.refresh(account_reference=account_reference)

        reference = KeychainSecretReference(
            service=metadata.credential_service,
            account=metadata.access_token_account,
        )
        if not self.keychain.exists(reference):
            raise GmailAuthorizationUnavailable
        return GmailAuthorization(
            account_reference=metadata.account_reference,
            granted_scopes=frozenset({metadata.granted_scope}),
            credential_reference=reference.identifier,
        )

    def refresh_gmail_authorization(
        self,
        account_reference: str,
    ) -> GmailAuthorization:
        """Refresh once and revalidate the exact Work Gmail grant."""

        if self.refresher is None:
            raise GmailAuthorizationUnavailable
        try:
            self.refresher.refresh(account_reference=account_reference)
        except Exception:
            raise GmailAuthorizationUnavailable from None
        return self.get_gmail_authorization(account_reference)


@dataclass(frozen=True, slots=True)
class WorkGmailHttpTransport:
    """Call only approved Gmail profile, list, metadata, and full GET methods."""

    keychain: MacOSKeychain
    access_token_reference: KeychainSecretReference
    url_opener: GmailUrlOpener = field(
        default=_open_url,
        repr=False,
        compare=False,
    )

    def get_profile(self, authorization: GmailAuthorization) -> GmailProfile:
        """Retrieve only the current user's email profile."""

        payload = self._get_json(
            authorization,
            GMAIL_PROFILE_URL,
            expected_operation="profile",
        )
        email_address = payload.get("emailAddress")
        payload.clear()
        if not isinstance(email_address, str) or "@" not in email_address:
            raise GmailRetrievalError(
                "Gmail profile response was invalid",
                category=GmailFailureCategory.INVALID_PROVIDER_RESPONSE,
                stage=GmailFailureStage.PROFILE,
            )
        return GmailProfile(email_address=email_address)

    def list_messages(
        self,
        authorization: GmailAuthorization,
        request: GmailMessageListRequest,
    ) -> GmailMessageListPage:
        """List one stable query page without mutation."""

        if (
            not request.query
            or not 1 <= request.page_size <= 100
            or (request.page_token is not None and not request.page_token)
        ):
            raise GmailRetrievalError(
                "Gmail list request was invalid",
                category=GmailFailureCategory.UNEXPECTED_INTERNAL_FAILURE,
                stage=GmailFailureStage.LISTING,
            )
        query = {
            "maxResults": str(request.page_size),
            "q": request.query,
        }
        if request.page_token is not None:
            query["pageToken"] = request.page_token
        payload = self._get_json(
            authorization,
            f"{GMAIL_MESSAGES_URL}?{urllib.parse.urlencode(query)}",
            expected_operation="messages.list",
        )
        try:
            raw_messages = payload.get("messages", [])
            next_page_token = payload.get("nextPageToken")
            if not isinstance(raw_messages, list) or not (
                next_page_token is None or isinstance(next_page_token, str)
            ):
                raise GmailRetrievalError(
                    "Gmail list response was invalid",
                    category=GmailFailureCategory.INVALID_PROVIDER_RESPONSE,
                    stage=GmailFailureStage.LISTING,
                )
            messages = tuple(_message_reference(item) for item in raw_messages)
            return GmailMessageListPage(
                messages=messages,
                next_page_token=next_page_token,
            )
        finally:
            payload.clear()

    def get_message_metadata(
        self,
        authorization: GmailAuthorization,
        message_id: str,
    ) -> GmailMessageMetadata:
        """Retrieve approved headers with `format=metadata`."""

        safe_id = _message_id(message_id, stage=GmailFailureStage.METADATA)
        query: list[tuple[str, str]] = [("format", "metadata")]
        query.extend(("metadataHeaders", header) for header in GMAIL_METADATA_HEADERS)
        payload = self._get_json(
            authorization,
            f"{GMAIL_MESSAGES_URL}/{safe_id}?{urllib.parse.urlencode(query)}",
            expected_operation="messages.get.metadata",
        )
        try:
            return _metadata_from_payload(payload, stage=GmailFailureStage.METADATA)
        finally:
            payload.clear()

    def get_message_full(
        self,
        authorization: GmailAuthorization,
        message_id: str,
    ) -> GmailFullMessage:
        """Retrieve one approved candidate with `format=full` only."""

        safe_id = _message_id(message_id, stage=GmailFailureStage.BODY)
        payload = self._get_json(
            authorization,
            f"{GMAIL_MESSAGES_URL}/{safe_id}?format=full",
            expected_operation="messages.get.full",
        )
        try:
            metadata = _metadata_from_payload(payload, stage=GmailFailureStage.BODY)
            mime_payload = payload.get("payload")
            return GmailFullMessage(
                metadata=metadata,
                payload=_mime_part(mime_payload),
            )
        finally:
            payload.clear()

    def _get_json(
        self,
        authorization: GmailAuthorization,
        url: str,
        *,
        expected_operation: str,
    ) -> dict[str, object]:
        if (
            authorization.credential_reference != self.access_token_reference.identifier
            or authorization.granted_scopes != frozenset({GMAIL_READONLY_SCOPE})
        ):
            raise GmailAuthenticationError("Gmail credential reference was invalid")
        if not (
            url == GMAIL_PROFILE_URL
            or url.startswith(f"{GMAIL_MESSAGES_URL}?")
            or url.startswith(f"{GMAIL_MESSAGES_URL}/")
        ):
            raise GmailRetrievalError(
                "Gmail request exceeded fixed endpoints",
                category=GmailFailureCategory.FIXED_ENDPOINT_VIOLATION,
                stage=_operation_stage(expected_operation),
            )
        try:
            access_token = self.keychain.read(self.access_token_reference)
        except KeychainSecretNotFound:
            raise GmailAuthenticationError(
                "Work Gmail access token is missing"
            ) from None
        http_request = urllib.request.Request(  # noqa: S310 - fixed host checked above
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
                "X-Chief-Of-Staff-Operation": expected_operation,
            },
            method="GET",
        )
        try:
            with self.url_opener(http_request, timeout=30) as response:
                raw_response = response.read(MAX_GMAIL_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            if error.code == 401:
                raise GmailAuthenticationError(
                    "Work Gmail authorization failed",
                    stage=GmailFailureStage.AUTHORIZATION,
                ) from None
            if error.code == 403:
                category = GmailFailureCategory.PROVIDER_FORBIDDEN
            elif error.code == 429:
                category = GmailFailureCategory.RATE_LIMITING
            elif 500 <= error.code <= 599:
                category = GmailFailureCategory.PROVIDER_SERVER_FAILURE
            else:
                category = GmailFailureCategory.NETWORK_OR_TRANSPORT_FAILURE
            raise GmailRetrievalError(
                "Work Gmail provider request failed",
                category=category,
                stage=_operation_stage(expected_operation),
                retry_after_seconds=_safe_retry_after(error),
            ) from None
        except TimeoutError:
            raise GmailRetrievalError(
                "Work Gmail provider request timed out",
                category=GmailFailureCategory.TIMEOUT,
                stage=_operation_stage(expected_operation),
            ) from None
        except urllib.error.URLError:
            raise GmailRetrievalError(
                "Work Gmail provider request failed",
                category=GmailFailureCategory.NETWORK_OR_TRANSPORT_FAILURE,
                stage=_operation_stage(expected_operation),
            ) from None
        finally:
            access_token = ""
        if len(raw_response) > MAX_GMAIL_RESPONSE_BYTES:
            raise GmailRetrievalError(
                "Work Gmail response exceeded its limit",
                category=GmailFailureCategory.RESPONSE_SIZE_BOUNDARY,
                stage=_operation_stage(expected_operation),
            )
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError, UnicodeDecodeError:
            raise GmailRetrievalError(
                "Work Gmail response was invalid",
                category=GmailFailureCategory.INVALID_PROVIDER_RESPONSE,
                stage=_operation_stage(expected_operation),
            ) from None
        finally:
            raw_response = b""
        if not isinstance(payload, dict):
            raise GmailRetrievalError(
                "Work Gmail response was invalid",
                category=GmailFailureCategory.INVALID_PROVIDER_RESPONSE,
                stage=_operation_stage(expected_operation),
            )
        return payload


def _safe_retry_after(error: urllib.error.HTTPError) -> int | None:
    """Parse only a bounded Retry-After delay without retaining header content."""

    if error.headers is None:
        return None
    value = error.headers.get("Retry-After")
    if value is None:
        return None
    try:
        delay = int(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except TypeError, ValueError:
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        delay = int((retry_at.astimezone(UTC) - datetime.now(UTC)).total_seconds())
    return max(delay, 0)


def _operation_stage(operation: str) -> GmailFailureStage:
    if operation == "profile":
        return GmailFailureStage.PROFILE
    if operation == "messages.list":
        return GmailFailureStage.LISTING
    if operation == "messages.get.metadata":
        return GmailFailureStage.METADATA
    if operation == "messages.get.full":
        return GmailFailureStage.BODY
    return GmailFailureStage.INITIALIZATION


def _message_id(value: str, *, stage: GmailFailureStage) -> str:
    if not value or not all(
        character.isalnum() or character in "-_" for character in value
    ):
        raise GmailRetrievalError(
            "Gmail message identity was invalid",
            category=GmailFailureCategory.INVALID_PROVIDER_RESPONSE,
            stage=stage,
        )
    return urllib.parse.quote(value, safe="")


def _message_reference(payload: object) -> GmailMessageReference:
    if not isinstance(payload, dict):
        raise GmailRetrievalError(
            "Gmail message reference was invalid",
            category=GmailFailureCategory.INVALID_PROVIDER_RESPONSE,
            stage=GmailFailureStage.LISTING,
        )
    message_id = payload.get("id")
    thread_id = payload.get("threadId")
    if not isinstance(message_id, str) or not isinstance(thread_id, str):
        raise GmailRetrievalError(
            "Gmail message reference was invalid",
            category=GmailFailureCategory.INVALID_PROVIDER_RESPONSE,
            stage=GmailFailureStage.LISTING,
        )
    return GmailMessageReference(id=message_id, thread_id=thread_id)


def _metadata_from_payload(
    payload: dict[str, object],
    *,
    stage: GmailFailureStage,
) -> GmailMessageMetadata:
    message_id = payload.get("id")
    thread_id = payload.get("threadId")
    internal_date = payload.get("internalDate")
    label_ids = payload.get("labelIds", [])
    size_estimate = payload.get("sizeEstimate", 0)
    raw_mime = payload.get("payload")
    if not (
        isinstance(message_id, str)
        and isinstance(thread_id, str)
        and isinstance(internal_date, str)
        and internal_date.isdigit()
        and isinstance(label_ids, list)
        and all(isinstance(label, str) for label in label_ids)
        and isinstance(size_estimate, int)
        and not isinstance(size_estimate, bool)
        and size_estimate >= 0
        and isinstance(raw_mime, dict)
    ):
        raise GmailRetrievalError(
            "Gmail metadata response was invalid",
            category=GmailFailureCategory.INVALID_PROVIDER_RESPONSE,
            stage=stage,
        )
    raw_headers = raw_mime.get("headers", [])
    if not isinstance(raw_headers, list):
        raise GmailRetrievalError(
            "Gmail metadata headers were invalid",
            category=GmailFailureCategory.INVALID_PROVIDER_RESPONSE,
            stage=stage,
        )
    allowed = {name.casefold() for name in GMAIL_METADATA_HEADERS}
    headers: list[tuple[str, str]] = []
    for raw_header in raw_headers:
        if not isinstance(raw_header, dict):
            continue
        name = raw_header.get("name")
        value = raw_header.get("value")
        if (
            isinstance(name, str)
            and name.casefold() in allowed
            and isinstance(value, str)
        ):
            headers.append((name, value[:4096]))
    return GmailMessageMetadata(
        id=message_id,
        thread_id=thread_id,
        internal_date=datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC),
        label_ids=tuple(label_ids),
        size_estimate=size_estimate,
        headers=tuple(headers),
    )


def _mime_part(payload: object, *, depth: int = 0) -> GmailMimePart:
    if depth > 20:
        raise GmailRetrievalError(
            "Gmail MIME nesting exceeded its limit",
            category=GmailFailureCategory.RESPONSE_SIZE_BOUNDARY,
            stage=GmailFailureStage.BODY,
        )
    if not isinstance(payload, dict):
        raise GmailRetrievalError(
            "Gmail MIME payload was invalid",
            category=GmailFailureCategory.INVALID_PROVIDER_RESPONSE,
            stage=GmailFailureStage.BODY,
        )
    mime_type = payload.get("mimeType", "")
    filename = payload.get("filename", "")
    body = payload.get("body", {})
    parts = payload.get("parts", [])
    if not (
        isinstance(mime_type, str)
        and isinstance(filename, str)
        and isinstance(body, dict)
        and isinstance(parts, list)
    ):
        raise GmailRetrievalError(
            "Gmail MIME payload was invalid",
            category=GmailFailureCategory.INVALID_PROVIDER_RESPONSE,
            stage=GmailFailureStage.BODY,
        )
    body_data = body.get("data")
    attachment_id = body.get("attachmentId")
    if not (body_data is None or isinstance(body_data, str)) or not (
        attachment_id is None or isinstance(attachment_id, str)
    ):
        raise GmailRetrievalError(
            "Gmail MIME body was invalid",
            category=GmailFailureCategory.INVALID_PROVIDER_RESPONSE,
            stage=GmailFailureStage.BODY,
        )
    if len(parts) > 100:
        raise GmailRetrievalError(
            "Gmail MIME part count exceeded its limit",
            category=GmailFailureCategory.RESPONSE_SIZE_BOUNDARY,
            stage=GmailFailureStage.BODY,
        )
    return GmailMimePart(
        mime_type=mime_type,
        filename=filename,
        body_data=body_data,
        attachment_id=attachment_id,
        parts=tuple(_mime_part(part, depth=depth + 1) for part in parts),
    )
