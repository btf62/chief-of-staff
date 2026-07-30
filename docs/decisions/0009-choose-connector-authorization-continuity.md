# ADR-0009: Choose Connector Authorization Continuity

- **Status:** Proposed
- **Date:** 2026-07-30
- **Owners:** Brad

## Context

An on-demand briefing should degrade honestly when one approved connector
cannot be read. Google Calendar and Jira currently have different credential
lifetimes and refresh behavior. Repeated interactive authorization may
interrupt normal use, but any change to scopes, refresh-token authority, or
authorization persistence requires a conscious decision rather than an
operational workaround.

Milestone 11 adds retrieval-free preflight, connector-specific recovery
guidance, and reduced-source composition. It does not authorize a new scope,
request a new credential, or change an existing grant.

## Decision drivers

- Keep every connector within its accepted read-only source boundary.
- Avoid silent authorization expansion.
- Make an expired source distinguishable from an empty source.
- Preserve a useful briefing when remaining evidence is sufficient.
- Minimize repeated browser authorization without retaining broader authority
  than the product needs.

## Options considered

### Option 1: Refreshable Google Calendar authorization

Request and retain a provider-supported Calendar refresh credential under the
existing exact Calendar scope. This could reduce routine interruptions while
keeping source access read-only, but it would create longer-lived access and
must be reviewed against the accepted credential lifecycle.

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

## Proposed direction

No authorization change is selected yet.

Continue graceful omission as the safe operational baseline. Before changing
authorization, Brad should separately decide whether the continuity benefit
of refreshable Calendar access or Jira `offline_access` justifies the
longer-lived authority. Continued short-lived Jira authorization remains a
valid least-authority option.

## Consequences if accepted

- Connector continuity and authorization authority will be decided
  explicitly rather than by implementation accident.
- Reduced-source briefing behavior remains necessary under every option.
- A refreshable option would require separate approval, documentation,
  credential lifecycle tests, and a bounded live authorization exercise.
- Selecting continued short-lived Jira access would preserve least authority
  at the cost of periodic manual reauthorization.

## Current implementation status

This proposal is unexecuted. Milestone 11 does not request refresh
credentials, broaden OAuth scopes, reauthorize an account, or alter
authorization persistence.
