# ADR-0005: Adopt OAuth and macOS Keychain for Connector Credentials

- **Status:** Accepted
- **Date:** 2026-07-25
- **Owners:** Brad

## Context

[Daily Briefing v1](../product/features/daily-briefing-v1.md) requires
read-only access to:

- Google Calendar
- Gmail
- Approved Google Drive content
- Todoist
- Jira
- Asana
- Approved local repository context

These sources contain private personal, organizational, pastoral, and
third-party information. The application therefore needs a consistent
authentication model that:

- Keeps passwords out of the application
- Limits access to approved sources and scopes
- Securely retains refresh or long-lived tokens
- Supports revocation and reauthorization
- Prevents credentials from entering Git, SQLite, logs, backups, or briefing
  output
- Enforces the product's read-only external boundary

This decision applies within the local-first Mac deployment established by
[ADR-0003](0003-adopt-local-first-python-runtime.md) and the separation of
secret values from application data established by
[ADR-0004](0004-adopt-sqlite-and-bounded-local-data-lifecycle.md).

## Decision drivers

- Protect Brad's credentials and the private information available through
  them.
- Use provider-supported consent, scope, refresh, revocation, and
  reauthorization mechanisms.
- Apply least privilege independently to each connector and account.
- Enforce read-only behavior even when provider scopes are imperfect.
- Keep credential compromise separate from application-data compromise.
- Support future unattended briefing runs without normalizing long-lived
  personal tokens.

## Options considered

### Option 1: Personal access tokens and API tokens

Personal tokens can simplify setup for a one-user script. They were not
selected as the normal production method because they are often long-lived,
broader than required, harder to scope and rotate, less visible through a
consent experience, and a poorer foundation for a durable application.

### Option 2: Credentials stored in SQLite

Storing credentials with application data would simplify lookup and backup. It
was rejected because application-data compromise and credential compromise
should remain separate, and ADR-0004 explicitly excludes tokens and
credentials from SQLite.

### Option 3: Credentials stored in `.env` files

Environment files can be useful for temporary development injection. They were
rejected as the persistent production secret store because they can be copied,
backed up, committed accidentally, or exposed through diagnostics.

### Option 4: Application-managed encrypted credential file

An encrypted file could provide a portable application-owned secret store. It
was rejected for Version 1 because macOS already provides an operating-system-
backed secret store, while custom secret encryption would add key-management
complexity.

### Option 5: Service accounts or delegated organizational access

Service accounts and delegated access could support organization-wide
retrieval and centralized administration. They were rejected for Version 1
because the product acts on Brad's behalf as a single user and should not
introduce organization-wide authority.

### Option 6: One shared broad Google authorization

A broad shared authorization would reduce the number of consent operations. It
was rejected because Calendar, Gmail, and Drive have different sensitivity,
approval, and source-boundary concerns. Authorization must remain inspectable
at the connector and scope level.

## Decision

### OAuth is the default connector authorization mechanism

Cloud connectors use provider-supported OAuth 2.0 authorization-code flows
whenever available.

For Daily Briefing v1:

- Google Workspace APIs use Google OAuth for an installed or local
  application.
- Todoist uses OAuth rather than a personal API token.
- Jira Cloud uses OAuth 2.0 three-legged authorization.
- Asana uses OAuth rather than a personal access token.
- Approved local repository context requires no remote credential when read
  directly from an approved local path.

The application does not collect account passwords or use password-based
authentication. API tokens, personal access tokens, basic authentication,
service accounts, and domain-wide delegation are not normal production
authentication methods.

A connector may use a non-OAuth credential only when:

1. The provider does not offer a suitable OAuth flow.
2. The connector specification documents the need.
3. The credential's permissions and lifetime are understood.
4. Brad explicitly approves the exception.
5. A separate decision records the exception when it materially expands risk.

### Provider-supported authorization-code flows

Authorization must:

- Open the provider's authorization page in the system browser.
- Use a provider-supported local callback or redirect flow.
- Validate OAuth `state`.
- Use Proof Key for Code Exchange (PKCE) where supported or required.
- Exchange authorization codes through the application rather than asking
  Brad to copy tokens manually.
- Request offline access or refresh capability only when future briefing runs
  require it.

Embedded-browser login, password collection, implicit grants, and obsolete
out-of-band flows are prohibited unless a provider currently requires a
documented exception. Each flow follows the provider's current official
guidance rather than assuming one generic OAuth implementation fits every
provider.

### Least privilege per connector

Each [connector specification](../architecture/connectors/README.md) must
define:

- The account being authorized
- The specific resource boundary
- The exact scopes requested
- Why each scope is required
- Whether each scope is read-only
- Whether the provider classifies a scope as sensitive or restricted
- How access can be reviewed and revoked

Connectors request only the minimum scopes required for implemented retrieval
behavior. The intended direction is:

- Calendar event read access rather than calendar modification.
- Gmail read access without sending, drafting, deleting, labeling, or
  modifying messages.
- Todoist `data:read` rather than read/write or delete permissions.
- Jira issue, project, and user read scopes without write or administrative
  scopes.
- Asana task, project, workspace, and identity read scopes without write or
  delete scopes.
- Google Drive access limited to approved content using the narrowest
  practical scope and content boundary.

Exact provider scopes belong in connector specifications, not this ADR. Broad,
sensitive, or restricted scopes require explicit review before use. Scope
expansion cannot occur silently and may require renewed user consent.

### Read-only access in depth

OAuth scopes are the first read-only control, not the only control. Every
connector must:

- Implement only retrieval operations.
- Reject write, delete, send, comment, or other mutation operations.
- Expose a read-only connector interface.
- Include contract tests proving that no external writes occur.
- Avoid a broader endpoint merely because the credential permits it.

When a provider cannot offer genuinely read-only scopes, the connector
specification must disclose the limitation, and code and contract tests must
enforce read-only behavior before the connector is enabled.

### macOS Keychain secret storage

macOS Keychain is the accepted secret-storage boundary for the initial Mac
deployment. Store the following in Keychain when applicable:

- OAuth refresh tokens
- OAuth access tokens when persistence is required
- Client secrets
- Personal or API tokens approved through a future exception
- Other connector secrets

Keychain access occurs through a narrow, application-owned secret-store
abstraction. A Python integration such as the system-keyring interface may be
selected during implementation, but application modules must not access
credential files directly.

Use separate Keychain entries by application, provider, account, environment,
and credential purpose.

Credentials and tokens must not be stored in:

- SQLite
- Git
- Tracked configuration
- Markdown documentation
- Source code
- Logs
- Briefing output
- Fixtures
- Analytics
- Crash reports
- Application-managed backups

### Client identifiers and client secrets

Provider client identifiers may be stored in non-secret local configuration
when the provider treats them as public identifiers. Provider client secrets
are secrets and must be stored in Keychain or provisioned through an equally
protected local mechanism.

No client secret may be committed to the repository. When a provider's native-
application model cannot keep a client secret confidential, follow that
provider's installed-application guidance rather than treating an embedded
value as secret.

### Non-secret authorization metadata

SQLite may store non-secret credential metadata, including:

- Provider name
- Account identifier
- Granted scopes
- Authorization status
- Token expiry time
- Last successful refresh
- Last successful connector use
- Credential health
- Keychain lookup reference

SQLite must not store token values, authorization codes, client secrets, or
passwords. A Keychain reference must not expose secret material.

### Expiration, refresh, revocation, and reauthorization

Connectors must:

- Refresh expiring access tokens through the provider-supported process.
- Update rotated refresh tokens safely.
- Detect revoked, expired, missing, or invalid credentials.
- Report authentication failure separately from source-data absence.
- Provide a clear reauthorization path.

A connector never falls back automatically to broader scopes, a different
account, a personal token, cached private source content, or another
credential. Authentication failure normally produces a partial-coverage
briefing with a clear disclosure rather than failing silently.

### Credential inspection and disconnection

Brad must be able to inspect:

- Which providers are connected
- Which account is connected
- Which scopes were granted
- When authorization last succeeded
- Whether refresh is healthy
- How to revoke or reconnect access

Disconnecting a connector must:

- Remove its stored credentials from Keychain.
- Disable future retrieval.
- Update local authorization metadata.
- Preserve or delete existing non-secret local state according to ADR-0004.

Disconnecting does not modify source data.

### Authorization-flow and log protection

Authorization implementation must:

- Validate redirect state.
- Bind callbacks to the initiating local session.
- Use short-lived authorization codes only once.
- Avoid placing tokens in URLs or logs.
- Redact authorization headers and token-shaped values.
- Avoid logging provider responses containing secret material.
- Expose the local callback only for the duration and scope required.

The local web interface must not expose credential-management endpoints beyond
the accepted local security boundary.

### Development and test credentials

Development uses synthetic connector responses, mocks, provider sandbox or
test accounts where available, or explicitly approved access-controlled
accounts. Production credentials and copied production tokens never become
test fixtures.

Environment variables may be used only as an explicitly documented temporary
development injection mechanism. They are not the normal persistent secret
store and must never be written into committed `.env` files, shell history,
logs, or test output.

### Provider-registration ownership

OAuth applications used for Version 1 must be registered under accounts
controlled by Brad or the appropriate Northridge authority. The registration
owner, consent-screen identity, redirect URIs, approved scopes, and revocation
procedure must be documented outside secret values.

Version 1 remains a private single-user application. Distribution to other
users requires review of provider policies, app verification, consent-screen
requirements, organizational approval, and potentially a new ADR.

## Provider-specific direction

These directions do not finalize endpoint or scope lists.

### Google Calendar, Gmail, and Drive

- Use an installed or local-application OAuth flow.
- Use the system browser and a provider-supported local redirect.
- Request separate minimum scopes for each enabled Google connector.
- Treat Gmail and broad Drive access as especially sensitive.
- Do not assume Calendar approval implies Gmail or Drive approval.
- Document consent-screen, test-user, organizational, sensitive-scope,
  restricted-scope, and verification implications in the connector
  specifications.

### Todoist

- Use OAuth with read-only data access.
- Do not use Brad's personal API token for normal Version 1 operation.
- Do not request task creation, read/write, deletion, project deletion, or
  backup access.

### Jira Cloud

- Use OAuth 2.0 three-legged authorization.
- Prefer a resource- or site-restricted grant where supported and appropriate.
- Request only the read scopes needed by implemented Jira queries.
- Do not use Jira API tokens or basic authentication for normal Version 1
  operation.
- Request refresh or offline capability only as needed for unattended future
  runs.

### Asana

- Use the authorization-code OAuth flow.
- Request only the required read scopes.
- Do not use a personal access token for normal Version 1 operation.
- Store the client secret and refresh token in Keychain.
- Do not request task, project, comment, or other write or delete permissions.

### Local repository context

- Read only from explicitly approved local repository paths.
- Do not require a GitHub token when the local checkout contains the approved
  content.
- Require a connector-specific decision and secure credential entry if remote
  repository authentication becomes necessary.

## Consequences

### Positive

- Passwords never enter the application.
- Tokens are isolated from product data.
- Provider consent and revocation mechanisms remain available.
- Read-only and least-privilege intent is visible and testable.
- Credential management fits the accepted local-first Mac deployment.
- Future scheduled execution can use refresh tokens without manual login each
  morning.
- Connector failures can be isolated and disclosed.

### Negative

- OAuth application registration and provider setup add initial complexity.
- Some providers require client secrets even for a local single-user
  application.
- Sensitive or restricted Google scopes may require additional review or
  organizational approval.
- Token refresh and rotation require careful implementation.
- Authorization behavior differs among providers.
- Reauthorization may occasionally interrupt briefing coverage.
- A future hosted or multi-user product requires reassessment.

### Follow-up

- Define exact scope strings, account and resource boundaries, registration
  ownership, and provider behavior in each connector specification.
- Define the Keychain lookup and entry design for each connector without
  exposing secret values.
- Document authorization, inspection, revocation, disconnection, and
  reauthorization procedures before enabling a connector.
- Test credential failure separately from empty or unavailable source data.

## Guardrails

- Never broaden a scope merely to simplify implementation.
- Never silently reuse credentials for a different account, source, or
  environment.
- Never store credentials in SQLite or Git.
- Never display token values after initial provisioning.
- Never log authorization headers, codes, secrets, or complete token
  responses.
- Never treat OAuth authorization as permission to retain all accessible data.
- Never let authentication failure appear as an empty source.
- Never introduce write scopes without a separately approved product
  requirement and security review.

## Related records and documents

- [ADR-0003: Adopt a Local-First Python Runtime](0003-adopt-local-first-python-runtime.md)
- [ADR-0004: SQLite and Bounded Local Data Lifecycle](0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
- [Constitution](../foundations/constitution.md)
- [Daily Briefing v1](../product/features/daily-briefing-v1.md)
- [Architecture Overview](../architecture/overview.md)
- [Connector specifications](../architecture/connectors/README.md)
