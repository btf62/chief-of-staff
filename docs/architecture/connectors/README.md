# Connector Specifications

This directory is the authoritative location for external source integration
specifications. Create one specification per external source.

Each specification should eventually define source authority, supported data,
access boundaries, authorization, synchronization behavior, failure handling,
privacy constraints, and observability. Do not place credentials, secret
values, or private source content in a connector specification.

## Required specification content

Every connector specification must document:

- The authorized account and resource boundary
- OAuth application registration and ownership, when applicable
- Exact requested scopes and why each is required
- Whether each scope is read-only, sensitive, or restricted
- Provider-specific authorization-code, redirect, PKCE, and refresh behavior
- The Keychain entry and lookup-reference design without exposing secret
  values
- Authorization inspection, revocation, disconnection, and reauthorization
- Authentication-failure disclosure, distinct from empty source data
- Read-only interface behavior and contract tests proving no external writes
- Any narrowly bounded cache exception and its retention and deletion behavior

Cloud connectors follow the authentication and secret-storage boundary in
[ADR-0005](../../decisions/0005-adopt-oauth-and-macos-keychain.md). Exact scope
strings, provider endpoints, registrations, and resource boundaries remain
decisions for each future connector specification.

## Connector index

| Source | Specification | Status |
| --- | --- | --- |
| Approved repository context | [Repository context](repository-context.md) | Accepted and implemented |
| Google Calendar | [Google Calendar](google-calendar.md) | Accepted; bounded live trial complete and stopped |
| Todoist | [Todoist](todoist.md) | Accepted; bounded live trial and workday validation complete and stopped |
| Jira | [Jira](jira.md) | Accepted; mocked and synthetic phase complete, stopped at live-access gate |

## Planned specifications

| Source | Planned specification |
| --- | --- |
| Gmail | `gmail.md` |
| Asana | `asana.md` |
| Approved Google Drive content | `google-drive.md` |

Each future specification should implement the common read-only connector
contract in the [Architecture Overview](../overview.md#4-connector-model)
without selecting priorities or mutating its source. Approved local repository
context requires no remote credential when read from an approved local path;
future remote repository access requires a connector-specific decision.

## Related documents

- [Technical architecture](../overview.md)
- [Product requirements](../../product/requirements.md)
- [ADR-0004: SQLite and Bounded Local Data Lifecycle](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
- [ADR-0005: OAuth and macOS Keychain](../../decisions/0005-adopt-oauth-and-macos-keychain.md)
