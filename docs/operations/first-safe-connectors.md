# First Safe Connector Operations

- **Status:** Accepted
- **Owner:** Brad
- **Last updated:** 2026-07-28

This document describes the implemented repository, Calendar, Todoist, Jira,
and Work Gmail boundaries. The synthetic demonstrations, bounded Calendar and
Todoist trials, Todoist workday-quality validation, Jira project discovery,
and one exact-project Jira issue trial are complete. The Work Gmail synthetic
gate is complete. Its first combined trial stopped
without satisfying the Milestone 6 acceptance gate. It stopped before Gmail
metadata or body analysis and produced no Gmail records, briefing run, review
artifact, or combined briefing. Offline diagnostic remediation is complete,
and repeatable bounded validation is authorized within the accepted boundary.

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

## Jira authorization and credential boundary

The Jira connector uses a private OAuth 2.0 3LO application named
`Chief of Staff (Local) — Jira`, owned and administered by Brad through his
Northridge account. Brad approved proceeding with himself as the sole current
contributor. It uses a resource-level grant, the fixed loopback callback in the
[Jira connector specification](../architecture/connectors/jira.md), and
exactly this scope:

```text
read:jira-work
```

The client secret and short-lived access token are stored only in macOS
Keychain. No refresh token or offline access was requested. SQLite stores only
non-secret application ownership, user-confirmed account identity, selected
site, `cloudId`, grant type, scope, expiry, health, and Keychain references.

The private local setup and one-time discovery command was:

```text
python -m chief_of_staff.jira_live_cli \
  register-client-interactive \
  --application-name "Chief of Staff (Local) — Jira" \
  --application-owner "Northridge Church"
python -m chief_of_staff.jira_live_cli authorize-and-discover
python -m chief_of_staff.jira_live_cli status
```

The first command prompts for the client ID and uses a hidden terminal prompt
for the client secret. Neither belongs in a command argument, shell history,
configuration file, report, or repository file. A controlled two-line stdin
variant remains available for non-interactive local recovery. The authorization
command requires Brad to confirm the account shown during browser consent.
These commands remain available for inspection and recovery, but their
presence does not authorize another grant or retrieval.

## Bounded Jira project discovery

The one approved Jira discovery:

- Used `accessible-resources` to require exactly one selected site.
- Bound all Jira API requests to that site's `cloudId`.
- Used only `GET /rest/api/3/project/search` with `action=browse`.
- Followed project pagination within a fixed page ceiling.
- Minimized each project to ID, key, name, type, archived status when
  available, and browse availability.
- Kept provider pages and unused fields transient.
- Stored only authorization health, selected-site metadata, one connector run,
  coverage, and a catalog-level provenance reference in SQLite.
- Wrote project names and keys only to a mode-`0600` report under
  `.local/jira/`.
- Prepared an unfilled JQL and field proposal without executing either.

It did not call an issue endpoint or retrieve issue descriptions, counts
through issue search, project details, roles, components, versions, boards,
sprints, filters, permission details, or configuration. It exposed no Jira
mutation operation.

## Bounded Jira issue trial

The later approved Jira issue trial was invoked once with:

```text
python -m chief_of_staff.jira_issue_live_cli trial \
  --briefing-date 2026-07-27
```

It:

- Reused the selected site and its locally stored `cloudId`.
- Used exact `read:jira-work` scope and a short-lived Keychain token without
  requesting a refresh token.
- Posted only to `/rest/api/3/search/jql`.
- Restricted JQL to unresolved `NRC` issues assigned to `currentUser()`.
- Requested only the accepted summary, project, type, status, assignee,
  priority, due date, timestamps, parent, label, and issue-link fields.
- Followed opaque continuation tokens with a stable query and field list.
- Discarded unrequested fields and raw response pages.
- Persisted only minimized normalized issues, labels, links, evidence,
  freshness, coverage, and run metadata.
- Combined one approved repository, primary Calendar, Todoist, and Jira
  retrieval into a private deterministic normal-workday briefing.
- Omitted Jira display items when none had enough current evidence.
- Used no hosted inference, external write, other project, or other connector.

Jira enhanced search is eventually consistent, so the report does not claim
that concurrent provider changes were impossible during pagination. The
private briefing remains under ignored mode-`0600` local state.

## Work Gmail authorization and bounded trial

The implemented Work Gmail connector uses a dedicated Desktop OAuth client in
the Northridge-controlled `nrc-chief-of-staff` project and requests exactly:

```text
https://www.googleapis.com/auth/gmail.readonly
```

The private local setup and trial commands are:

```text
python -m chief_of_staff.gmail_live_cli import-client \
  /path/to/dedicated-desktop-client.json \
  --application-owner "Northridge Church"
python -m chief_of_staff.gmail_live_cli authorize
python -m chief_of_staff.gmail_live_cli status
python -m chief_of_staff.gmail_live_cli trial
```

Client and token secrets remain in macOS Keychain. The imported client file is
deleted after successful bounded import. SQLite receives only non-secret
authorization metadata and minimized application facts.

The trial initially lists two separate streams through the exclusive end of
the briefing day: seven calendar days of inbound mail and fourteen calendar
days of sent mail. It enforces independent 300-message and 200-message caps,
deduplicates before metadata, and stops if combined unique messages exceed
500. If one stream exceeds its cap, the authorized runner moves only that
stream's start forward by one calendar day, preserving the end, until it fits
or reaches three inbound days or seven sent days. It never raises a cap and
discloses any reduced effective window in coverage and the private review.
It retrieves metadata before any content. If more than 120 direct-human or
outbound messages are eligible, it allocates the 120 slots proportionally
between inbound and sent streams, redistributes rounding capacity
deterministically, and selects the newest messages within each stream with the
private message identity used only as the final tie-breaker. Omitted candidates
receive no body request. Coverage and the private review report aggregate
eligible, selected, omitted, fetched, usable, and unavailable counts and mark
the source partial.

The connector retrieves `format=full` only for the selected subset. It never
uses `format=raw`, retrieves attachments, renders active HTML, loads remote
resources, or exposes a Gmail mutation method. It does not use truncated
current-message text for a conclusion. If the total extracted-text boundary is
reached, it preserves completed evidence, omits the message that would exceed
the remaining limit, stops further body retrieval, and reports partial
coverage. Raw responses, MIME trees, and complete bodies remain transient.

Before routine use, a second Northridge-controlled owner or editor must be
added to the Google Cloud project to reduce single-person administrative risk.
This is an operational follow-up, not authorization to change IAM or select an
administrator during the bounded trial.

Every proposed deterministic email conclusion and a bounded rejected sample
are written to a private mode-`0600` artifact under
`.local/gmail/reviews/`. The combined briefing is written under
`.local/briefings/`; both directories are ignored. Neither artifact may enter
Git or a public report.

If an authorized bounded attempt fails, the command exits nonzero after
printing a privacy-safe aggregate JSON report and writes a separate private
mode-`0600` aggregate report under `.local/gmail/` for each attempt. The report
identifies the failure category and stage, affected stream and window when
known, applicable boundary/limit/observed count, and completed listing,
metadata, and body progress. It contains no message identities, addresses,
subjects, query strings, content, labels, page tokens, provider responses, or
credentials. Failed trials do not write briefing state, Gmail evidence, review
artifacts, or combined briefings.

Brad has authorized repeatable, on-demand attempts using only `gmail:work`,
the exact `gmail.readonly` scope, and the existing Northridge-controlled OAuth
application until an MVP briefing succeeds or a genuine external blocker is
reached. An attempt may perform the normal exact-scope refresh or
reauthorization and retrieve the existing read-only Calendar, Todoist, Jira,
and repository inputs required for that combined briefing. Another identical
bounded attempt needs no separate approval. Healthy credentials do not permit
broader access, background operation, or an unrelated retrieval.

Timeout, network, rate-limit, and provider-5xx failures use a safe
`Retry-After` delay when available or bounded exponential backoff otherwise.
One transient sequence makes no more than three attempts and waits no more
than 30 seconds between them. A 401 permits one exact-scope refresh attempt.
Account or scope mismatch, a second 401, 403, invalid response, fixed-endpoint
violation, and internal invariant failures stop without automatic retry.

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
Jira tests additionally cover exact scope, state and account confirmation,
resource-level one-site selection, rejection of an unselected `cloudId`,
Keychain isolation, project discovery, exact enhanced-search JQL and fields,
cursor pagination, duplicate IDs, distinct authorization and retrieval
failures, minimized issue persistence, transient raw pages and cursors,
conservative cross-source association, daily relevance, and absence of
mutation operations.
Work Gmail tests additionally cover exact restricted scope, state and PKCE,
account confirmation, Keychain isolation, refresh and revocation, separate
bounded epoch queries, stable pagination, stream and combined deduplication,
metadata-first filtering, proportional and order-independent body-candidate
selection, the unchanged 120-fetch ceiling, safe omission counts,
extracted-content partial processing without truncated conclusions, MIME
minimization, inert malicious content, reply state, explicit requests and
promises, local correction recurrence, private review artifacts, briefing
integration, structured failure categories, current-run aggregate failure
audits, failed-trial non-persistence, and absence of attachment or mutation
operations.
## Current limitations and stop condition

- Google's approved scope can technically read events on other calendars the
  user owns; the application restricts every retrieval to `primary` and
  contract tests enforce that boundary.
- Authorization uses a short-lived access token without offline access or
  automatic refresh.
- Todoist refresh credentials exist in Keychain, but their presence does not
  authorize scheduled, unattended, or repeated retrieval.
- Jira uses a short-lived access token without refresh capability.
- Work Gmail uses conservative deterministic rules only; uncertain requests
  and commitments are intentionally omitted.
- Daily Briefing v1 has not been accepted for operational use.

Only the repeatable combined-MVP Work Gmail validation described above may
proceed without separate approval. Do not broaden any account, scope, source,
endpoint, retrieval cap, or operating mode; run an unrelated live retrieval;
or begin another connector without new explicit approval from Brad. Personal
Gmail and Google Drive remain deferred and unauthorized.
