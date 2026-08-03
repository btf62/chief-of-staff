# Run the On-Demand Daily Briefing

- **Status:** Accepted
- **Owner:** Brad
- **Last updated:** 2026-08-02

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

### Credential states and recovery

- **Healthy:** The current Keychain access credential is usable.
- **Refreshable:** The access credential expired, but an already approved
  Keychain refresh credential can recover it within the existing boundary.
- **Expired or missing:** Retrieval is skipped. Use the displayed
  reauthorization command; do not delete SQLite or substitute another account.
- **Unauthorized or boundary exceeded:** Stop and verify the approved account,
  scope, and resource before using the displayed command.
- **Provider unavailable or retrieval failure:** Keep the other sources
  independent. Retry only within a current authorization; do not reauthorize
  merely to work around provider availability.

The project-owned forms of the recovery commands are:

```text
.venv/bin/python -m chief_of_staff.live_cli authorize --account-identity <approved-work-account> --refreshable
.venv/bin/python -m chief_of_staff.todoist_live_cli authorize
.venv/bin/python -m chief_of_staff.jira_live_cli authorize
.venv/bin/python -m chief_of_staff.gmail_live_cli authorize --account-identity <approved-work-account>
```

These commands open the existing authorization flow. They do not authorize a
new account, scope, resource, or refresh-token policy. Stop if the provider
offers a different boundary than the one already approved.

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

Every successful generation also archives an immutable structured
presentation in `.local/state.sqlite3`. Reduced-coverage results and multiple
successful runs on one date are archived independently. Failed or incomplete
attempts are not archived.

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

The on-demand command does not schedule another run, remain resident, or
modify an external system. The separately accepted bounded schedule is
operated only through the
[Scheduled Morning Generation runbook](scheduled-morning-generation.md).

Calendar, Work Gmail, Todoist, and Jira refresh authority remains limited to
the exact accounts, resources, and scopes accepted in
[ADR-0011](../../decisions/0011-require-durable-authorization-for-scheduled-connectors.md).
Jira's `offline_access` permission provides continuity only; its Jira data
permission and source boundary remain unchanged.

## Understand time and historical modes

A current briefing describes the whole selected day. The heading records its
generation time, while written labels distinguish earlier, in-progress, and
upcoming items. An earlier event or elapsed focus opportunity remains part of
the day rather than disappearing at generation time.

Historical lineage uses separate meanings:

- **Recorded:** The exact immutable presentation originally generated.
- **Replay:** A new presentation using current logic and sufficient archived
  normalized facts from a recorded run. It links to, but never replaces, that
  run.
- **Reconstructed:** A later presentation from available historical evidence.
  It is explicitly limited, filters facts after the historical `as_of`, and
  never claims to be the original snapshot.
- **Synthetic:** An invented evaluation scenario. It belongs in private
  evaluation artifacts, never Brad's personal briefing history.

The production interface intentionally shows the latest briefing only. A
history dashboard is deferred. The local data model and synthetic evaluation
support selection by date and generation time without silently substituting a
reconstruction or synthetic example for a recorded briefing.

## Local retention, correction, and deletion

Private runtime state is stored under:

```text
.local/state.sqlite3
.local/briefings/
.local/gmail/reviews/
```

These paths are ignored by Git. Source payloads, Gmail bodies, attachments,
credentials, and hosted-inference responses are not archived for replay.

A later correction or disposition is a current overlay; it does not rewrite
what the recorded presentation originally said. A permitted local deletion
removes dependent archived presentation content and replay facts while
retaining only the approved minimal recurrence tombstone. See
[Local State Operations](../local-state.md) for the complete lifecycle.

## Milestone 11 acceptance record

The synthetic acceptance package is regenerated with:

```text
make milestone-11-eval
```

Its private mode-`0600` artifacts are under
`.local/milestone-11/review/`. They include representative and outage
briefings, aggregate metrics, historical comparisons, responsive browser
captures, and print/PDF evidence. The visual files require an actual browser
and print review; their presence is part of the gate.

Passing automation alone does not accept a milestone. On 2026-07-30, Brad
reviewed and explicitly approved the corrected Milestone 11 package, including
historical behavior, preserved local times and lineage, browser and print
presentation, reduced-source behavior, privacy and no-write boundaries, and
all 14 synthetic metrics. Milestone 11 and the on-demand Daily Briefing v1 MVP
are accepted.
