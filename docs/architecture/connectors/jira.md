# Jira Connector

- **Status:** Accepted
- **Version:** 3
- **Owner:** Brad
- **Last updated:** 2026-07-27

This specification defines the read-only Jira connector through its bounded
issue-retrieval phase. It accepts the resource-restricted authorization,
project discovery, exact-project enhanced JQL search, minimized issue
persistence, and deterministic briefing behavior described below. It does not
authorize another issue retrieval, another project, broader fields or scopes,
refresh capability, or external mutation.

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
- An exact `NRC` project boundary and executable, fixed JQL.
- A live enhanced-search HTTP transport restricted to the selected `cloudId`.
- Cursor pagination with a stable query, field list, and page size.
- Synthetic issue pages and mocked non-secret authorization for contract
  tests.
- A mocked OAuth state-validation preview that cannot open a provider flow or
  exchange an authorization code.
- Pagination, partial-page retention, field and permission limitations, rate
  limits, and authorization failure categories.
- Provider-neutral source items plus dedicated minimized Jira persistence,
  source evidence, connector-run records, provenance, and coverage counts.
- Deterministic briefing integration across approved repository context,
  primary Calendar, Todoist, and Jira without hosted inference.

There is no background poller, refresh-token path, hosted-inference path,
external write, unrestricted search, or other-project access. Project
discovery and issue retrieval remain separate bounded operations.

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

The bounded trial uses a short-lived access token without refresh capability.
Any future refresh token or unattended operation requires separate approval of
`offline_access`, rotation behavior, revocation, retention, and scheduling.

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

## Approved bounded query

The live transport accepts only the approved `NRC` project, unresolved state,
and `currentUser()` assignment boundary. Explicitly linked keys outside the
project are not approved. It executes exactly this logical query:

```text
project = NRC
AND statusCategory != Done
AND assignee = currentUser()
ORDER BY updated DESC, key ASC
```

The connector must not substitute or retry with a broader query after a
permission, syntax, or provider failure.

The page size is 50 with a 20-page hard stop, for a maximum of 1,000 returned
issue records. Opaque continuation tokens are followed without decoding,
logging, caching, or persistence. Jira enhanced search is eventually
consistent; the connector reports that concurrent changes cannot be excluded.

## Approved issue fields

Stable issue ID and key are top-level response identity. The approved field
list is:

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

Reporter, descriptions, comments, attachments, changelogs, worklogs, votes,
watches, rendered fields, names, schema, arbitrary properties, and field
expansions are excluded. Unrequested response fields remain transient and are
discarded.

## Normalization and provenance

Jira issues preserve, as available:

- Stable issue ID and key
- Clean summary
- Project key and issue type
- Status and status category
- Assignee account reference sufficient to support the `currentUser()` query
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

Each normalized issue produces minimal source evidence linked to its connector
run. The evidence fingerprint uses source identity and freshness. Dedicated
SQLite tables store only approved facts, labels, and issue-link references.
No credential value, cursor, unrequested field, or raw response is part of a
source, issue, evidence, or connector-run model.

## Selection and deterministic briefing behavior

Provider retrieval applies the approved project, unresolved-state, and current
assignee boundary. A separate date-specific daily-candidate gate then requires
current briefing evidence.

Assignment, overdue state, or Jira priority alone is insufficient. Supported
daily signals include:

- Due today or within the next seven days
- Explicit Calendar dependency
- Explicit preparation
- Link to an approved active priority
- Jira-owned blocker or dependency risk
- An overdue due date combined with a recent source update
- A separately supported explicit commitment

Jira records can support:

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

Jira and Todoist remain separate authoritative records. The conservative
association rule requires an explicit stable cross-source identifier, such as
a Jira key in Todoist content or an already normalized stable reference.
Associated records are not destructively merged or used to overwrite one
another.

The association retains:

- Both normalized records
- Both authoritative links
- The explicit association basis
- Conflicting statuses, due dates, or source priorities

One combined recommendation may carry both authoritative links when explicit
association evidence supports it. Title similarity alone is not enough.

## Coverage, pagination, and failures

Coverage reports:

- Retrieved issue count
- Selected issue count
- Persisted count
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
are counted and retain the newest representation by Jira's `updated` fact.
Continuation tokens and raw pages remain transient.

## Persistence and lifecycle

The project-discovery and bounded issue phases apply
[ADR-0004](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md):

- Raw response bytes and provider dictionaries remain transient.
- The complete project catalog and project names do not persist in SQLite.
- One minimized connector run, coverage record, catalog provenance reference,
  authorization-health record, and selected-site boundary may persist.
- The private report under `.local/` is mode `0600`, ignored by Git, and
  retained only long enough for Brad to approve project keys.
- Credentials never enter SQLite.
- Only approved, selected, minimized issue facts, provenance, evidence,
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
- Private report permissions and absence of project catalog or credentials
  from SQLite.
- No reachable mutation operation in either live transport.
- Mocked OAuth state matching and replay rejection.
- Exact read-scope matching in mock metadata.
- Read-only-only connector and transport interfaces.
- Exact enhanced-search endpoint, JQL, fields, page size, selected site, and
  `cloudId`.
- Cursor pagination with stable fields and boundaries.
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
- Canonical-section integration and presentation budgets.
- Absence of credentials, private live fixtures, hosted inference, and
  external writes.

## Mandatory stop after the issue trial

The approved issue gate permits one bounded retrieval and combined briefing.
After that trial, work stops. Another Jira query, project discovery,
authorization refresh, scope or project expansion, field expansion, external
mutation, or another connector requires new explicit approval.

## Official references

- [Atlassian OAuth 2.0 3LO apps](https://developer.atlassian.com/cloud/jira/platform/oauth-2-3lo-apps/)
- [Jira OAuth 2.0 scopes](https://developer.atlassian.com/cloud/jira/platform/scopes-for-oauth-2-3LO-and-forge-apps/)
- [Jira Cloud REST API v3](https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/)
- [Jira project search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-projects/#api-rest-api-3-project-search-get)
- [Jira enhanced issue search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/)
- [ADR-0004: SQLite and Bounded Local Data Lifecycle](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
- [ADR-0005: OAuth and macOS Keychain](../../decisions/0005-adopt-oauth-and-macos-keychain.md)
