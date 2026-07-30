# Run the On-Demand Daily Briefing

- **Status:** Accepted
- **Owner:** Brad
- **Last updated:** 2026-07-29

This runbook describes the supported local, on-demand Daily Briefing command.
It reads only the existing approved connector instances and never modifies an
external source.

## First-time local setup

From the repository root, create the project-owned environment:

```text
make bootstrap
```

The existing Calendar, Todoist, Jira, and Work Gmail authorizations must
already be configured. The command uses their non-secret SQLite metadata and
macOS Keychain credentials; it does not ask Brad to type account identifiers,
tokens, or secrets.

Inspect all four approved connectors independently without retrieving source
records:

```text
make connector-status
```

The status check distinguishes healthy, refreshable, expired, missing,
unauthorized, and boundary-mismatched configuration. It prints an exact safe
reauthorization command when Brad must act. It never prints tokens, client
identifiers, private source records, or provider payloads.

## Generate the briefing

Run:

```text
make briefing
```

Only one briefing process may run at a time. A second invocation exits safely
without starting another retrieval.

On success, the command prints:

- The private Daily Briefing path under `.local/briefings/`
- The private Milestone 7 deterministic-review path under
  `.local/gmail/reviews/`
- A concise Work Gmail coverage and omission summary
- Confirmation that the external sources remained read-only

Both artifacts are ignored by Git and created with mode `0600`. The review
separates displayed, supported-but-nondisplayed, insufficient-evidence, and
correction-recurrence results. Do not copy it into the repository or a public
report.

Then open the latest completed briefing:

```text
make web-open
```

The normal workflow is therefore:

```text
make connector-status
make briefing
make web-open
```

## Understand partial coverage

Partial coverage means the connector honored one or more safety limits rather
than claiming it inspected every potentially relevant message body. The
briefing and private review disclose aggregate eligible, selected, omitted,
usable, and unavailable counts. An omitted message receives no body request
and cannot create a conclusion.

The briefing remains useful when a source is partial or unavailable, but
conclusions apply only to the disclosed evidence window and selected subset.
An unavailable source is labeled as unchecked, never as empty. Sections and
conclusions that depend on it are omitted. A failed connector payload is not
persisted. Generation stops without archiving a briefing only when no approved
external source completed and the remaining context cannot support an honest
result.

## If generation stops

The command exits nonzero and prints a safe category and stage. When available,
it also prints a private diagnostic path under `.local/gmail/`. Failed runs do
not create a combined briefing or persist failed-run source data.

Inspect connector health rather than deleting local state:

```text
make connector-status
```

If an OAuth browser flow requires a password, MFA, passkey, CAPTCHA, new
account, new scope, or administrative decision, stop and complete that
user-owned step explicitly. Never weaken a scope or use another account to
avoid the prompt.

## Stop safely

Interrupting the foreground command stops the run. Source pages and Gmail
content are transient, and persistence begins only after every required source
has completed successfully. Do not delete `.local/state.sqlite3` merely to stop
or recover a run.

The application does not schedule another run, remain resident, or modify an
external system.

Changing refresh-token authority remains outside this runbook. The unexecuted
options are recorded in
[ADR-0009](../../decisions/0009-choose-connector-authorization-continuity.md).
