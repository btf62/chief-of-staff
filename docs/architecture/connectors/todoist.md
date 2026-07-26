# Todoist Connector

- **Status:** Accepted
- **Version:** 2
- **Owner:** Brad
- **Last updated:** 2026-07-26

This specification defines the read-only Todoist connector and the approved
bounded live trial for Daily Briefing v1. The trial does not authorize
continuing live retrieval, Todoist mutation, another account, another
connector, scheduling, or hosted inference.

## Source authority

Todoist is authoritative for its personal tasks, project context, due dates,
provider priorities, labels, sections, assignment, and completion state.
Chief of Staff may interpret these facts alongside other approved sources, but
it does not replace Todoist or silently rewrite a source-owned fact.

Todoist priority is one input to downstream judgment, not the final Chief of
Staff priority. An overdue task is not automatically important, an undated
task is not automatically irrelevant, and a due date is not automatically an
external promise.

## Account and application boundary

The connector is restricted to the single Todoist account Brad explicitly
selects and confirms in the provider consent flow. The exact identity is stored
as non-secret private runtime authorization metadata under the opaque
`primary-user` alias and is not committed to Git. The connector verifies the
current-user response against that stored identity before task retrieval and
does not fall back to another account.

The OAuth application is:

- **Owner:** Brad
- **Application name:** `Chief of Staff (Local)`
- **Registration:** Todoist App Management Console confidential client
- **Callback:** `http://127.0.0.1:8765/oauth/callback`

The callback listener binds only to `127.0.0.1`, accepts only the configured
path, exists only during authorization, and validates a unique cryptographically
random `state`. A mismatch aborts the flow. If Todoist rejects the registered
callback, the implementation must stop rather than substitute a hosted
callback or dynamically registered client.

## OAuth scope and credentials

The only accepted scope is:

```text
data:read
```

Todoist documents this as read-only access to application data including
tasks, projects, labels, and filters. The provider scope is broader than this
application's endpoint boundary, but the application accepts that residual
limitation while exposing only the retrieval operations below.

The connector rejects a missing, broader, or additional scope.
`task:add`, `data:read_write`, `data:delete`, `project:delete`,
`backups:read`, and future write or delete scopes are not authorized.
Brad's personal API token is never used as a fallback.

Authorization follows
[ADR-0005](../../decisions/0005-adopt-oauth-and-macos-keychain.md):

- Todoist authorization-code flow in the system browser.
- Exact registered loopback callback and mandatory state validation.
- Authorization code exchanged only in application memory.
- Authenticated-user lookup before the grant is persisted.
- Client secret, access token, and refresh token stored only in macOS
  Keychain.
- Account, scope, expiry, refresh health, application ownership, and Keychain
  lookup references stored as non-secret SQLite metadata.

The selected confidential-client flow uses the App Management Console client
secret. Todoist's current documentation requires PKCE for public metadata
clients but does not document it as a requirement for this confidential
client flow, so this implementation does not invent unsupported PKCE
parameters. A future public-client flow requires a reviewed specification
change.

Keychain lookup accounts are:

```text
todoist:client-secret
todoist:access-token:primary-user
todoist:refresh-token:primary-user
```

Secret values never appear in SQLite, Git, configuration, logs, fixtures,
briefing output, or operational reports.

## Refresh, revocation, and reauthorization

New Todoist applications issue one-hour access tokens and rotated refresh
tokens by default. When a refresh token is issued, the trial performs one
refresh through the same exact-scope boundary and atomically replaces the
Keychain values. Refresh does not authorize scheduling or unattended use.

Credential inspection reports presence, expiry, scope, account identity, and
health without reading a secret into output. Provider rejection, expiry,
missing credentials, and scope mismatch are distinct from a legitimate empty
task result.

Disconnect supports provider revocation through Todoist's RFC 7009 endpoint,
then deletes the local access and refresh tokens and non-secret grant
metadata. It retains the client registration unless Brad explicitly removes
the connector configuration. Reauthorization repeats browser account
selection, state validation, identity confirmation, exact-scope validation,
and refresh testing.

## Read-only transport contract

The live transport exposes only these `GET` resources:

| Resource | Purpose |
| --- | --- |
| `/api/v1/user` | Confirm the authenticated account identity and timezone |
| `/api/v1/tasks/filter` | Retrieve the approved active-task subset |
| `/api/v1/projects/{project_id}` | Resolve a project referenced by a selected task |
| `/api/v1/sections/{section_id}` | Resolve a section referenced by a selected task |
| `/api/v1/labels` | Resolve label names and IDs for selected tasks |

The connector does not expose task creation, update, completion, reopening,
move, deletion, comments, project or section mutation, label mutation,
assignment mutation, or another external write.

Comments, completed-task history, filters, reminders, collaborators, workspace
administration, backups, activity, attachments, and other Todoist resources
are excluded.

## Bounded task retrieval

The server-side task filter is exactly:

```text
overdue | 15 days | p1 | p2 | assigned to: me
```

Todoist defines `15 days` as the current date plus the following fourteen
calendar days. The connector applies a second local check in Brad's configured
timezone and retains only active tasks meeting at least one condition:

- Overdue.
- Due today.
- Due within the next fourteen calendar days, inclusive.
- Provider priority `1` or `2`, where the current API defines `1` as highest.
- Assigned to the authenticated Brad account where assignment applies.

This filter avoids retrieving the complete active-task corpus. Every page uses
the same parameters, a maximum page size of 200, and an opaque cursor that is
never decoded or persisted.

## Context retrieval

After task selection, the connector:

- Retrieves each distinct referenced project by exact ID.
- Retrieves each distinct referenced section by exact ID.
- Retrieves the paginated personal-label collection only when a selected task
  has labels, because the task payload supplies label names rather than label
  IDs.
- Discards unused label records after matching.

No project, section, or label collection is cached. A missing context record
does not invent a name; the task remains usable with partial coverage.

## Normalization and provenance

Selected tasks preserve, when available:

- Todoist task ID and content/title.
- Due date or due datetime, timezone interpretation, and all-day status.
- Recurring status.
- Todoist provider priority.
- Resolved project ID and name.
- Resolved section ID and name.
- Resolved label IDs and names.
- Responsible-user ID when relevant.
- Parent-task relationship.
- Creation and update timestamps.
- Authoritative Todoist task link.
- Retrieval freshness and connector-run identity.

Descriptions are not needed for deterministic reduced mode and are neither
normalized nor persisted. A Todoist task alone never creates a People Waiting
on Brad item or an inferred human commitment. Provider priority remains a
transparent source signal in the deterministic explanation.

## Freshness, coverage, pagination, and failures

Coverage reports the approved filter, retrieval time, selected record count,
task and label page counts, source freshness when available, safe warnings,
and an error category.

- Complete pagination, including zero selected tasks: `complete`.
- Later-page or context failure after usable tasks: `partial`.
- Failure before any usable task result: `unavailable`.
- Missing, expired, revoked, rejected, wrong-account, or scope-mismatched
  authorization: `unauthorized`.
- Invalid task or context record: omit or leave unresolved and report
  `partial`.
- Repeated or empty cursor, or the 100-page safety limit: stop and report
  `partial`.
- HTTP 429: report a rate-limit category; do not broaden scope, switch
  endpoints, or retry aggressively.

Todoist does not publish a stable general REST-request quota in the referenced
API page. The connector therefore handles explicit 429 responses and provider
retry guidance without inventing a quota. It performs no background polling.

## Persistence and retention

The connector follows
[ADR-0004](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md):

- Raw HTTP bytes and parsed provider dictionaries exist only during the active
  request and are cleared after extraction.
- Full task pages and unused context remain transient.
- No source cache is enabled.
- SQLite stores selected normalized task facts, minimal resolved context,
  stable source IDs, authoritative links, freshness, evidence fingerprints,
  coverage, and connector-run metadata.
- Task descriptions, comments, completed history, unused context, cursors, raw
  payloads, authorization codes, and credentials are not persisted.
- Connector and briefing runs use the accepted 30-day retention class;
  deleting source evidence cascades to its normalized task facts and labels.

The private generated briefing is stored under ignored local state with
restricted filesystem permissions.

## Deterministic briefing behavior

Todoist task facts may support Today's Outcomes, Up Next, Important Tasks,
Looking Ahead, or a source-fact risk notice when deterministic evidence is
sufficient. Visible items retain Todoist provenance and authoritative links.
The same task is not repeated across ordinary sections without necessary new
context.

The connector does not claim that a person is waiting, convert a due date into
an external promise, or perform task mutations. On configured non-workdays,
ordinary task-driven sections remain suppressed while Todoist coverage is
still disclosed.

## Validation

Synthetic contract, integration, security, and lifecycle tests demonstrate:

- Exact `data:read` authorization with no write or delete scope.
- State mismatch rejection.
- Keychain-only client secret, access-token, and refresh-token storage.
- Refresh rotation, revocation, disconnection, and reauthorization
  boundaries.
- Distinct unauthorized, unavailable, partial, rate-limited, and empty
  results.
- Exact filter and local overdue/today/fourteen-day/priority/assignment checks.
- Cursor pagination and partial-page retention.
- Conservative project, section, and label resolution.
- Minimal source persistence and cascade deletion.
- Provider priority as a source signal.
- No People Waiting claim from a task alone.
- Duplicate-presentation limits, provenance, section order, and word budgets.
- Independent repository, Calendar, and Todoist coverage disclosure.
- Absence of reachable Todoist mutation methods.

One explicitly approved live trial combined approved repository context, one
bounded live primary-Calendar retrieval, and the bounded live Todoist
retrieval in deterministic reduced mode. It invoked no other connector or
hosted inference. The exact-scope, Keychain, refresh, endpoint, pagination,
lifecycle, provenance, failure, and presentation-budget checks passed.

## Bounded live-trial stop

Brad approved and completed one bounded trial under this specification. The
mandatory stop now applies.

No further Todoist retrieval, refresh, reauthorization, account change, scope
change, cache, mutation, or additional connector is authorized without a new
explicit approval.

## Official references

- [Todoist API v1 and OAuth](https://developer.todoist.com/api/v1/)
- [Todoist filter syntax](https://www.todoist.com/help/articles/introduction-to-filters-V98wIH)
- [ADR-0004: SQLite and Bounded Local Data Lifecycle](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
- [ADR-0005: OAuth and macOS Keychain](../../decisions/0005-adopt-oauth-and-macos-keychain.md)
