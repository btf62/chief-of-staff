# Todoist Connector

- **Status:** Accepted
- **Version:** 5
- **Owner:** Brad
- **Last updated:** 2026-07-27

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
| `/api/v1/tasks` | Retrieve the complete active-task collection |
| `/api/v1/tasks/filter` | Verify live P1/P2 response semantics before selection |
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

The task endpoint is exactly:

```text
GET /api/v1/tasks
```

It returns the complete active-task collection. The connector follows each
opaque `next_cursor` until the provider returns `null`, keeps the page size and
all other request parameters identical, and deduplicates by stable Todoist task
ID if concurrent source changes repeat a record across pages. Cursors are never
decoded or persisted. Pagination across more than one page is reported as
complete when every cursor succeeds, while also disclosing that concurrent
source changes cannot be excluded.

Every active task remains transient until the connector applies independent
local qualification rules in Brad's configured timezone. It retains only
active tasks meeting at least one condition:

- Overdue.
- Due today.
- Due within the next fourteen calendar days, inclusive.
- Provider priority P1 or P2.
- Explicitly linked to an approved active priority in local configuration.
- Assigned to the authenticated Brad account in a shared project or workspace
  where assignment meaningfully distinguishes ownership.

Assignment to Brad is not by itself a selection signal in a personal project.
An undated task is selected only when it is P1 or P2, explicitly linked to an
approved active priority, or assigned under the distinguishing shared-project
rule.

The complete active corpus is not persisted. Completed history remains
excluded.

### Endpoint-specific priority semantics

For `GET /api/v1/tasks`, the returned `priority` value is an integer from 1
through 4. Higher numbers are more urgent:

| Todoist label | API value | Meaning |
| --- | ---: | --- |
| P1 | 4 | Very urgent |
| P2 | 3 | Urgent |
| P3 | 2 | Important |
| P4 | 1 | Natural/default |

This mapping follows Todoist's current unified API v1 task documentation. The
validation gate also queries the read-only filter endpoint with `p1` and `p2`
before applying priority selection; the live response must return only values
4 and 3 respectively. Any mismatch stops the run before priority is used.

Todoist's deprecated REST v1 and REST v2 task documentation uses the same
1-normal-to-4-urgent API range. The older Sync API also stores the numeric API
priority in this direction. The apparent inversion is between Todoist's
user-facing ordinal labels and the API integer: user-facing P1 is API value 4,
not API value 1. The connector does not translate according to a guessed or
endpoint-independent convention.

The current unified documentation also contains a generated create/update
request-field description that says value 1 is highest. That write-schema text
is internally inconsistent with the documented task object and is not the
response contract used by this read-only connector. The live P1/P2 probe
matched the task-object contract. If the observed `GET /api/v1/tasks` response
or filter semantics ever cease to do so, the connector must stop before using
priority for selection.

## Context retrieval

To apply and explain task selection, the connector:

- Retrieves each distinct referenced project by exact ID, including project
  sharing and assignment-capability flags needed to evaluate assignment-only
  candidates.
- Discards assignment-only candidates whose project context does not prove
  that assignment meaningfully distinguishes ownership.
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

Coverage reports the approved endpoint, retrieval time, task and label page
counts, source freshness when available, safe warnings, and an error category.
Counts use distinct labels for:

- Active tasks retrieved from the complete collection.
- Tasks selected by the application boundary.
- Selected tasks persisted as minimized local facts.
- Persisted tasks considered as date-specific daily candidates.
- Tasks displayed in the briefing.
- Projects, sections, and labels retrieved for context.
- Distinct projects, sections, and labels persisted for selected tasks.

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
- After a complete retrieval and boundary re-evaluation, the current selected
  task snapshot replaces superseded snapshots and tasks that no longer qualify
  are deleted. Reconciliation reports previous, new, retained, removed, and
  dependency-preserved identities separately. Partial retrieval never drives
  absence-based cleanup. Evidence needed by a prior correction or disposition
  is retained so the correction loop remains effective.

The private generated briefing is stored under ignored local state with
restricted filesystem permissions.

## Deterministic briefing behavior

Todoist task facts may support Today's Outcomes, Up Next, Important Tasks,
Looking Ahead, or a source-fact risk notice when deterministic evidence is
sufficient. Visible items retain Todoist provenance and authoritative links.
The same task is not repeated across ordinary sections without necessary new
context.

The selected and persisted pool is deliberately broader than one day's
presentation. A deterministic daily-candidate gate narrows that pool for the
briefing date, and section budgets narrow it again for display. This
presentation gate never changes source selection or persistence.

### Todoist planning confidence

The connector retains a simple, explainable relative-ranking confidence
assessment. It calculates:

- Complete active-task count.
- Overdue count and percentage.
- P1/P2 count and percentage.
- Count that is both overdue and P1/P2.

Relative-ranking confidence is `degraded` when either the overdue percentage
or the P1/P2 percentage exceeds 25 percent. These two module-level thresholds
are configurable implementation constants and must remain documented and
covered by tests. They do not form a composite score and do not characterize
Brad's task-management practice as healthy, unhealthy, or failing.

When confidence is degraded, an ordinary-workday task becomes a daily
candidate only through stronger current evidence:

- Due today or within the next seven days.
- Direct dependency on today's Calendar.
- Explicit linkage to an approved active priority.
- Explicit commitment or preparation evidence.
- A compatible multi-signal combination, such as P1/P2 plus a reliable source
  update on the briefing date or preceding calendar day.

An overdue task requires another current signal. Overdue status alone is
insufficient. P1 or P2 alone is also insufficient while confidence is
degraded. A source update is not inferred when the endpoint omits its
timestamp, and the one-day recency window is an intentionally narrow
date-based signal rather than a general task-quality judgment.

When confidence is not degraded, Todoist P1/P2 may remain a daily-candidate
signal, but section budgets and current-date rules still prevent arbitrary
backlog filling.

Up Next admits ordinary future tasks only through the fourteen-day horizon. A
more distant task requires explicit preparation or a direct Calendar
dependency that makes work necessary now. Looking Ahead prioritizes Calendar
and explicit preparation rather than serving as overflow for distant tasks.

Visible titles remove Todoist label-style control tokens without changing the
persisted source title. All-day due values render as dates, and actual times
appear only for source due datetimes. Priority explanations use Todoist's P1/P2
terminology rather than the application's internal importance conversion.

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
- Complete active-task retrieval and independent
  overdue/today/fourteen-day/priority/assignment checks.
- Cursor pagination to `next_cursor = null`, stable page parameters,
  duplicate-ID handling, and partial-page retention.
- Endpoint-specific P1/P2 mapping verification.
- Conservative project, section, and label resolution.
- Minimal source persistence and cascade deletion.
- Provider priority as a source signal.
- Transparent Todoist saturation thresholds and aggregate coverage facts.
- Degraded-confidence exclusion of overdue-only and priority-only tasks.
- Strong current and multi-signal daily candidacy.
- Fourteen-day Up Next limits and explicit preparation exceptions.
- Clean display titles, all-day due dates, and provider priority terminology.
- No People Waiting claim from a task alone.
- Duplicate-presentation limits, provenance, section order, and word budgets.
- Independent repository, Calendar, and Todoist coverage disclosure.
- Absence of reachable Todoist mutation methods.

One explicitly approved live trial combined approved repository context, one
bounded live primary-Calendar retrieval, and the bounded live Todoist
retrieval in deterministic reduced mode. It invoked no other connector or
hosted inference. The exact-scope, Keychain, refresh, endpoint, pagination,
lifecycle, provenance, failure, and presentation-budget checks passed.

One later explicitly approved validation exercised the complete active-task
endpoint, live priority probe, identity-based reconciliation, and two
date-specific briefing funnels from the same snapshot. Private source content
and production-derived counts remain in ignored local state rather than this
public specification.

## Bounded live-trial stop

Brad approved and completed one bounded trial under this specification. The
mandatory stop now applies.

The later bounded validation and workday-quality gate is separately authorized
by Brad's explicit current instruction. After that gate, no further Todoist
retrieval, refresh, reauthorization, account change, scope change, cache,
mutation, or additional connector is authorized without a new explicit
approval.

## Official references

- [Todoist API v1 and OAuth](https://developer.todoist.com/api/v1/)
- [Todoist filter syntax](https://www.todoist.com/help/articles/introduction-to-filters-V98wIH)
- [ADR-0004: SQLite and Bounded Local Data Lifecycle](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
- [ADR-0005: OAuth and macOS Keychain](../../decisions/0005-adopt-oauth-and-macos-keychain.md)
