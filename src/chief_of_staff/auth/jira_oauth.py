"""Non-live Atlassian OAuth planning and state-validation boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

JIRA_OAUTH_AUDIENCE: Final = "api.atlassian.com"
JIRA_PROPOSED_READ_SCOPE: Final = "read:jira-work"


class JiraLiveAccessNotApproved(RuntimeError):
    """Raised when code attempts to cross the Jira live-access gate."""


class JiraOAuthStateMismatch(RuntimeError):
    """Raised when a mocked callback does not match its pending state."""


@dataclass(frozen=True, slots=True)
class JiraOAuthPreview:
    """Inspectable non-secret plan; it cannot open or exchange an OAuth flow."""

    audience: str
    requested_scopes: tuple[str, ...]
    state: str
    resource_restricted: bool
    live_authorization_enabled: bool = False


@dataclass(slots=True)
class MockJiraOAuthBoundary:
    """Exercise OAuth state handling without credentials, URLs, or network I/O."""

    state_factory: Callable[[], str]
    _pending_state: str | None = field(default=None, init=False, repr=False)

    def prepare_preview(
        self,
        *,
        requested_scopes: tuple[str, ...] = (JIRA_PROPOSED_READ_SCOPE,),
    ) -> JiraOAuthPreview:
        """Create a non-live, resource-restricted authorization preview."""

        if not requested_scopes or any(not scope.strip() for scope in requested_scopes):
            raise ValueError("at least one proposed Jira scope is required")
        state = self.state_factory()
        if not state.strip():
            raise ValueError("OAuth state must not be empty")
        self._pending_state = state
        return JiraOAuthPreview(
            audience=JIRA_OAUTH_AUDIENCE,
            requested_scopes=requested_scopes,
            state=state,
            resource_restricted=True,
        )

    def validate_mock_callback(self, *, returned_state: str) -> None:
        """Validate and consume state without accepting an authorization code."""

        if self._pending_state is None or returned_state != self._pending_state:
            raise JiraOAuthStateMismatch("mocked Jira OAuth state did not match")
        self._pending_state = None

    def exchange_authorization_code(self) -> None:
        """Reject token exchange until Brad approves a bounded live trial."""

        raise JiraLiveAccessNotApproved(
            "Jira OAuth token exchange is disabled pending live-access approval"
        )
