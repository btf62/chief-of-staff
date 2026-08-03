# Milestone 12 Decision Checklist

- **Status:** Accepted
- **Owner:** Brad
- **Last updated:** 2026-08-02

Brad approved each operating decision below for the bounded seven-eligible-date
Milestone 12 trial. These decisions authorize implementation, one exact-scope
Calendar and Jira continuity exercises, and installation on the approved trial
host. They do not accept routine unattended operation after the trial.

| Decision | Recommended option | Principal tradeoff | Brad's decision |
| --- | --- | --- | --- |
| 1. Target host | Use the current primary Mac for the bounded trial; prefer an approved always-awake Mac mini before routine unattended use. | The current Mac can sleep, travel, power off, or be logged out; a future Mac mini adds migration and maintenance work. | Accepted |
| 2. Scheduled days | Run Monday–Thursday, Saturday, and Sunday. Friday is ineligible. | The schedule follows Brad's approved work rhythm while preserving Friday as a day off. | Accepted |
| 3. Scheduled time | Trigger at 6:00 a.m. in `America/New_York`. | An early briefing is more useful but depends on host, network, and credential readiness. | Accepted; changed from 7:00 a.m. before the first trial date |
| 4. Missed-run/catch-up policy | Permit one delayed invocation through 11:00 a.m. local time; after that, record a miss without retrieval or generation. | A bounded catch-up tolerates sleep while preventing stale or silent backfill. | Accepted |
| 5. Reduced-coverage success | Require repository context, usable Calendar coverage, and at least one usable source from Work Gmail or Todoist. Jira is optional. | This permits a useful degraded run without allowing Calendar loss or loss of both primary action sources to appear successful. | Accepted |
| 6. Google Calendar continuity | Perform one bounded move to refreshable authorization under the unchanged exact read-only Calendar scope. | Continuity improves, but a refresh credential creates longer-lived authority that must remain in Keychain. | Accepted |
| 7. Jira continuity | Add `offline_access` for rotating refresh continuity while retaining the exact `read:jira-work` data permission, selected site, `NRC` project, and fixed query. | Durable authority requires stronger Keychain, rotation, revocation, and readiness controls. | Revised and accepted 2026-08-02 |
| 8. Success/failure notification | Use a private-safe local macOS notification plus an inspectable non-content local status record. | Immediate visibility adds a notification surface that must reveal no source or briefing content. | Accepted |
| 9. Bounded scheduled trial | End automatically after seven eligible scheduled local dates; require Brad's explicit acceptance or extension afterward. | The trial can include missed or failed dates, but it cannot silently become permanent. | Accepted |

Calendar, Work Gmail, Todoist, and Jira must each have healthy, exact-boundary
refresh continuity before scheduled setup is ready. Runtime provider failures
may still produce honest reduced coverage under Decision 5. No other account,
scope, connector, source, or durable authorization is approved.

Related design:

- [Scheduled Morning Generation v1](scheduled-morning-generation-v1.md)
- [ADR-0011: Durable Scheduled Connector Authorization](../../decisions/0011-require-durable-authorization-for-scheduled-connectors.md)
- [ADR-0010: Scheduled Morning Generation Mechanism](../../decisions/0010-choose-scheduled-morning-generation-mechanism.md)
