# Connector Specifications

This directory is the authoritative location for external source integration
specifications. Create one specification per external source.

Each specification should eventually define source authority, supported data,
access boundaries, authorization, synchronization behavior, failure handling,
privacy constraints, and observability. Do not place credentials, secret
values, or private source content in a connector specification.

## Required specification content

Every connector specification must document:

- Whether the provider supports one or multiple independently configured
  connector instances
- The stable instance ID, safe account alias, domain classification, authorized
  account reference, and resource boundary for each instance
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

Each retrieval operates on one connector instance. Connector runs, normalized
facts, source evidence, freshness, coverage, failure state, and briefing
provenance retain that instance identity. User-facing output uses the safe
alias rather than a full email address or provider account identifier.

Multiple instances of one provider must have independent OAuth grants,
Keychain entries, resource and scope boundaries, retrieval configuration,
enabled state, coverage, retention policy, and disconnection behavior.
Provider-level defaults may be shared only when they do not silently broaden
an instance. A failure, cache exception, sensitivity approval, or
configuration change for one instance never transfers to another.

Work and personal records remain distinct throughout retrieval, persistence,
inference, and presentation. Hosted-inference evidence packets do not combine
domains by default. Cross-account actors, threads, tasks, and commitments are
not merged automatically; a conservative association preserves every source
record and its separate provenance.

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
| Jira | [Jira](jira.md) | Accepted; bounded project and issue trials complete and stopped |
| Work Gmail | [Gmail](gmail.md) | Accepted MVP boundary; trial consumed without satisfying acceptance gate; live validation paused |

## Planned specifications

| Source | Planned specification |
| --- | --- |
| Personal Gmail | Deferred until after MVP validation; future instance remains within `gmail.md` |
| Approved Google Drive content | Deferred until after MVP validation; specification not yet created |

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
