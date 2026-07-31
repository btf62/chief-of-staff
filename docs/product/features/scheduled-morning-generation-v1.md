# Feature: Scheduled Morning Generation v1

- **Status:** Proposed
- **Owner:** Brad
- **Last updated:** 2026-07-30

## Summary

Milestone 12 proposes one automatic morning invocation of the accepted
on-demand Daily Briefing on Brad-approved days. The scheduler would invoke the
existing read-only pipeline; it would not create another briefing product,
expand connector access, enable routine hosted inference, or modify an
external source.

The intended outcome is:

> Chief of Staff can generate one reliable morning briefing automatically on
> approved days without duplicate runs, silent failures, unexpected
> authorization expansion, or dependence on Brad manually opening Terminal.

This proposal does not authorize implementation or installation. Brad must
approve the decisions in the
[Milestone 12 decision checklist](scheduled-morning-generation-decision-checklist.md)
before scheduled operation begins.

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

## Proposed operating model

A user-level macOS `launchd` LaunchAgent is the recommended scheduling
direction, subject to
[ADR-0010](../../decisions/0010-choose-scheduled-morning-generation-mechanism.md).
The agent would invoke one bounded command and exit; it would not keep the
Chief of Staff application running continuously.

The target host, scheduled days, exact time, and catch-up policy remain
unselected. The application timezone remains the IANA zone
`America/New_York`, independent of archived UTC storage. The selected host
must have a compatible local timezone and pass an explicit timezone preflight
before scheduled operation is enabled.

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
| SMG-004 | The implementation must define one approved missed-run and wake-after-trigger policy with a finite catch-up window and cutoff. | Synthetic sleep, wake, late-wake, power-off, and repeated-wake scenarios produce the approved result without silent backfill. |
| SMG-005 | A scheduled invocation must acquire the existing process lock and an application-owned idempotency key for `briefing_date` plus scheduled invocation type. | Concurrent, repeated, delayed, and retried triggers create no duplicate successful scheduled run. |
| SMG-006 | An existing recorded briefing must never be overwritten. A successful scheduled run for the same date must become a separate immutable run only when the approved invocation policy permits it. | Replay, manual, reduced-source, and scheduled histories retain distinct run IDs, modes, timestamps, and lineage. |
| SMG-007 | Retries must be finite, delayed, and bounded by the catch-up cutoff. | The recommended default is at most one automatic retry; Brad must approve the exact retry policy. |
| SMG-008 | Connector health preflight must run before retrieval and must distinguish healthy, refreshable, expired, missing, revoked, scope-mismatched, and unavailable sources. | An unusable connector is omitted before retrieval and is never represented as empty coverage. |
| SMG-009 | Scheduled operation may use only authorization continuity explicitly approved for Milestone 12. | Tests prove no browser OAuth flow, new scope, account change, or unapproved refresh path can occur from the scheduled command. |
| SMG-010 | Reduced-source success must follow a Brad-approved sufficiency policy and always disclose omitted or partial sources. | Representative single-source and multi-source outages are classified as full success, reduced success, or complete failure exactly as approved. |
| SMG-011 | Complete failure must not persist a successful briefing presentation. | The run records safe failure metadata and makes the failure visible through the approved notification and local status surface. |
| SMG-012 | Diagnostics must be private, local, mode `0600`, bounded, and non-content. | Diagnostics contain only run identity, dates, safe source aliases, stages, health categories, counts, durations, and safe error categories—never source content or secrets. |
| SMG-013 | Success, reduced success, missed run, and failure must have an approved visibility or notification path. | Each outcome is distinguishable without exposing briefing content, event titles, message content, credentials, or private identifiers in the notification. |
| SMG-014 | The recorded briefing must be available to the existing loopback-only web interface after generation. | Starting or opening the supported local interface shows the new run; scheduled generation does not expose or require a remote server. |
| SMG-015 | Existing retention, correction, replay, reconstruction, and deletion behavior must apply unchanged. | Lifecycle tests cover scheduled runs and prove that scheduler diagnostics do not become an unbounded second archive. |
| SMG-016 | The scheduled command must use an explicit supported Python environment, application path, database path, working directory, and safe environment allow list. | A moved repository, missing virtual environment, incompatible schema, or unhealthy package installation fails visibly before connector retrieval. |
| SMG-017 | Software updates must not occur inside the scheduled run. | Version changes require the normal reviewed update and validation workflow; the scheduled command detects incompatibility and stops safely. |
| SMG-018 | Installation, disabling, shutdown, and removal must be documented and reversible. | A dry-run package identifies the exact user service, files, state effects, verification steps, and rollback; removal does not delete briefing history unless separately requested. |
| SMG-019 | Migration to an always-awake Mac mini must require a new host-readiness review. | The migration plan separates code/configuration, Keychain authorization, local-state transfer, validation, and old-host disablement; it never copies secret values into Git or logs. |
| SMG-020 | The scheduler must retain all accepted MVP exclusions. | Contract and repository scans show no Personal Gmail, Drive, new connector, mutation, hosted-inference, remote-access, multi-user, mobile, analytics, or autonomous-action path. |

## Proposed policies requiring Brad's decision

The design recommends, but does not select:

- Begin on the current primary Mac with a bounded scheduled trial, then prefer
  an always-awake Mac mini for routine unattended reliability.
- Use configured normal workdays only, with Brad naming the exact weekdays.
- Choose a time after the host is normally awake but early enough to preserve
  briefing usefulness.
- Permit at most one catch-up attempt inside a short approved grace window and
  never backfill after the cutoff.
- Treat a deterministically valid reduced-source briefing as successful only
  under an explicit source-sufficiency policy.
- Consider refreshable Calendar authorization under the unchanged read-only
  scope, while initially retaining short-lived Jira access and omitting Jira
  honestly when expired.
- Use a private-safe local macOS notification plus an inspectable local status
  record.
- Require a bounded attended trial before unattended operation.

## Constraints and risks

- A user-level LaunchAgent runs in the logged-in user's context; logout,
  shutdown, FileVault startup state, sleep, network availability, Keychain
  access, and system privacy controls can still prevent useful work.
- Calendar-based `launchd` triggers can run after wake from sleep, but powered-
  off triggers are not recovered automatically. The application still needs
  an explicit catch-up cutoff and idempotency.
- Existing Gmail and Todoist refresh capability does not itself authorize
  unattended refresh. Calendar and Jira continuity remain unresolved under
  [ADR-0009](../../decisions/0009-choose-connector-authorization-continuity.md).
- Notifications must reveal no private briefing content.
- An always-awake host reduces sleep-related misses but creates a longer-lived
  local attack and credential-availability window.

## Open questions

All blocking questions are isolated in the
[Milestone 12 decision checklist](scheduled-morning-generation-decision-checklist.md).
Implementation must not begin until Brad resolves them and the proposed ADRs
are accepted or revised.

## Related documents

- [Product requirements](../requirements.md)
- [Daily Briefing v1](daily-briefing-v1.md)
- [Implementation roadmap](../../roadmap.md#milestone-12--scheduled-morning-generation)
- [ADR-0009: Connector Authorization Continuity](../../decisions/0009-choose-connector-authorization-continuity.md)
- [ADR-0010: Scheduled Morning Generation Mechanism](../../decisions/0010-choose-scheduled-morning-generation-mechanism.md)
- [Milestone 12 decision checklist](scheduled-morning-generation-decision-checklist.md)
- [On-demand briefing runbook](../../operations/runbooks/on-demand-briefing.md)
