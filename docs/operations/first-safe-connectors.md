# First Safe Connector Operations

- **Status:** Accepted
- **Owner:** Brad
- **Last updated:** 2026-07-25

This document describes the implemented Milestone 4 connector boundary. The
local repository-context connector, a synthetic Calendar demonstration, and
one explicitly approved bounded live Google Calendar trial are complete. Live
access is now stopped. None of the credential or live-retrieval commands below
may be repeated without new explicit approval.

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

## Calendar authorization and credential boundary

The implemented Calendar authorization uses Google's installed-application
OAuth flow in the system browser with a loopback redirect, state validation,
and PKCE. It accepts exactly this scope:

```text
https://www.googleapis.com/auth/calendar.events.owned.readonly
```

OAuth client secrets and access tokens are stored only in macOS Keychain.
SQLite contains non-secret client, account, scope, credential-health, expiry,
and lookup metadata. Credential commands display health and identity metadata,
not secret values. Offline access was not requested, and no refresh token is
stored.

The one approved setup sequence used the private local CLI:

```text
python -m chief_of_staff.live_cli import-client /path/to/client.json
python -m chief_of_staff.live_cli authorize \
  --account-identity confirmed-account@example.com
python -m chief_of_staff.live_cli status
```

`import-client` deletes the bounded source file after importing the secret. A
`register-client-from-stdin` fallback is available when a managed browser
cannot deliver the downloaded file; secret input must come from a controlled
transient source and must not enter shell history. These commands exist for
the completed trial boundary, not as continuing authorization to reconfigure
or refresh credentials.

## Bounded live trial

The completed trial was invoked on demand with:

```text
python -m chief_of_staff.live_cli trial
```

It:

- Reads only the two approved repository documents.
- Queries only `calendarId=primary`.
- Uses a window from the beginning of the current day through seven days
  ahead in the configured timezone.
- Follows result pages without using Calendar discovery or other endpoints.
- Normalizes a minimized event representation and keeps raw provider payloads
  transient.
- Stores only non-secret authorization metadata, connector coverage, minimal
  source references, freshness, and the briefing-run graph in SQLite.
- Writes the generated briefing under private ignored `.local/` state.
- Uses deterministic composition without hosted inference.

The trial does not inspect secondary calendars, process attachments, follow
external links, invoke another connector, or expose a Calendar mutation
method.

## Validation

Run the complete quality gate:

```text
make check
```

Connector tests cover exact repository path enforcement, file immutability,
Calendar pagination, all-day events, timezones, freshness, empty data,
unauthorized access, rejected scope expansion, partial-page failure, exact
primary-calendar HTTP requests, Keychain isolation, source provenance,
presentation budgets, transient raw payloads, and absence of mutation methods.

## Current limitations and stop condition

- Google's approved scope can technically read events on other calendars the
  user owns; the application restricts every retrieval to `primary` and
  contract tests enforce that boundary.
- Authorization uses a short-lived access token without offline access or
  automatic refresh.
- Calendar events remain evidence for deterministic output; inference-only
  briefing sections are not implemented.
- Daily Briefing v1 has not been accepted for operational use.

The bounded trial is complete. Do not repeat live Calendar retrieval, refresh
authorization, broaden the Calendar boundary, or begin another live connector
without new explicit approval.
