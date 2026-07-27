"""OAuth and macOS Keychain boundaries."""

from chief_of_staff.auth.google_oauth import (
    GoogleInstalledAppOAuth,
    GoogleOAuthClientImporter,
    GoogleOAuthClientRegistrar,
    GoogleOAuthTokenClient,
    OAuthError,
    OAuthImportResult,
)
from chief_of_staff.auth.jira_oauth import (
    JIRA_OAUTH_AUDIENCE,
    JIRA_PROPOSED_READ_SCOPE,
    JiraLiveAccessNotApproved,
    JiraOAuthPreview,
    JiraOAuthStateMismatch,
    MockJiraOAuthBoundary,
)
from chief_of_staff.auth.keychain import (
    KeychainError,
    KeychainSecretNotFound,
    KeychainSecretReference,
    MacOSKeychain,
)
from chief_of_staff.auth.todoist_oauth import (
    TodoistAuthorizationResult,
    TodoistInstalledAppOAuth,
    TodoistOAuthClientRegistrar,
    TodoistOAuthError,
    TodoistOAuthTokenClient,
)

__all__ = (
    "JIRA_OAUTH_AUDIENCE",
    "JIRA_PROPOSED_READ_SCOPE",
    "GoogleInstalledAppOAuth",
    "GoogleOAuthClientImporter",
    "GoogleOAuthClientRegistrar",
    "GoogleOAuthTokenClient",
    "JiraLiveAccessNotApproved",
    "JiraOAuthPreview",
    "JiraOAuthStateMismatch",
    "KeychainError",
    "KeychainSecretNotFound",
    "KeychainSecretReference",
    "MacOSKeychain",
    "MockJiraOAuthBoundary",
    "OAuthError",
    "OAuthImportResult",
    "TodoistAuthorizationResult",
    "TodoistInstalledAppOAuth",
    "TodoistOAuthClientRegistrar",
    "TodoistOAuthError",
    "TodoistOAuthTokenClient",
)
