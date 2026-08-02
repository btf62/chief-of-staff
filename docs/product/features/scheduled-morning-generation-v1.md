# Feature: Scheduled Morning Generation v1

- **Status:** Accepted
- **Version:** 1
- **Owner:** Brad
- **Last updated:** 2026-07-31
- **Trial state:** Live activation authorized for seven eligible dates
- **Implementation state:** Complete; live activation requires the accepted
  setup gates

## Summary

Milestone 12 adds one automatic morning invocation of the accepted on-demand
Daily Briefing on Brad-approved days. The scheduler invokes the existing
read-only pipeline; it does not create another briefing product, enable
routine hosted inference, or modify an external source.

The intended outcome is:

> Chief of Staff can generate one reliable morning briefing automatically on
> approved days without duplicate runs, silent failures, unexpected
> authorization expansion, or dependence on Brad manually opening Terminal.

Brad accepted this specification and the
[Milestone 12 decision checklist](scheduled-morning-generation-decision-checklist.md)
for implementation and a self-limiting seven-eligible-date trial on his
current primary Mac. This acceptance authorizes one bounded Calendar
reauthorization under the unchanged exact read-only scope and scheduled use of
the already accepted Work Gmail and Todoist refresh paths. It does not accept
routine unattended operation after the trial.

## Problem and evidence

The on-demand Daily Briefing v1 MVP is accepted, but Brad must currently open
Terminal and invoke it. That manual dependency makes a morning briefing easier
to miss and prevents the product from being reliably ready at the start of an
approved day.

Scheduling adds failure modes that the on-demand workflow does not have:

- The selected Mac may be asleep, powered off, logged out, disconnected, or
  mid-update.
- A trigger may be missed, delayed, duplicated, or coalesced after wake.
- Short-lived connector authorization may expire without a person present.
- A retry may overwrite or duplicate a briefing already recorded for the day.
- A failure may remain invisible unless the product records and surfaces it.

The design gate must resolve those operating policies before installation.

## Goals

- Generate at most one scheduled-morning briefing for an approved local date
  and invocation type.
- Preserve the accepted briefing, privacy, provenance, correction, retention,
  historical-lineage, and external-read-only boundaries.
- Handle sleep, wake, missed triggers, connector degradation, and complete
  failure explicitly.
- Make success, reduced coverage, failure, and scheduler health visible
  without logging private source content.
- Support disabling, removal, and later migration to an always-awake Mac mini.

## Non-goals

Milestone 12 does not include:

- Personal Gmail
- Google Drive
- New connectors
- External-source mutations
- Routine hosted inference
- Public or remote web access
- Multi-user operation
- Mobile applications
- Analytics dashboards
- Autonomous email or Calendar actions
- Automatic software updates
- A guarantee that a sleeping, powered-off, logged-out, or disconnected host
  can always generate on time

## Accepted operating model

A user-level macOS `launchd` LaunchAgent on Brad's current primary Mac invokes
one bounded command and exits; it does not keep Chief of Staff running
continuously. [ADR-0010](../../decisions/0010-choose-scheduled-morning-generation-mechanism.md)
records the accepted mechanism.

The LaunchAgent triggers at 6:00 a.m. on Monday through Thursday, Saturday,
and Sunday. Friday is ineligible. The application timezone is the IANA zone
`America/New_York`, independent of archived UTC storage. A delayed invocation
may proceed through 11:00 a.m. local time. After that cutoff, it records a
miss without retrieving sources or generating a briefing.

The trial covers seven eligible scheduled local dates, including eligible
dates that are missed or fail. Its first date is the first configured
6:00 a.m. occurrence after installation. After the seventh eligible date, the
scheduled command becomes inert until Brad explicitly accepts or extends
operation. Routine use should later migrate to an approved always-awake Mac
mini.

## User scenarios

1. Given an approved day and a healthy awake host, when the scheduled time
   arrives, then one recorded scheduled-morning briefing is generated and made
   available through the existing local interface.
2. Given the host is asleep at the scheduled time, when it wakes, then the
   approved catch-up policy either permits one bounded late run or records a
   visible missed-run outcome without backfilling silently.
3. Given a scheduled briefing already succeeded for the date, when the
   scheduler or a retry invokes again, then the operation exits safely without
   replacing or duplicating that recorded briefing.
4. Given one connector is unavailable, when the remaining evidence satisfies
   the approved reduced-source policy, then the briefing succeeds with honest
   coverage disclosure and the diagnostic records the reduced mode.
5. Given evidence is insufficient or every approved source fails, when the run
   ends, then no false-success briefing is created and a private non-content
   failure record and approved notification are produced.
6. Given the schedule is disabled or removed, when a future trigger time
   arrives, then no scheduled process runs and existing briefing history
   remains unchanged.

## Requirements

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| SMG-001 | The scheduler must target one Brad-approved macOS host and document its expected login, sleep, wake, power, network, and Keychain conditions. | A host-readiness review verifies each condition without installing the schedule. |
| SMG-002 | Approved weekdays and the exact morning time must be explicit configuration, not inferred from the Leadership Model or Calendar. | Tests show that unconfigured days and times cannot trigger a run. |
| SMG-003 | Briefing-date interpretation must use `America/New_York` and remain correct across daylight-saving transitions. | Spring and fall transition tests verify local date, trigger eligibility, due dates, Calendar times, and idempotency. |
| SMG-004 | A delayed invocation may run only through 11:00 a.m. `America/New_York`; after that cutoff it records a miss without retrieval or generation. | Synthetic sleep, wake, late-wake, power-off, and repeated-wake scenarios produce the accepted result without silent backfill. |
| SMG-005 | A scheduled invocation must acquire the existing process lock and an application-owned idempotency key for `briefing_date` plus scheduled invocation type. | Concurrent, repeated, delayed, and retried triggers create no duplicate successful scheduled run. |
| SMG-006 | An existing recorded briefing must never be overwritten. A successful scheduled run for the same date must become a separate immutable run only when the approved invocation policy permits it. | Replay, manual, reduced-source, and scheduled histories retain distinct run IDs, modes, timestamps, and lineage. |
| SMG-007 | The bounded trial performs no automatic whole-run retry. Provider transports retain only their already accepted pagination and one exact-scope token-refresh behavior. | A failed run records its outcome and waits for review or the next eligible scheduled date. |
| SMG-008 | Connector health preflight must run before retrieval and must distinguish healthy, refreshable, expired, missing, revoked, scope-mismatched, and unavailable sources. | An unusable connector is omitted before retrieval and is never represented as empty coverage. |
| SMG-009 | Scheduled operation may use only authorization continuity explicitly approved for Milestone 12. | Tests prove no browser OAuth flow, new scope, account change, or unapproved refresh path can occur from the scheduled command. |
| SMG-010 | A scheduled run succeeds only with repository context, usable Calendar coverage, and at least one usable source from Work Gmail or Todoist. Jira is optional. | Representative single-source and multi-source outages are classified as full success, reduced success, or failure exactly as accepted. |
| SMG-011 | Complete failure must not persist a successful briefing presentation. | The run records safe failure metadata and makes the failure visible through the approved notification and local status surface. |
| SMG-012 | Diagnostics must be private, local, mode `0600`, bounded, and non-content. | Diagnostics contain only run identity, dates, safe source aliases, stages, health categories, counts, durations, and safe error categories—never source content or secrets. |
| SMG-013 | Success, reduced success, missed run, and failure must have an approved visibility or notification path. | Each outcome is distinguishable without exposing briefing content, event titles, message content, credentials, or private identifiers in the notification. |
| SMG-014 | The recorded briefing must be available to the existing loopback-only web interface after generation. | Starting or opening the supported local interface shows the new run; scheduled generation does not expose or require a remote server. |
| SMG-015 | Existing retention, correction, replay, reconstruction, and deletion behavior must apply unchanged. | Lifecycle tests cover scheduled runs and prove that scheduler diagnostics do not become an unbounded second archive. |
| SMG-016 | The scheduled command must use an explicit supported Python environment, application path, database path, working directory, and safe environment allow list. | A moved repository, missing virtual environment, incompatible schema, or unhealthy package installation fails visibly before connector retrieval. |
| SMG-017 | Software updates must not occur inside the scheduled run. | Version changes require the normal reviewed update and validation workflow; the scheduled command detects incompatibility and stops safely. |
| SMG-018 | Installation, disabling, shutdown, and removal must be documented and reversible. | A dry-run package identifies the exact user service, files, state effects, verification steps, and rollback; removal does not delete briefing history unless separately requested. |
| SMG-019 | Migration to an always-awake Mac mini requires a new host-readiness review. | The migration plan separates code/configuration, Keychain authorization, local-state transfer, validation, and old-host disablement; it never copies secret values into Git or logs. |
| SMG-020 | The scheduler must retain all accepted MVP exclusions. | Contract and repository scans show no Personal Gmail, Drive, new connector, mutation, hosted-inference, remote-access, multi-user, mobile, analytics, or autonomous-action path. |
| SMG-021 | The trial must count seven eligible scheduled local dates, not seven successful retrievals, then prevent further scheduled retrieval. | Missed and failed eligible dates advance the deterministic trial ordinal; the eighth and later invocation reports `trial_complete` before connector access. |

## Accepted source and outcome policy

- **Full success:** Repository context, Calendar, Work Gmail, Todoist, and Jira
  all have accepted usable coverage.
- **Reduced success:** Repository context and Calendar have usable coverage,
  at least one of Work Gmail or Todoist has usable coverage, and one or more
  nonmandatory sources are unavailable, expired, or partial. Normal bounded
  Gmail partial coverage is reduced success.
- **Failure:** Repository context or Calendar is unavailable; both Work Gmail
  and Todoist are unusable; or the pipeline cannot produce a valid briefing.

An expired or failed connector is unavailable, never empty. Jira remains
short-lived and is omitted without an interactive authorization attempt when
unusable. Calendar may use the separately authorized refresh credential under
the unchanged exact read-only scope. Work Gmail and Todoist may use only their
already accepted exact-account, exact-scope refresh paths.

The supported outcomes are `full_success`, `reduced_success`,
`already_completed`, `ineligible_day`, `before_window`,
`missed_after_cutoff`, `insufficient_sources`,
`credential_attention_required`, `transient_failure`,
`configuration_failure`, and `trial_complete`.

## Constraints and risks

- A user-level LaunchAgent runs in the logged-in user's context; logout,
  shutdown, FileVault startup state, sleep, network availability, Keychain
  access, and system privacy controls can still prevent useful work.
- Calendar-based `launchd` triggers can run after wake from sleep, but powered-
  off triggers are not recovered automatically. The application still needs
  an explicit catch-up cutoff and idempotency.
- Scheduled refresh authority is limited to the exact connector decisions in
  [ADR-0009](../../decisions/0009-choose-connector-authorization-continuity.md).
- Notifications must reveal no private briefing content.
- An always-awake host reduces sleep-related misses but creates a longer-lived
  local attack and credential-availability window.

## Post-trial decision

The trial does not convert automatically into permanent scheduling. After
seven eligible dates, Brad must review the results and explicitly accept,
extend, revise, or remove scheduled operation. Moving to a Mac mini requires a
new host-readiness and credential-migration review.

## Implemented operating surface

The accepted implementation provides:

- a deterministic local scheduling policy and application-owned idempotency
  record;
- forward-only migration `0012` for bounded non-content trial and occurrence
  state;
- one current-user LaunchAgent definition with no `RunAtLoad`, `KeepAlive`, or
  automatic whole-run retry;
- retrieval-free readiness, dry-run, status, install, notification-test,
  disable, enable, and removal commands;
- exact-scope Calendar refresh continuity through macOS Keychain;
- source sufficiency requiring Calendar plus Work Gmail or Todoist, with Jira
  optional;
- private-safe fixed notifications and a non-content local web status summary;
  and
- terminal trial behavior after seven eligible dates.

The
[Scheduled Morning Generation runbook](../../operations/runbooks/scheduled-morning-generation.md)
is the authoritative operator procedure. Implementation does not itself
activate the LaunchAgent, reauthorize Calendar, retrieve a live source, or
accept routine post-trial use.

## Related documents

- [Product requirements](../requirements.md)
- [Daily Briefing v1](daily-briefing-v1.md)
- [Implementation roadmap](../../roadmap.md#milestone-12--scheduled-morning-generation)
- [ADR-0009: Connector Authorization Continuity](../../decisions/0009-choose-connector-authorization-continuity.md)
- [ADR-0010: Scheduled Morning Generation Mechanism](../../decisions/0010-choose-scheduled-morning-generation-mechanism.md)
- [Milestone 12 decision checklist](scheduled-morning-generation-decision-checklist.md)
- [On-demand briefing runbook](../../operations/runbooks/on-demand-briefing.md)
