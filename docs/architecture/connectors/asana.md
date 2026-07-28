# Asana Connector

- **Status:** Accepted
- **Version:** 3
- **Owner:** Brad
- **Last updated:** 2026-07-28

This specification defines the read-only Asana connector through bounded
workspace discovery and one explicitly approved organization-workspace
project discovery. It prepares a synthetic task contract for later review, but
it does not authorize or implement live task retrieval. It does not authorize
another discovery, a different account, broader scopes, hosted inference, or
an external mutation.

## Source authority

Asana is authoritative for Asana-managed work. A later approved task boundary
may preserve, when available and necessary:

- Workspace, task identity, and task name
- Completion state and assignee
- Due and start dates or datetimes
- Creation and modification timestamps
- Resource subtype and parent task
- Approved project and section membership
- Dependency and dependent references
- Approved tags
- The authoritative Asana permalink

Chief of Staff may interpret those facts with other approved sources, but it
does not replace Asana or silently rewrite source-owned facts. Descriptions,
comments or stories, attachments, followers, likes, custom fields, time
tracking, portfolios, goals, administrative information, and other
unapproved fields are excluded.

## Connector-instance boundary

The initial application-owned instance is `asana:primary`, with the safe alias
`Asana` and work-domain classification. Its account authorization, Keychain
entries, scopes, resource selection, retrieval configuration, coverage,
freshness, and retention policy are independent from every other connector
instance.

SQLite may retain a non-secret provider account reference and the Keychain
lookup references required to operate the instance. Private account identity
must not appear in public reports or briefing provenance; presentation uses
the safe alias.

## Current implementation boundary

The implemented boundary contains:

- A synthetic-only assigned-task connector contract with no live task
  transport.
- Mocked authorization, workspace, project, task, pagination, failure, and
  partial-coverage behavior.
- Provider-neutral task normalization for the approved future field model.
- A live transport exposing only workspace and active-project discovery, with
  a project-only service that cannot list workspaces.
- Exact-scope OAuth authorization code handling with random `state`, PKCE
  `S256`, token introspection, refresh support, revocation, and reauthorization.
- Keychain-only client-secret, access-token, and refresh-token storage.
- Non-secret SQLite authorization, health, connector-run, minimal source
  reference, discovered-workspace, freshness, and coverage metadata.
- A private ignored selection report containing the discovery catalog.

The first explicitly authorized live trial completed with three accessible
workspaces and stopped. Brad then approved the organization workspace using
the GID already recorded in the private discovery report. The bounded
project-only gate is restricted to that local resource binding and cannot
repeat workspace discovery. No task operation is authorized.

## OAuth application and authorization

The trial uses the private, workspace-restricted OAuth application
`Chief of Staff (Local) — Asana`. Brad is the sole current owner; no separate
Northridge administrator ownership was confirmed. The application is not
published in Asana's public app directory. Provider requirements made the app
available only to the one workspace Brad explicitly confirmed for
distribution.

The registered callback is:

```text
https://127.0.0.1:8768/oauth/callback
```

The local process uses an ephemeral loopback HTTPS listener and a temporary
self-signed certificate. Certificate and private-key files use mode `0600`
inside a temporary directory and are deleted after the callback. The
authorization request carries an unguessable session-bound `state`, a unique
PKCE verifier, and its `S256` challenge. The callback must match the registered
redirect and initiating state before the code is exchanged.

Asana's authorization-code response supplies minimal account identity without
requiring an OpenID Connect or user scope. Brad must explicitly confirm the
account shown in the browser, and the returned account email must match that
confirmation before credentials are stored.

The exact discovery scopes are:

```text
workspaces:read projects:read
```

The access token is introspected after exchange; its active status, bearer
type, and exact scope set must match the approved boundary. The application
must not enable full permissions or request tasks, users, sections, tags,
stories, attachments, OpenID Connect, write, delete, or administrative scopes.

Asana documents one-hour access tokens and a long-lived refresh token for this
flow. The client secret and both token values are stored only in macOS
Keychain. SQLite contains only non-secret app ownership, account reference,
scope, expiry, credential and refresh health, and Keychain lookup references.
Disconnect revokes the refresh grant and deletes only this instance's tokens.
A personal access token is never an allowed fallback.

See Asana's official [OAuth guide](https://developers.asana.com/docs/oauth) and
[scope reference](https://developers.asana.com/docs/oauth-scopes).

## Bounded workspace discovery

The first operation is exactly:

```text
GET /api/1.0/workspaces
```

Every request uses a page size of 100 and requests only `gid`, `name`, and
`is_organization`. Pagination follows only the provider-returned opaque offset,
preserves the same fields and limit, rejects repeated or empty offsets, and
stops after 20 pages rather than widening access. Identical duplicate GIDs are
deduplicated; conflicting duplicates stop discovery.

If discovery returns anything other than exactly one workspace, the connector
stops before projects. More than one workspace requires Brad to choose from
the private report; no name-based inference is allowed. An empty successful
response remains distinct from authorization, permission, rate-limit,
pagination, and retrieval failures.

See the official
[workspace-list endpoint](https://developers.asana.com/reference/getworkspaces)
and [pagination guide](https://developers.asana.com/docs/pagination).

## Bounded active-project discovery

After Brad explicitly selects one organization workspace from the private
workspace report, the connector binds the instance to that workspace GID and
calls only:

```text
GET /api/1.0/workspaces/{workspace_gid}/projects
```

Every page sets `archived=false`, uses a limit of 100, and requests only:

```text
gid,name,archived,public,permalink_url
```

The selected-workspace gate does not call the workspace-list endpoint and
rejects any workspace other than the explicitly approved organization alias.
The actual workspace GID remains private local metadata rather than committed
configuration.

The same offset safeguards and 20-page ceiling apply. An archived project,
conflicting duplicate GID, ambiguous permission, timeout, invalid response,
rate limit, or excessive pagination stops the trial rather than changing
endpoints or broadening retrieval. Descriptions, members, owners, teams,
counts, tasks, sections, custom fields, portfolios, goals, templates, status
updates, and other project configuration are not retrieved. Provider-offset
pagination is complete when no next offset remains, but concurrent project
changes may still affect catalog completeness.

See the official
[workspace-project endpoint](https://developers.asana.com/reference/getprojectsforworkspace).

## Private selection report

Each discovery gate writes one ignored mode-`0600` Markdown report under
`.local/asana/`. Workspace and project names, GIDs, visibility, archived state,
and authoritative project links exist only in private reports and transient
memory, never in chat or Git. The project-selection report asks Brad to
approve:

- One or more projects
- Whether all assigned incomplete tasks in the approved workspace are allowed
- Whether tasks with no project are allowed
- Whether My Tasks is included
- Whether another approved source may nominate explicit task GIDs
- Whether project or section membership is needed for briefing context
- Whether any selected project has explicit priority over another

It also presents assigned-workspace, approved-project, and hybrid
task-retrieval options without choosing among them.

Discovery does not imply approval. The complete project catalog, raw provider
responses, and pagination offsets are not persisted. Transient response data,
OAuth code, PKCE verifier, offsets, and temporary TLS material are released
after use.

## Prepared task contract — not authorized live

The narrowest practical future task operation is:

```text
GET /api/1.0/tasks
```

The proposal uses one explicitly approved workspace, `assignee=me`,
provider-supported incomplete-task semantics through `completed_since`, a
limit of 100, and stable provider-offset pagination. Proposed later scopes
are `tasks:read`, `workspaces:read`, and `projects:read`;
`project_sections:read` is added only if Brad approves section membership as a
requirement.

The proposed task fields are:

```text
gid
name
completed
assignee.gid
due_on
due_at
start_on
start_at
created_at
modified_at
resource_subtype
parent.gid
dependencies
dependents
memberships.project.gid
permalink_url
```

Section membership and approved tags require a separately justified field and
scope review. Notes and descriptions remain excluded.

Asana's
[standard task-list endpoint](https://developers.asana.com/reference/gettasks)
is preferred over
[workspace task search](https://developers.asana.com/reference/searchtasksforworkspace).
Workspace search is premium-only, eventually consistent, and does not provide
normal stable pagination, so it is unsuitable as the default v1 retrieval
path without a later product requirement.

No live task endpoint, task count, user endpoint, section endpoint, or search
endpoint is authorized by this specification's discovery gate.

## Read-only enforcement

The synthetic task transport exposes `list_tasks`; the live discovery
transport exposes only `list_workspaces` and `list_projects`. Neither surface
contains creation, update, completion, reopening, deletion, comment, story,
assignment, project, section, tag, dependency, follower, attachment,
custom-field, or other mutation methods.

Tests assert the absence of live task and mutation operations. Provider host,
paths, methods, fields, scopes, page limits, workspace rule, and
`archived=false` query are fixed in code.

## Coverage and failure behavior

Coverage remains connector-instance specific. Successful empty workspace or
project results are valid complete coverage. Missing authorization, expired
credentials, identity mismatch, scope mismatch, provider authentication,
permission denial, rate limiting, invalid pagination, and retrieval failure
are distinct states.

The synthetic future task connector retains successful pages and reports
partial coverage when a later page fails. It never treats missing or partial
data as an empty authoritative source.

## Persistence and lifecycle

Permitted durable data is limited to:

- OAuth application ownership and non-secret registration metadata
- Account alias and opaque account reference
- Exact scope, expiry, authorization status, credential and refresh health
- Keychain lookup references
- One connector run and minimized source-evidence reference
- One explicitly approved organization-workspace GID and safe resource
  reference
- Coverage and freshness metadata
- The ignored private selection report

The complete workspace or project catalog, names, raw JSON, offsets, tokens,
client secret, authorization code, PKCE verifier, and temporary certificate
material are excluded from SQLite and Git. The private report is deleted
through the local-state lifecycle when it is no longer required.

## Completed workspace-discovery checkpoint

The one approved live trial:

- API-verified the account Brad explicitly confirmed.
- Issued an access token and refresh token through the authorization-code
  flow and stored both only in macOS Keychain.
- Introspected an active bearer token with exactly
  `workspaces:read projects:read`.
- Retrieved one workspace page and found three accessible workspaces.
- Wrote the private mode-`0600` selection report under `.local/asana/`.
- Stopped before the project endpoint because workspace selection was
  ambiguous.
- Persisted authorization health, one connector run, one catalog-level source
  reference, and connector coverage and freshness.
- Persisted no workspace selection, complete workspace catalog, project
  catalog, raw response, or offset.
- Released transient provider responses, authorization code, PKCE material,
  offsets, clipboard transfer, and temporary TLS files.
- Called no project, task, user, hosted-inference, other-connector, or mutation
  operation.

Brad selected one organization workspace from this private report. That
selection authorizes one bounded project-only discovery but does not authorize
another OAuth flow, workspace retrieval, task retrieval, or a different
workspace.

## Approved project-discovery checkpoint

The approved project-only gate:

- Uses the existing work-account connector instance and exact
  `workspaces:read projects:read` grant.
- Resolves the approved workspace GID from the prior private report and stores
  it as the instance's explicit local resource boundary.
- Calls only the active-project endpoint for that GID with `archived=false`
  and the five approved project fields.
- Follows only provider-returned offsets and stops on timeout, permission
  ambiguity, conflicting duplicates, invalid pagination, or the page ceiling.
- Writes the complete catalog only to a new private mode-`0600` report.
- Persists only the approved workspace boundary, connector-run, source
  reference, coverage, freshness, and credential-use metadata.
- Calls no workspace-list, task, user, section, search, hosted-inference,
  other-connector, or mutation operation.

This checkpoint must stop for Brad to select a later task-retrieval boundary.

## Acceptance

The mocked contract is accepted when formatting, linting, strict type checks,
unit and integration tests, Markdown validation, credential and private-data
checks, lifecycle audit, and wheel packaging pass.

The bounded project live gate is complete only after:

1. The private app ownership and exact registered scopes are confirmed.
2. The browser account is explicitly confirmed and API-verified.
3. Token introspection reports exactly the approved discovery scopes.
4. The instance is bound to the previously discovered, explicitly approved
   organization workspace GID.
5. No workspace-list endpoint is called.
6. Active-project pagination completes without endpoint substitution.
7. The private report is mode `0600`.
8. No task, user, hosted-inference, other-connector, or mutation operation is
   called.
9. Persisted and transient data satisfy the lifecycle boundary.
10. The complete repository validation passes.
11. Execution stops for Brad's explicit task-boundary selection.

## Related documents

- [Connector specifications](README.md)
- [Architecture Overview](../overview.md)
- [Daily Briefing v1](../../product/features/daily-briefing-v1.md)
- [ADR-0004: SQLite and Bounded Local Data Lifecycle](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
- [ADR-0005: OAuth and macOS Keychain](../../decisions/0005-adopt-oauth-and-macos-keychain.md)
