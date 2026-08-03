# ADR-0011: Require Durable Authorization for Scheduled Connectors

- **Status:** Accepted
- **Date:** 2026-08-02
- **Owner:** Brad
- **Supersedes:** [ADR-0009](0009-choose-connector-authorization-continuity.md)

## Context

Scheduled Morning Generation is intended to produce a briefing without Brad
being present to repair an expired credential. Calendar, Work Gmail, and
Todoist already have approved refresh continuity, but Jira retained a
short-lived access token. That choice made Jira predictably unavailable before
many scheduled runs and prevented reliable four-connector coverage.

Runtime degradation remains necessary for temporary provider, network, or
credential failures. It is not a substitute for deliberately configuring each
approved connector to survive ordinary access-token expiry.

## Decision drivers

- Make every approved Daily Briefing connector operationally durable.
- Preserve each connector's accepted account, data scope, and source boundary.
- Keep scheduled operation noninteractive.
- Store secret values only in macOS Keychain.
- Make missing refresh continuity visible before trial installation or update.
- Preserve honest reduced-coverage behavior for exceptional runtime failure.

## Options considered

### Option 1: Keep Jira short-lived

Continue exact `read:jira-work` access without a refresh credential and omit
Jira after each access token expires. This is the narrowest authorization but
does not provide dependable Jira coverage for scheduled generation.

### Option 2: Reauthorize Jira before each scheduled run

Require an attended browser flow whenever Jira expires. This avoids a durable
refresh credential but defeats unattended morning generation and introduces a
repetitive manual dependency.

### Option 3: Add durable, rotating Jira refresh continuity

Request `offline_access` alongside the unchanged `read:jira-work` permission,
store the refresh credential in Keychain, rotate it through Atlassian's token
endpoint, and reject any scope or resource expansion. This adds longer-lived
authorization while preserving the accepted read-only Jira data boundary.

### Option 4: Remove Jira from scheduled coverage

Keep Jira available only on demand. This would simplify scheduled operation
but would knowingly omit an accepted source of commitments and approaching
work.

## Decision

Every approved Daily Briefing connector must have durable, noninteractive
authorization continuity before Scheduled Morning Generation is considered
ready:

- Google Calendar retains its exact
  `calendar.events.owned.readonly` scope and Keychain refresh credential.
- Work Gmail retains its exact work account, `gmail.readonly` scope, and
  Keychain refresh credential.
- Todoist retains its exact approved account, `data:read` scope, and Keychain
  refresh credential.
- Jira retains its exact account, selected site, `NRC` project, fixed query,
  and `read:jira-work` data permission. It additionally requests
  `offline_access` solely for authorization continuity.

Jira access and refresh tokens remain separate Keychain values. SQLite stores
only non-secret scope, expiry, health, connector-instance, resource, and
Keychain-reference metadata. Each successful Jira refresh must replace both
the access token and Atlassian's rotated refresh token. A missing token,
missing rotation, scope mismatch, unselected site, or unhealthy Keychain
reference fails closed before issue retrieval.

The attended Jira reauthorization is a separate setup action. Scheduled code
may refresh the accepted grant, but it may not open a browser, request consent,
change account or site, broaden a data scope, or retrieve a different project.

Readiness requires refresh continuity for Calendar, Work Gmail, Todoist, and
Jira individually. Once operation begins, a transient connector failure may
still produce an honestly reduced briefing when the accepted source-
sufficiency policy is met. Durable configuration does not turn every source
into an absolute runtime dependency and does not misrepresent an unavailable
source as empty.

## Consequences

- Ordinary access-token expiry no longer makes Jira predictably absent from
  scheduled briefings.
- The readiness and status surfaces can show durability for all four approved
  connectors without retrieving source records.
- Jira gains a longer-lived authorization credential, increasing the
  importance of Keychain protection, token rotation, revocation, and explicit
  reauthorization after a refresh failure.
- The Jira data boundary remains read-only and unchanged; `offline_access`
  grants continuity, not additional Jira records or operations.
- Tests must prove exact scope enforcement, separate Keychain storage, rotated
  refresh replacement, secret absence from SQLite and output, and
  noninteractive refresh before retrieval.
- A temporary provider or network failure remains visible as reduced coverage
  or failure according to the existing product policy.
- This decision does not add a connector, authorize a source retrieval,
  extend the seven-date trial, or accept routine operation after the trial.

## Implementation status

The repository implementation and attended Jira reauthorization are part of
the accepted Milestone 12 setup correction. Readiness must be reverified
without issue retrieval before the active trial uses the new application
version.
