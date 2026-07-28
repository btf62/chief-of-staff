# Jira Connector

- **Status:** Accepted
- **Version:** 2
- **Owner:** Brad
- **Last updated:** 2026-07-27

This specification defines the read-only Jira connector through its completed
resource-restricted authorization and project-discovery phase. It accepts the
project-only live boundary plus the mocked issue connector, normalization,
failure handling, and deterministic briefing behavior described below. It does
not authorize live issue search, issue normalization, issue persistence,
another project discovery, or external mutation.

## Source authority

Jira is authoritative for Jira-managed issue identity, project, type, status,
status category, ownership, provider priority, due date, hierarchy, labels,
dependencies, and authoritative issue link. Chief of Staff may interpret these
facts with other approved sources, but it does not replace Jira or silently
rewrite source-owned facts.

Jira priority is one source signal, not the final Chief of Staff priority. An
assigned, overdue, or high-priority issue does not automatically become a
daily candidate, primary outcome, human commitment, or relationship claim.

## Current implementation boundary

The implemented phase contains:

- A private, resource-level Atlassian OAuth 2.0 3LO application.
- Exact `read:jira-work` scope enforcement without offline access.
- A state-protected fixed loopback callback and explicit browser-account
  confirmation.
- Keychain-only client-secret and short-lived access-token storage.
- Exact one-site discovery through `accessible-resources`.
- A current paginated project-search transport restricted to the selected
  `cloudId`, `action=browse`, and minimal project metadata.
- One private ignored project-selection report with no project catalog in
  SQLite.
- A structured, non-executable query boundary.
- A read-only issue-search transport protocol.
- Synthetic issue pages and mocked non-secret authorization metadata.
- A mocked OAuth state-validation preview that cannot open a provider flow or
  exchange an authorization code.
- Pagination, partial-page retention, field and permission limitations, rate
  limits, and authorization failure categories.
- Provider-neutral source items, normalized task records, source evidence,
  connector-run records, provenance, and coverage counts.
- Deterministic briefing integration using synthetic issue data only.

There is no live issue-search HTTP transport, executable JQL, issue
normalization from Jira, background poller, refresh path, or hosted-inference
path. Project discovery and synthetic issue behavior remain separate
boundaries.

## Accepted account, site, and application boundary

The completed project-discovery trial uses:

- The Atlassian account Brad explicitly confirmed in the browser.
- One exact Jira Cloud site and its provider `cloudId`, retained only as
  private non-secret local metadata.
- A resource-level grant limited to the site selected during consent.
- The private application `Chief of Staff (Local) — Jira`, owned and
  administered by Brad through his Northridge account.
- Exact `read:jira-work` scope with no refresh token or offline access.
- The fixed callback `http://127.0.0.1:8766/oauth/callback`.

Brad explicitly approved proceeding with himself as the sole current
contributor. Additional administrator ownership remains preferred where
Northridge policy permits it. No personal API token or basic-auth fallback is
allowed.

The repository stores only opaque aliases such as `primary-user` and
`approved-site`. Account identity, site URL, and `cloudId` remain private
non-secret runtime metadata and must not be committed.

## OAuth boundary

Atlassian currently recommends OAuth 2.0 authorization-code grants, commonly
called three-legged OAuth or 3LO, for external integrations. New applications
can use resource-restricted grants so the token applies only to the site
selected during consent.

The approved least-privilege scope is:

```text
read:jira-work
```

Atlassian lists this classic scope for reading Jira project and issue data and
for issue search. The project-discovery transport uses only project search.
The connector does not call a user-profile endpoint; account identity is
therefore explicitly confirmed from the browser consent experience rather than
requesting `read:jira-user` or `read:me`.

Do not request:

- `write:jira-work`
- Jira administration or project-management scopes
- User-profile scope without a demonstrated endpoint need
- `offline_access` for the first bounded on-demand trial
- Any granular or product scope not required by the approved operations

Authorization uses a cryptographically random, unguessable `state` value and
rejects mismatches. The callback exactly matches the application registration.
Atlassian's current documented confidential-client 3LO sequence does not
specify PKCE parameters, so this implementation does not invent unsupported
parameters.

The initial trial should use a short-lived access token without refresh
capability. Any future refresh token or unattended operation requires separate
approval of `offline_access`, rotation behavior, revocation, retention, and
scheduling.

The client secret and short-lived access token belong only in macOS Keychain
under reviewed lookup references. SQLite contains only non-secret account,
site, scope, expiry, health, app-ownership, grant-type, and Keychain-reference
metadata.

## Bounded project discovery

The sole live Jira data operation completed before issue selection is:

```text
GET /rest/api/3/project/search
```

Every request uses the selected `cloudId`, `action=browse`, `orderBy=key`, a
page size of 50, and a 20-page ceiling. The application rejects a different
`cloudId` before network access. Returned projects are minimized to ID, key,
name, project type, archived status when the provider supplies it, and the
fact that the browse-filtered endpoint returned the project.

No issue search, issue count derived through issue search, project description,
lead, role, component, version, board, sprint, filter, permission-detail,
configuration, or mutation endpoint is called. Provider pages and unused
fields remain transient. Project names and keys appear only in the mode-`0600`
ignored selection report; the complete catalog is not stored in SQLite.

## Read-only transport contract

The connector transport exposes exactly one provider-shaped operation:

```text
POST /rest/api/3/search/jql
```

This HTTP `POST` is Jira's current enhanced issue-search operation and is
read-only in application semantics. The transport contract exposes
`search_issues` only.

The connector does not implement or expose:

- Issue creation or edits
- Comments or transitions
- Assignment changes
- Worklogs, votes, or watches
- Attachment retrieval or upload
- Deletion
- Project changes
- Jira administration
- Unrestricted issue search

Contract tests verify that mutation methods do not exist on either the
connector or transport interface.

## Proposed bounded query

The mocked connector carries a structured boundary rather than executable
JQL. It represents:

- Unresolved issues.
- Assigned to the authorized current user.
- Within explicitly approved project keys.
- Plus explicitly linked issue keys within those same approved projects.

The proposed JQL for live-gate review is:

```text
project in (<APPROVED_PROJECT_KEYS>)
AND statusCategory != Done
AND (
  assignee = currentUser()
  OR key in (<EXPLICITLY_LINKED_ISSUE_KEYS>)
)
ORDER BY updated DESC, key ASC
```

The placeholder list must be resolved and Brad must approve the final
expression before it is stored or executed. When there are no explicitly
linked keys, the corresponding clause should be omitted rather than supplied
an invalid or broad value. The connector must not substitute a broader query
after a permission or syntax failure.

The proposed first-trial page size is 50 with a 20-page hard stop, for a
maximum of 1,000 returned issue records. Both limits remain gate decisions.
Opaque continuation tokens are followed without decoding or persistence.

## Proposed issue fields

Stable issue ID and key are top-level response identity. The proposed initial
field list is:

```text
summary
project
issuetype
status
assignee
priority
duedate
created
updated
parent
labels
issuelinks
```

Reporter is supported as an optional normalized fact but is not proposed for
the initial trial. It should be added only if Brad approves a concrete use
that cannot be satisfied by assignee and issue history already in scope.

Descriptions, comments, attachments, changelogs, worklogs, votes, watches,
rendered fields, arbitrary properties, and field expansions are excluded.
Issue descriptions require a separate privacy and product justification.

## Normalization and provenance

Synthetic Jira issues preserve, as available:

- Stable issue ID and key
- Clean summary
- Project key and issue type
- Status and status category
- Assignee and optional reporter reference
- Jira priority name
- Due date as an all-day date in Brad's configured timezone
- Created and updated timestamps
- Parent or epic reference
- Labels
- Issue-link and dependency references
- Authoritative Jira display URL
- Freshness
- Connector-run identity
- Source provenance

Descriptions are absent from both the provider model and requested field list.
Missing optional fields remain `None` or empty tuples; they are not invented.
Required identity or classification fields that are empty cause the issue to
be omitted with partial coverage.

Each normalized issue produces minimal source evidence linked to the synthetic
connector run. The evidence fingerprint uses source identity and freshness.
No credential value or raw response is part of a source, task, evidence, or
connector-run model.

## Selection and deterministic briefing behavior

Provider retrieval applies the approved project, unresolved-state, current
assignee, and explicit-link boundary. A separate date-specific daily-candidate
gate then requires current briefing evidence.

Assignment, overdue state, or Jira priority alone is insufficient. Supported
daily signals include:

- Due today or within the next seven days
- Explicit Calendar dependency
- Explicit preparation
- Link to an approved active priority
- Jira-owned blocker or dependency risk
- A separately supported explicit commitment

Synthetic Jira records can support:

- Today's Outcomes when the due date or separate explicit evidence supports
  an outcome.
- Up Next for selectively approaching work.
- Important Tasks when an independent current signal supports inclusion.
- Commitments at Risk only as Jira-owned endangered work, explicitly labeled
  as source status rather than a human promise.
- Preparation Needed when Jira contains explicit preparation linked to
  Calendar.
- Dependency and blocker disclosure.
- Looking Ahead after higher-priority section budgets are satisfied.

A Jira issue alone never creates a People Waiting on Brad item or an inferred
human promise. Section quotas are never filled with unsupported issues.

## Cross-source association

Jira and Todoist remain separate authoritative records. The current
conservative association rule requires an explicit cross-source identifier.
Associated records are not merged or used to overwrite one another.

The association retains:

- Both normalized records
- Both authoritative links
- The explicit association basis
- Conflicting titles, statuses, or due dates

Title similarity alone is not enough to associate records in this phase.
Broader probabilistic matching belongs to later inference work and requires
separate evaluation.

## Coverage, pagination, and failures

Coverage reports:

- Retrieved issue count
- Selected issue count
- Persisted count, currently zero
- Date-specific daily-candidate count
- Displayed count
- Complete or partial status
- Page count and whether pagination occurred
- Safe warnings and an error category

Failure meanings remain distinct:

- Valid empty result: `complete` with zero records.
- Missing, wrong-account, wrong-site, or scope-mismatched authorization:
  `unauthorized`.
- Authentication rejection: `unauthorized`.
- Permission-denied bounded search before usable results: `unavailable` with a
  permission category.
- Permission-limited project results: `partial`.
- Inaccessible requested fields: `partial` with a field-access category.
- Later-page retrieval or pagination failure after usable records: `partial`.
- Rate limiting: a distinct rate-limit category.
- Page-limit exhaustion: `partial`; do not broaden or retry aggressively.

Completed pages remain usable after a later-page failure. Duplicate issue IDs
retain the latest synthetic page representation and are counted. Continuation
tokens and raw pages remain transient.

## Persistence and lifecycle

The completed project-discovery phase applies
[ADR-0004](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md):

- Raw response bytes and provider dictionaries remain transient.
- The complete project catalog, project names, and project keys do not persist
  in SQLite.
- One minimized connector run, coverage record, catalog provenance reference,
  authorization-health record, and selected-site boundary may persist.
- The private report under `.local/` is mode `0600`, ignored by Git, and
  retained only long enough for Brad to approve project keys.
- Credentials never enter SQLite.
- No issue fact is normalized or persisted.

A future issue trial must first confirm Brad's project selection and the Jira
task-to-SQLite mapping:

- Only approved, selected, minimized source facts, provenance, evidence,
  freshness, coverage, and run metadata may persist.
- Descriptions and excluded resources do not persist.
- Complete retrieval may reconcile absence; partial retrieval may not drive
  absence-based deletion.
- Source-owned Jira facts remain subordinate to Jira.

## Validation

Tests demonstrate:

- Exact `read:jira-work` authorization without user-profile, offline, write,
  administrative, granular, Confluence, Jira Software, or Jira Service
  Management scopes.
- State mismatch and replay rejection.
- Explicit account confirmation before token exchange.
- One resource-level selected site and rejection of an unselected `cloudId`.
- Keychain-only client-secret and access-token storage.
- Project-only endpoint, field minimization, pagination, and browse filtering.
- Distinct missing-site, ambiguous-site, authentication, permission,
  rate-limit, empty-project, and partial-pagination outcomes.
- Private report permissions, proposed unexecuted JQL, and absence of project
  catalog or credentials from SQLite.
- No reachable issue or mutation operation in the live discovery transport.
- Mocked OAuth state matching and replay rejection.
- Exact proposed read-scope matching in mock metadata.
- Read-only-only connector and transport interfaces.
- Pagination with stable fields and boundaries.
- Partial-page retention.
- Empty, unauthorized, permission, field-access, rate-limit, and pagination
  distinctions.
- Stable issue identity, display links, and connector-run provenance.
- Missing optional fields and due-date interpretation.
- Status-category filtering.
- Jira priority preserved only as a source signal.
- Dependency and blocker preservation.
- Conservative Jira–Todoist and Jira–Calendar association.
- Preservation of conflicting cross-source facts and links.
- No Jira-only People Waiting or human-commitment claim.
- Retrieved, selected, persisted, candidate, and displayed funnel counts.
- Synthetic canonical-section integration and presentation budgets.
- Absence of credentials, live data, hosted inference, and external writes.

## Mandatory issue-retrieval gate

Work stops after the one project-discovery trial. Brad must inspect the private
report and explicitly approve:

1. Project keys.
2. Whether every selected project should be searched.
3. Whether explicitly linked issue keys outside those projects are allowed.
4. The filled JQL or equivalent query boundary.
5. The exact issue fields, with description and reporter excluded unless a
   later approval changes that boundary.
6. Page size, page limit, retrieval window, normalization, persistence, and
   briefing behavior.

No JQL, issue endpoint, issue normalization, issue persistence, repeat project
discovery, authorization refresh, or Jira mutation is authorized before that
approval.

## Official references

- [Atlassian OAuth 2.0 3LO apps](https://developer.atlassian.com/cloud/jira/platform/oauth-2-3lo-apps/)
- [Jira OAuth 2.0 scopes](https://developer.atlassian.com/cloud/jira/platform/scopes-for-oauth-2-3LO-and-forge-apps/)
- [Jira Cloud REST API v3](https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/)
- [Jira project search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-projects/#api-rest-api-3-project-search-get)
- [Jira enhanced issue search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/)
- [ADR-0004: SQLite and Bounded Local Data Lifecycle](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
- [ADR-0005: OAuth and macOS Keychain](../../decisions/0005-adopt-oauth-and-macos-keychain.md)
