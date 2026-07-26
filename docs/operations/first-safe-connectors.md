# First Safe Connector Operations

- **Status:** Draft
- **Owner:** Brad
- **Last updated:** 2026-07-25

This document describes the authorized, non-live portion of Milestone 4. The
local repository-context connector is implemented, and the Google Calendar
connector has a mocked authorization and provider boundary. No OAuth
application has been registered, no account has been authorized, no
credential has entered Keychain, and no live Calendar request exists.

## Run the safe connector demonstration

Create the supported development environment, then run:

```text
make demo
```

The command:

- Reads only `docs/product/features/daily-briefing-v1.md` and
  `docs/roadmap.md` from the local repository.
- Retrieves one synthetic Calendar page through in-process mocks.
- Models a second-page Calendar failure.
- Produces a deterministic briefing with repository provenance, a Calendar
  event, and explicit partial-source disclosure.

It does not use the network, load credentials, open an authorization flow,
persist source content, use hosted inference, or modify any source.

The earlier all-synthetic Milestone 3 scenario remains available with:

```text
make demo-synthetic
```

## Repository connector configuration

Construct `RepositoryContextConnector` with one repository root and exact
Markdown file paths relative to that root. Do not supply a repository
directory, glob, ignored private file, or path merely because it is nearby.
The approved-path set is an application input and must be reviewed whenever it
changes.

The accepted behavior and limits are defined in the
[repository connector specification](../architecture/connectors/repository-context.md).

## Calendar mocked boundary

`GoogleCalendarConnector` requires injected authorization and transport
objects. The repository intentionally contains no live implementation of
either boundary. The mock authorization returns non-secret metadata only; the
mock transport serves repository-owned synthetic event fixtures.

The proposed live boundary, exact read-only scope, failure behavior, and
approval requirements are defined in the
[Google Calendar connector specification](../architecture/connectors/google-calendar.md).

## Validation

Run the complete quality gate:

```text
make check
```

Connector tests cover exact repository path enforcement, file immutability,
repository-owned integration, Calendar pagination, all-day events,
timezones, freshness, empty data, unauthorized access, rejected scope
expansion, partial-page failure, source provenance, presentation budgets, and
absence of mutation methods.

## Current limitations

- Google Calendar remains mock-only.
- No Google Cloud project, OAuth client, consent screen, account, redirect, or
  Keychain entry has been selected or configured.
- The proposed Calendar scope has not been requested.
- There is no live HTTP transport, token refresh, revocation, reauthorization,
  or credential inspection.
- No live-data staleness, provider quota, or provider-policy behavior has been
  validated.
- The deterministic composer still omits inference-only sections.
- Daily Briefing v1 has not been accepted for operational use.

Implementation must stop at this point until Brad explicitly approves the
[live-access gate](../architecture/connectors/google-calendar.md#live-access-approval-gate).
