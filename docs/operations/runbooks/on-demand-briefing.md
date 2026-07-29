# Run the On-Demand Daily Briefing

- **Status:** Accepted
- **Owner:** Brad
- **Last updated:** 2026-07-28

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

Inspect Work Gmail credential health without retrieving mail:

```text
.venv/bin/python -m chief_of_staff.gmail_live_cli status
```

## Generate the briefing

Run:

```text
make briefing
```

Only one briefing process may run at a time. A second invocation exits safely
without starting another retrieval.

On success, the command prints:

- The private Daily Briefing path under `.local/briefings/`
- The private Gmail evidence-review path under `.local/gmail/reviews/`
- A concise Work Gmail coverage and omission summary
- Confirmation that the external sources remained read-only

Both artifacts are ignored by Git and created with mode `0600`. Do not copy
the Gmail review into the repository or a public report.

## Understand partial coverage

Partial coverage means the connector honored one or more safety limits rather
than claiming it inspected every potentially relevant message body. The
briefing and private review disclose aggregate eligible, selected, omitted,
usable, and unavailable counts. An omitted message receives no body request
and cannot create a conclusion.

The briefing remains useful when a source is partial, but conclusions apply
only to the disclosed evidence window and selected subset.

## If generation stops

The command exits nonzero and prints a safe category and stage. When available,
it also prints a private diagnostic path under `.local/gmail/`. Failed runs do
not create a combined briefing or persist failed-run source data.

Inspect connector health rather than deleting local state:

```text
.venv/bin/python -m chief_of_staff.gmail_live_cli status
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
