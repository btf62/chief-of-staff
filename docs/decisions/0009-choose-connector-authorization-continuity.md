# ADR-0009: Choose Connector Authorization Continuity

- **Status:** Proposed
- **Date:** 2026-07-30
- **Owners:** Brad

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

## Proposed direction

No authorization change is selected yet.

Continue graceful omission as the safe operational baseline. The recommended
starting direction is to review refreshable Calendar authorization under the
unchanged read-only scope, retain short-lived Jira authorization initially,
and omit Jira honestly when it expires. Jira `offline_access` should be
considered only if the missing coverage materially reduces scheduled briefing
value. Brad has not selected these recommendations.

Brad must also decide whether a deterministically valid reduced-source
briefing counts as scheduled success and whether any source—especially
Calendar—is mandatory.

## Consequences if accepted

- Connector continuity and authorization authority will be decided
  explicitly rather than by implementation accident.
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

Milestone 12 implementation must not begin until Brad decides:

1. Whether Google Calendar should receive refreshable authorization.
2. Whether Jira remains short-lived and omitted when expired or requests
   `offline_access`.
3. Which reduced-source combinations count as scheduled success.

These choices belong in the
[Milestone 12 decision checklist](../product/features/scheduled-morning-generation-decision-checklist.md)
and require separate authorization before any credential change. Gmail and
Todoist differ because their accepted connector designs already include
refresh credentials; Milestone 12 approval would still need to verify those
existing paths under the selected scheduled user context, but it would not
create a new scope or credential type for either connector.

## Current implementation status

This proposal is unexecuted. It does not request refresh credentials, broaden
OAuth scopes, reauthorize an account, alter authorization persistence, or
authorize unattended refresh.
