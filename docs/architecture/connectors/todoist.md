# Todoist Connector

- **Status:** Proposed
- **Version:** 1
- **Owner:** Brad
- **Last updated:** 2026-07-26

This specification defines the proposed read-only Todoist connector, its
implemented mock boundary, and the approval gate that must be satisfied before
any live authorization or retrieval. It does not authorize registering a
Todoist application, opening OAuth, storing credentials, or calling Todoist.

## Source authority

Todoist remains authoritative for task content, completion state, due dates,
provider priority, and other Todoist-owned facts. The connector retrieves a
bounded task subset and provenance only. It does not complete, reopen, create,
move, update, rank, or delete tasks, and it does not replace Todoist with an
application-owned task list.

The deterministic pipeline may use source-owned due dates and provider
priority as explicit inputs. It must not convert a Todoist task into an
external commitment without separate supporting evidence.

## Account and resource boundary

The proposed first live trial is restricted to:

- One Todoist account explicitly selected and confirmed by Brad during
  authorization. Its address or user identifier must remain absent from Git.
- Active tasks returned by the exact Todoist filter:

  ```text
  overdue | 7 days | p1
  ```

- The unified API v1 task-filter endpoint only.
- A page size of 200 and all opaque cursors followed until completion or a
  bounded failure.

The filter includes overdue tasks, tasks due within the next seven days, and
P1 tasks even when they are due later. It intentionally excludes an
unfiltered task corpus.

Projects, sections, labels, filters, comments, completed-task history,
attachments, activity, backups, and collaboration metadata are not retrieved
in the first trial. Project identifiers present on task payloads are ignored.
Adding project names or any other endpoint requires a reviewed specification
change and a new approval.

The proposed application registration is:

- **Owner:** Brad
- **Application name:** `Chief of Staff (Local)`
- **Redirect URI:** `http://127.0.0.1:8765/oauth/callback`
- **Client type:** App Management Console confidential client

The loopback listener binds only to `127.0.0.1` and exists only for the
authorization callback. If Todoist rejects this exact redirect, implementation
must stop; substituting a hosted callback, dynamic registration, or a public
metadata document requires review rather than silent fallback.

## OAuth scope

The only proposed scope is:

```text
data:read
```

Todoist documents `data:read` as read-only access to application data,
including tasks, projects, labels, and filters. No narrower task-only OAuth
scope is documented. The connector accepts this residual provider limitation
while restricting application code to the task-filter endpoint and exact
filter above.

The implementation must reject missing, broader, or additional scopes.
`task:add`, `data:read_write`, `data:delete`, `project:delete`, and
`backups:read` are not authorized.

Official references:

- [Todoist API v1 and OAuth](https://developer.todoist.com/api/v1/)
- [Todoist filter syntax](https://www.todoist.com/help/articles/introduction-to-filters-V98wIH)

## Authorization and credential boundary

Any approved live implementation must follow
[ADR-0005](../../decisions/0005-adopt-oauth-and-macos-keychain.md):

- Register one confidential Todoist OAuth application in the App Management
  Console, owned or explicitly approved by Brad.
- Use Todoist's authorization-code flow in the system browser.
- Generate a cryptographically random, unguessable state value and reject a
  missing or mismatched callback state.
- Use the exact `data:read` scope.
- Confirm the selected account identity before retrieval.
- Store the client secret, access token, and any refresh token only in macOS
  Keychain.
- Store only non-secret application, account-alias, granted-scope, expiry,
  health, and Keychain lookup metadata in SQLite.

Todoist also documents public-client flows that use PKCE through dynamic
registration or a publicly hosted OAuth Client ID Metadata Document. Those
flows require an additional HTTPS registration, metadata-hosting, and redirect
boundary that this local-first project has not established. They are not
selected for the first trial. The selected App Management Console
confidential-client flow uses a client secret held only in Keychain and
mandatory state validation. If Todoist confirms that PKCE is supported for
that registered client type, the implementation must also use `S256`;
otherwise it must not invent unsupported parameters. Moving to a public-client
flow requires a reviewed specification change before registration.

Todoist documents refresh tokens as the default for new applications. If a
refresh token is returned, it must remain in Keychain and must not enable
scheduled or unattended retrieval. Revocation, disconnection, and local
credential deletion behavior must be implemented and tested before live
authorization.

## Read-only transport contract

The currently implemented transport protocol exposes only `filter_tasks`. A
future live transport may use only `GET` against:

```text
https://api.todoist.com/api/v1/tasks/filter
```

Every request fixes the approved query, uses a maximum page size of 200, and
accepts only an opaque continuation cursor. The connector and transport expose
no task add, close, reopen, move, update, delete, project mutation, or other
write operation.

No live HTTP transport or OAuth implementation exists at this gate.

## Retrieved and normalized data

The first trial may read only the provider fields needed to normalize:

- Stable task ID.
- Task content as the display title.
- Provider priority.
- Due date or timezone-aware due time, when present.
- Task update time as freshness, when present.

The application constructs an authoritative Todoist task link from the stable
ID. Provider P1 through P4 values are preserved as source facts and mapped
deterministically to the application importance scale. A date-only deadline
remains all-day context rather than acquiring a fabricated time.

Descriptions, project and section names, labels, comments, attachments,
assignee or collaborator data, and other payload fields are ignored. Invalid
tasks are omitted with partial coverage rather than converted into unsupported
facts.

## Pagination and failure behavior

- All pages retrieved: `complete`, including a legitimate zero-task result.
- A later page fails after earlier tasks were retrieved: retain those tasks and
  report `partial`.
- The first page fails: `unavailable`.
- Authorization is missing, expired, revoked, or scope-mismatched:
  `unauthorized`, distinct from an empty result.
- A malformed task: omit it and report `partial`.
- A repeated cursor or the 100-page safety limit: stop and report `partial`.

Warnings disclose a safe failure category and page boundary without provider
response content. The connector does not broaden its filter, change accounts,
substitute cached tasks, or retry through a write-capable endpoint.

## Persistence, retention, and observability

No Todoist source cache is proposed. Raw provider pages and normalized task
facts remain transient pipeline inputs. The accepted local run graph may
store:

- Non-secret authorization and credential-health metadata.
- Connector status, approved filter, retrieval time, freshness, coverage,
  safe error category, and page count.
- Minimal source record identifiers, authoritative links, timestamps, and
  evidence fingerprints.
- Application-owned briefing-run metadata and private ignored output.

It must not store task content, descriptions, raw provider payloads, OAuth
codes, or tokens in SQLite. This lifecycle follows
[ADR-0004](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md).

## Implemented pre-authorization validation

Synthetic contract tests currently demonstrate:

- Exact `data:read` scope enforcement.
- Rejection of broader filters and additional scopes.
- Fixed filter query and page size.
- Cursor pagination and retention of prior pages after partial failure.
- Date-only and timezone-aware due normalization.
- Provider-priority mapping, source links, freshness, and coverage.
- Distinct unauthorized and empty results.
- Invalid-task disclosure.
- Absence of mutation operations.

Live OAuth, Keychain, HTTP, revocation, raw-payload lifecycle, and integrated
briefing tests remain required before a live trial can run.

## Live-access approval gate

Before implementation continues, Brad must explicitly approve:

1. The Todoist OAuth application's owner, name, and redirect URI.
2. The exact Todoist account selected during authorization.
3. The exact `data:read` scope and its unavoidable read access beyond the
   application's narrower endpoint and filter.
4. The fixed `overdue | 7 days | p1` task filter.
5. That the Todoist account timezone matches the application's configured
   timezone, because relative filters use account-local dates.
6. Keychain-only storage for the client secret, access token, and any refresh
   token, with non-secret metadata only in SQLite.
7. One on-demand trial with no hosted inference and no other live connector.

An approved first trial must retrieve only the fixed task subset, follow
pagination, keep raw responses transient, persist only the minimal lifecycle
data above, generate one private ignored deterministic briefing, and stop.
The trial report must omit task titles, account identifiers, token values, and
other private task content.

Until Brad gives that approval, no Todoist application registration, OAuth
authorization, Keychain mutation, live HTTP transport, or network retrieval is
authorized.
