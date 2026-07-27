# First Safe Connector Operations

- **Status:** Accepted
- **Owner:** Brad
- **Last updated:** 2026-07-27

This document describes the implemented repository, Calendar, and Todoist
connector boundaries. The synthetic demonstrations, one bounded Calendar
trial, one bounded combined Calendar-and-Todoist trial, and one approved
complete-retrieval and normal-workday quality validation are complete. Live
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

## Todoist authorization and credential boundary

The Todoist connector uses a Brad-owned confidential client named
`Chief of Staff (Local)`, the fixed loopback callback documented in the
[Todoist connector specification](../architecture/connectors/todoist.md), and
exactly this scope:

```text
data:read
```

The client secret, access token, and rotated refresh token are stored only in
macOS Keychain. SQLite stores only non-secret application ownership, account,
scope, expiry, health, and lookup metadata. The completed authorization
confirmed the selected current-user identity before persistence and
immediately exercised one refresh-token rotation.

The private local setup sequence was:

```text
python -m chief_of_staff.todoist_live_cli \
  register-client-from-stdin \
  --application-name "Chief of Staff (Local)" \
  --application-owner "Brad" \
  --client-id configured-non-secret-client-id
python -m chief_of_staff.todoist_live_cli authorize
python -m chief_of_staff.todoist_live_cli status
```

The client secret must enter the first command through controlled stdin, never
through a command argument, shell history, configuration file, or repository
file. Brad's personal API token is not an accepted fallback.

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

## Bounded combined Todoist trial

The completed Todoist trial was invoked on demand with:

```text
python -m chief_of_staff.todoist_live_cli trial
```

It:

- Confirms the authorized current Todoist user before task retrieval.
- Retrieves the complete active-task collection and applies the local
  selection boundary in the configured timezone.
- Resolves only project and section records referenced by selected tasks and
  retrieves labels only when selected tasks require them.
- Combines Todoist with the same two approved repository documents and one
  bounded primary-Calendar retrieval.
- Stores only selected normalized tasks, minimal referenced context, source
  provenance, freshness, coverage, and the briefing-run graph.
- Keeps provider pages, unused context, cursors, and other raw payloads
  transient.
- Writes the private deterministic briefing under ignored `.local/` state.
- Uses no hosted inference, other live connector, external write, scheduling,
  or persistent source cache.

The later workday-quality validation was invoked once with:

```text
python -m chief_of_staff.todoist_live_cli validate-workday
```

It first verifies live P1/P2 response semantics, then performs one complete
active-task retrieval, reconciles the prior selected snapshot, and generates
the July 26 ministry-workday regression and July 27 normal-workday briefing
from the same normalized live snapshot. It reports retrieval, independent
qualification, overlap, persistence, daily-candidate, and display funnels
without printing private source content.

During the authorization setup, Todoist's browser interface displayed an
existing personal API-token field unrelated to this connector. The connector
did not copy, use, log, or persist that value. A transient app-verification
value exposed during setup was rotated immediately and is not recorded here.
Brad may review whether any existing integrations depend on the personal token
before deciding whether to rotate it; this trial does not authorize reading or
rotating that token.

The private result and local SQLite state must not be copied into Git or a
public report.

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
Todoist tests additionally cover exact scope and endpoint enforcement,
current-user confirmation, refresh rotation, revocation and disconnection,
complete task and context pagination, duplicate-ID handling, priority
semantics, independent selection attribution, snapshot reconciliation,
candidate-versus-display accounting, minimized persistence, independent
failures, non-workday suppression, and no task-system mutation.

## Current limitations and stop condition

- Google's approved scope can technically read events on other calendars the
  user owns; the application restricts every retrieval to `primary` and
  contract tests enforce that boundary.
- Authorization uses a short-lived access token without offline access or
  automatic refresh.
- Todoist refresh credentials exist in Keychain, but their presence does not
  authorize scheduled, unattended, or repeated retrieval.
- Calendar events remain evidence for deterministic output; inference-only
  briefing sections are not implemented.
- Daily Briefing v1 has not been accepted for operational use.

The bounded trials and validation are complete. Do not repeat live Calendar or
Todoist retrieval, refresh authorization, broaden either boundary, or begin
Jira or another live connector without new explicit approval.
