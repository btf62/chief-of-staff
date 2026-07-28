# ADR-0007: Remove Asana from Product Scope

- **Status:** Accepted
- **Date:** 2026-07-28
- **Owners:** Brad

## Context

Asana was originally included as a Phase 1 source for
[Daily Briefing v1](../product/features/daily-briefing-v1.md). The only
identified live use was a private 9 Embers project used for Rock RMS
collaboration, which Brad accesses as a guest.

Workspace and exact-project discovery succeeded. Task retrieval nevertheless
returned HTTP 403 repeatedly after correcting application distribution,
reauthorizing with the approved scopes, and reducing optional fields. The
exact provider restriction was not conclusively established. Guest-access or
workspace-administration policy is a plausible explanation, but it is not a
confirmed provider fact.

No live Asana task data was retrieved or persisted. Resolving the remaining
restriction could require another organization's administrative involvement
and more provider-specific troubleshooting. That dependency and cost are not
justified by the source's expected product value. Brad explicitly decided
that Chief of Staff does not need data from any Asana account, workspace,
project, or task.

## Decision

Asana is removed from Daily Briefing v1, all planned Chief of Staff
connectors, and every roadmap milestone. No Asana authorization, retrieval,
normalization, persistence, briefing integration, monitoring, or active
connector specification will remain.

The project will not seek 9 Embers administrative approval or attempt another
Asana API or authentication strategy. The existing provider application
registration may remain inactive and unused; deleting it remotely is a
separate irreversible administrative action.

The committed multi-account connector-instance architecture remains. It is
not Asana-specific and is required for the independently authorized Work Gmail
and Personal Gmail instances.

Reintroducing Asana requires all of the following:

1. A new product requirement.
2. An ADR that supersedes this decision.
3. A newly approved security and access boundary.
4. A demonstrated need sufficient to justify the administrative dependency.

## Alternatives considered

### 1. Ask a 9 Embers administrator to approve or unblock the application

This might resolve the restriction, but it would add an external
administrative dependency for a source that Brad has determined the product
does not need.

### 2. Use a personal access token or alternate authentication

Changing authentication could weaken the accepted OAuth and credential
boundaries without establishing that authentication caused the failure. It
would also continue investment in an unnecessary connector.

### 3. Retrieve Asana information indirectly from another source

Email or another system may sometimes mention the same work, but treating an
indirect source as an Asana substitute would create ambiguous source
authority. Remaining approved sources should be interpreted on their own
terms.

### 4. Keep Asana deferred as a future connector

Deferral would leave misleading product and roadmap expectations and preserve
an unnecessary credential and maintenance footprint.

### 5. Remove Asana entirely

This was selected because it matches Brad's explicit product decision,
reduces risk and complexity, and focuses implementation on sources with
greater expected value.

## Consequences

### Positive

- The source and credential footprint is smaller.
- Privacy and administrative complexity are reduced.
- The product has fewer third-party dependencies.
- Implementation and maintenance burden are reduced.
- Product focus is clearer around Calendar, Todoist, Jira, Gmail, Drive, and
  approved repository context.

### Negative

- Chief of Staff will not directly see work that exists only in Asana.
- 9 Embers collaboration may require manual awareness or representation in
  Jira, Todoist, Calendar, email, or approved repository context.
- Reintroducing Asana later requires new design and authorization work.

## Related decisions

- [ADR-0004: Adopt SQLite and a Bounded Local Data Lifecycle](0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
- [ADR-0005: Adopt OAuth and macOS Keychain for Connector Credentials](0005-adopt-oauth-and-macos-keychain.md)
