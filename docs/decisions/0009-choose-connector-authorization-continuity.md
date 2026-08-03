# ADR-0009: Choose Connector Authorization Continuity

- **Status:** Superseded
- **Date:** 2026-07-31
- **Owners:** Brad
- **Superseded by:** [ADR-0011](0011-require-durable-authorization-for-scheduled-connectors.md)

ADR-0011 replaces this decision by requiring durable refresh continuity for
all four approved scheduled connectors, including Jira. This record remains
the historical rationale for the original bounded-trial choice.

## Context

The accepted on-demand briefing degrades honestly when one approved connector
cannot be read. Scheduled Morning Generation would have no person present to
resolve an expired credential, making authorization continuity an explicit
Milestone 12 dependency rather than an operational workaround.

Google Calendar currently has a short-lived access token and no refresh token.
Jira currently has exact `read:jira-work` authority with a short-lived access
token and no `offline_access`. Work Gmail and Todoist already have
connector-specific refresh behavior and Keychain storage, but those existing
credentials do not independently authorize unattended scheduled refresh.

Any new refresh credential, scope, authorization persistence, or unattended
use requires a conscious decision and a separate bounded authorization gate.

## Decision drivers

- Keep every connector within its accepted read-only source boundary.
- Avoid silent authorization expansion.
- Make an expired source distinguishable from an empty source.
- Preserve a useful briefing when remaining evidence is sufficient.
- Minimize repeated browser authorization without retaining broader authority
  than the product needs.
- Decide whether a reduced-source scheduled briefing can count as successful.

## Options considered

### Option 1: Refreshable Google Calendar authorization

Request and retain a provider-supported Calendar refresh credential under the
existing exact Calendar scope. This could reduce routine interruptions while
keeping source access read-only. It does not require a broader Calendar data
scope, but it creates longer-lived access and must be reviewed against the
accepted credential lifecycle.

### Option 2: Jira `offline_access`

Add Atlassian's `offline_access` scope so Jira can issue a refresh credential.
This would improve continuity but is a scope expansion and a meaningful
increase in durable authorization. It requires explicit approval and likely a
new live authorization exercise.

### Option 3: Continue short-lived Jira authorization

Keep the current `read:jira-work` authorization without `offline_access`.
When it expires, omit Jira until Brad runs the documented same-scope
reauthorization command. This preserves the narrowest grant but creates
periodic interruption.

### Option 4: Graceful omission whenever Jira has expired

Treat expired Jira as reduced coverage and continue from Calendar, Todoist,
Work Gmail, and repository context when those sources provide enough honest
evidence. This reduces operational coupling but does not solve Jira
continuity; Jira-dependent conclusions remain unavailable.

### Option 5: Use existing Gmail and Todoist refresh behavior

Permit the scheduled command to use only the already accepted, exact-account
and exact-scope Gmail and Todoist refresh paths. This avoids another
authorization change for those connectors, but unattended use still requires
explicit Milestone 12 approval, safe failure behavior, bounded retry, and
verification under the selected user LaunchAgent context.

## Decision

For the bounded Milestone 12 trial:

- Google Calendar receives one bounded reauthorization for provider-supported
  refresh capability under the unchanged exact scope
  `https://www.googleapis.com/auth/calendar.events.owned.readonly`.
- Work Gmail may use only its existing approved work account,
  `gmail.readonly` scope, and Keychain refresh path.
- Todoist may use only its existing approved account, `data:read` scope, and
  Keychain refresh path.
- Jira retains its existing short-lived `read:jira-work` grant without
  `offline_access`. Scheduled mode omits Jira before retrieval when its
  credential is unusable and never opens an interactive Jira authorization
  flow.
- A scheduled run requires repository context, usable Google Calendar
  coverage, and at least one usable source from Work Gmail or Todoist. Jira is
  optional.
- Normal bounded Gmail partial coverage is an honest reduced success.
- No other account, scope, connector, source, durable authorization, or
  interactive authorization from scheduled mode is approved.

The Calendar reauthorization remains a separate bounded live setup step after
the implementation and validation commits are pushed. Access and refresh
secrets remain only in macOS Keychain; SQLite records only safe metadata and
Keychain references.

## Consequences

- Connector continuity and authorization authority are explicit rather than
  left to implementation accident.
- Reduced-source briefing behavior remains necessary under every option.
- A refreshable option would require separate approval, documentation,
  credential lifecycle tests, and a bounded live authorization exercise.
- Selecting continued short-lived Jira access would preserve least authority
  at the cost of periodic manual reauthorization.
- Existing Gmail and Todoist refresh credentials would remain isolated by
  connector instance and could be used unattended only within an accepted
  Milestone 12 policy.
- A scheduled run with an expired connector would be a reduced-source success
  or complete failure only according to Brad's explicit sufficiency decision.

## Milestone 12 dependency

Brad resolved the blocking choices in the
[Milestone 12 decision checklist](../product/features/scheduled-morning-generation-decision-checklist.md).
This acceptance authorizes implementation and the explicitly bounded
authorization setup above. It does not accept routine unattended operation
after the seven-date trial.

## Current implementation status

The decision is accepted but not yet exercised. No credential was changed by
accepting this record. Calendar reauthorization and scheduled use remain
subject to the implementation, validation, and bounded setup gates in
Milestone 12.
