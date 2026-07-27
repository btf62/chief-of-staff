# Jira Connector

- **Status:** Accepted
- **Version:** 1
- **Owner:** Brad
- **Last updated:** 2026-07-27

This specification defines the read-only Jira connector through its mocked and
synthetic-data phase. It accepts the connector contract, normalization, failure
handling, and deterministic briefing behavior described below. It does not
authorize an OAuth application registration, credential storage, Atlassian
account authorization, site discovery, live Jira retrieval, or external
mutation.

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

- A structured, non-executable query boundary.
- A read-only issue-search transport protocol.
- Synthetic issue pages and mocked non-secret authorization metadata.
- A mocked OAuth state-validation preview that cannot open a provider flow or
  exchange an authorization code.
- Pagination, partial-page retention, field and permission limitations, rate
  limits, and authorization failure categories.
- Provider-neutral source items, normalized task records, source evidence,
  connector-run records, provenance, and coverage counts.
- Deterministic briefing integration using synthetic data only.

There is no Jira HTTP transport, token client, Keychain registration, live CLI,
background poller, or hosted-inference path. The mocked coverage funnel reports
zero persisted records because no Jira persistence or live trial is authorized.

## Proposed account, site, and application boundary

The live-access gate must approve all of the following before implementation:

- The exact Atlassian account Brad selects and confirms.
- One exact Jira Cloud site and its provider `cloudId`.
- A resource-restricted OAuth grant limited to that selected site.
- The OAuth application name, owner, and administrators.
- The exact read scopes, callback, refresh behavior, project keys, query, issue
  fields, page size, page limit, and description policy.

The proposed application should be controlled by Northridge or explicitly
approved by the appropriate Northridge administrator, with at least one
additional authorized administrator where organizational policy permits. No
personal API token or basic-auth fallback is allowed.

The repository stores only opaque aliases such as `primary-user` and
`approved-site`. Account identity, site URL, and `cloudId` remain private
non-secret runtime metadata and must not be committed.

## Proposed OAuth boundary

Atlassian currently recommends OAuth 2.0 authorization-code grants, commonly
called three-legged OAuth or 3LO, for external integrations. New applications
can use resource-restricted grants so the token applies only to the site
selected during consent.

The exact live scope remains subject to Brad's approval. The current
least-privilege recommendation is:

```text
read:jira-work
```

Atlassian lists this classic scope for reading Jira project and issue data and
for issue search. The enhanced JQL search operation identifies it as the
recommended classic scope. The initial connector does not call a user-profile
endpoint, so `read:jira-user` is not currently recommended. If account
verification later requires a separate user-profile call, that added scope and
endpoint require another explicit review.

Do not request:

- `write:jira-work`
- Jira administration or project-management scopes
- User-profile scope without a demonstrated endpoint need
- `offline_access` for the first bounded on-demand trial
- Any granular or product scope not required by the approved operations

Authorization must use a cryptographically random, unguessable `state` value
and reject mismatches. The provider callback must exactly match the
live-gate-approved registration. Atlassian's current documented 3LO sequence
does not specify PKCE parameters for this external application flow; the live
gate must recheck current documentation rather than invent unsupported
parameters.

The initial trial should use a short-lived access token without refresh
capability. Any future refresh token or unattended operation requires separate
approval of `offline_access`, rotation behavior, revocation, retention, and
scheduling.

If live access is later approved, the client secret and access token belong
only in macOS Keychain under reviewed lookup references. SQLite may contain
only non-secret account, site, scope, expiry, health, app-ownership, and
Keychain-reference metadata. No Jira credential currently exists under this
specification.

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

No Jira source facts are persisted in the mocked and synthetic phase. A future
approved live trial must first confirm the Jira task-to-SQLite mapping and
apply [ADR-0004](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md):

- Raw response bytes and provider dictionaries remain transient.
- Only selected, minimized source facts, provenance, evidence, freshness,
  coverage, and run metadata may persist.
- Descriptions and excluded resources do not persist.
- Credentials never enter SQLite.
- Complete retrieval may reconcile absence; partial retrieval may not drive
  absence-based deletion.
- Source-owned Jira facts remain subordinate to Jira.

## Mocked and synthetic validation

Tests demonstrate:

- Mocked OAuth state matching and replay rejection.
- Mandatory live token-exchange stop.
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

## Mandatory live-access gate

Work stops after mocked and synthetic validation. Before a live Jira trial,
Brad must explicitly approve:

1. Atlassian account identity.
2. Exact Jira Cloud site and `cloudId`.
3. OAuth application name, ownership, and administrators.
4. Resource-restricted grant selection.
5. Exact read scopes.
6. Exact callback and current state, PKCE, and refresh behavior.
7. Approved project keys.
8. Final JQL or equivalent boundary.
9. Exact issue fields, including whether reporter or description is allowed.
10. Page size, page limit, retrieval window, and persistence behavior.

No registration, authorization, Keychain change, site discovery, live query,
or Jira mutation is allowed until that approval is recorded.

## Official references

- [Atlassian OAuth 2.0 3LO apps](https://developer.atlassian.com/cloud/jira/platform/oauth-2-3lo-apps/)
- [Jira OAuth 2.0 scopes](https://developer.atlassian.com/cloud/jira/platform/scopes-for-oauth-2-3LO-and-forge-apps/)
- [Jira Cloud REST API v3](https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/)
- [Jira enhanced issue search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/)
- [ADR-0004: SQLite and Bounded Local Data Lifecycle](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
- [ADR-0005: OAuth and macOS Keychain](../../decisions/0005-adopt-oauth-and-macos-keychain.md)
