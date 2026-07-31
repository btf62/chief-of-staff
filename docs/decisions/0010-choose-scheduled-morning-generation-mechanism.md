# ADR-0010: Choose the Scheduled Morning Generation Mechanism

- **Status:** Accepted
- **Date:** 2026-07-31
- **Owners:** Brad

## Context

The accepted on-demand Daily Briefing v1 MVP runs successfully when Brad
invokes it. Milestone 12 proposes one automatic morning invocation on approved
days, but the repository has no accepted scheduling mechanism, host policy,
missed-run policy, or unattended authorization policy.

Apple describes `launchd` as the preferred macOS facility for timed jobs and
documents that a `StartCalendarInterval` job delayed by sleep runs after wake,
while a powered-off Mac does not recover that occurrence. Apple also documents
that `cron` skips occurrences while the Mac is asleep or off. See
[Scheduling Timed Jobs](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html).

A user LaunchAgent runs in the logged-in user's context rather than the
system-daemon context. That aligns better with the product's per-user files and
Keychain boundary, but it does not guarantee that the user is logged in, the
login Keychain is usable, the network is available, or the Mac is awake. See
[Creating Launch Daemons and Agents](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html),
[Designing Daemons and Services](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/DesigningDaemons.html),
and Apple's
[Mac keychain technote](https://developer.apple.com/documentation/Technotes/tn3137-on-mac-keychains).

This ADR records the accepted scheduling mechanism for a bounded trial. Routine
unattended operation after the trial remains unaccepted.

## Decision drivers

- Reliable behavior across login, sleep, wake, power loss, network loss, and
  daylight-saving changes
- Compatibility with the existing local Python, SQLite, and macOS Keychain
  boundaries
- Explicit missed-trigger and duplicate prevention
- Private, bounded, non-content diagnostics
- Simple installation, inspection, disabling, and removal
- Low maintenance burden and no always-running process unless justified
- A clean migration path to a future always-awake Mac mini
- No authorization, source, inference, or agency expansion by implication

## Options considered

| Option | Reliability and sleep/wake behavior | Security and Keychain context | Logging, removal, and maintenance | Portability and duplicate risk |
| --- | --- | --- | --- | --- |
| 1. User-level macOS `launchd` LaunchAgent | Native calendar trigger; a sleep-delayed `StartCalendarInterval` job can run after wake, while power-off still misses. User login remains required. | Runs as Brad in the user context, which best matches per-user files and Keychain, but actual Keychain and privacy access still require a host trial. | One service definition, one-shot process, native inspection, and explicit unload/removal. Safe application diagnostics remain required. | macOS-specific. Duplicate wake or retry calls are contained by application idempotency and locking. |
| 2. `cron` | Apple documents that sleep and power-off occurrences are skipped with no wake catch-up. | Runs per user but offers a weaker macOS integration and the same credential/runtime concerns. | Edits a shared user crontab, has less product-specific status, and is less straightforward to package and inspect safely. | Broad Unix familiarity, but worse Mac reliability and the same application-level duplicate controls. |
| 3. Always-running application with internal timer | Can observe its own clock only while alive and scheduled by the OS; sleep still pauses useful work and process failure needs supervision. | Keeps the application and possibly credentials available longer than necessary. | Requires lifecycle supervision, health monitoring, restart policy, and more memory and maintenance. | More portable timer logic, but effectively creates another service architecture and duplicate-leader risk. |
| 4. Continue manual/on-demand operation | No automatic missed trigger because Brad decides when to run, but the briefing is not ready without manual action. | Narrowest authority and shortest credential-use window. | Already supported and simplest to maintain. | Fully portable within the current CLI, but does not achieve Milestone 12's outcome. |
| 5. Future always-awake Mac mini host | Reduces sleep and travel-related misses, but power, network, login, updates, and process failures remain possible. It still needs a scheduling mechanism. | Creates a dedicated long-lived host and requires new Keychain setup, local-state policy, physical security, and old-host disablement. | More stable host operations but adds patching, monitoring, migration, and recovery responsibility. | Best future host consistency; not itself a scheduler and must retain the same idempotency contract. |

Apple's current Service Management API can register, unregister, and inspect a
LaunchAgent that is packaged with an application. The current Chief of Staff
is a local CLI rather than a signed app bundle, so whether Milestone 12 uses a
user-owned property list initially or first creates a packaged service
boundary remains an implementation-review detail. No packaging expansion is
authorized here. See
[SMAppService](https://developer.apple.com/documentation/servicemanagement/smappservice)
and Apple's
[helper executable guidance](https://developer.apple.com/documentation/servicemanagement/updating-helper-executables-from-earlier-versions-of-macos).

## Decision

Use a user-level macOS `launchd` LaunchAgent in Brad's logged-in GUI session
with calendar triggers at 7:00 a.m. on Monday through Thursday, Saturday, and
Sunday. It invokes one bounded scheduled-generation command and then exits.
Friday has no trigger. The LaunchAgent uses neither `KeepAlive` nor an
always-running worker.

The application—not `launchd`—would remain authoritative for:

- the `America/New_York` briefing date;
- approved-day and catch-up-cutoff eligibility;
- the scheduled-morning idempotency key;
- process locking and duplicate suppression;
- connector preflight and reduced-source policy;
- immutable recorded briefing preservation;
- retry limits;
- safe diagnostics and outcome notification; and
- success, reduced success, missed, and failed state.

The current primary Mac is the approved bounded-trial host. The application
may catch up a sleep-delayed invocation only through 11:00 a.m.
`America/New_York`; afterward it records a miss without retrieving sources.
Application-owned state makes retrieval inert after seven eligible scheduled
dates. A private-safe macOS notification and non-content local status record
surface outcomes.

Installation uses an idempotent, reversible user-owned property list with
exact absolute paths, no secrets, a safe environment allowlist, restrictive
file creation, and private or deliberately discarded process output. A future
Mac mini remains a separately reviewed host migration.

## Why this direction

The LaunchAgent uses the platform's preferred per-user scheduling context,
avoids maintaining an always-running application solely for one daily
invocation, and has better documented sleep/wake behavior than `cron`.
Application-owned idempotency is still mandatory because delayed triggers,
retries, manual runs, and future host migration cannot be made safe by a
scheduler alone.

An always-awake Mac mini is a promising later host, not a competing timer. The
same one-shot LaunchAgent and application safety contract should migrate
without changing product semantics.

## Consequences

- Milestone 12 becomes macOS-specific for its first scheduler.
- The scheduler remains a thin invocation layer; product behavior stays in the
  existing application.
- The selected user must be logged in and the actual host must pass an attended
  Keychain, network, sleep/wake, privacy, and notification trial.
- Sleep-delayed triggers may be eligible for one catch-up; powered-off misses
  require the application policy and cannot be assumed recoverable.
- A dedicated Mac mini can improve availability later but requires a separate
  migration and host-readiness gate.
- Installation and removal must be explicit, reversible, and testable.
- Installation may proceed only after the implementation, synthetic gate,
  repository-cleanliness check, connector-health check, and exact Calendar
  continuity exercise required by Milestone 12.
- The installed trial remains self-limiting after seven eligible dates and
  cannot become routine operation without Brad's further approval.

## Dependencies

- [Scheduled Morning Generation v1](../product/features/scheduled-morning-generation-v1.md)
- [ADR-0009: Connector Authorization Continuity](0009-choose-connector-authorization-continuity.md)
- [Milestone 12 decision checklist](../product/features/scheduled-morning-generation-decision-checklist.md)

## Current implementation status

Accepted for implementation and the bounded trial. This decision record alone
does not install a scheduler, change a credential, retrieve a source, or
accept routine unattended operation after the trial.
