# Milestone 12 Decision Checklist

- **Status:** Proposed
- **Owner:** Brad
- **Last updated:** 2026-07-30

Brad must decide each item before Scheduled Morning Generation implementation
or installation begins.

| Decision | Recommended option | Principal tradeoff | Brad's decision |
| --- | --- | --- | --- |
| 1. Target host | Use the current primary Mac for a bounded attended trial; prefer an always-awake Mac mini before routine unattended use. | The current Mac is quickest to validate but can sleep, travel, or be logged out; a Mac mini is more reliable but adds host setup, credential migration, and maintenance. | TBD |
| 2. Scheduled days | Run only on explicitly configured normal workdays; Brad names the exact weekdays. | Fewer approved days reduce unwanted briefings, but configuration must be maintained when rhythms change. | TBD |
| 3. Scheduled time | Choose one `America/New_York` morning time after the host is normally awake and before the briefing loses usefulness. | Earlier is more useful but more vulnerable to sleep, network, and credential availability. | TBD |
| 4. Missed-run/catch-up policy | Permit one catch-up inside a short Brad-approved grace window; record a miss after the cutoff and never backfill silently. | Catch-up improves availability, but a late briefing can be distracting or stale. | TBD |
| 5. Reduced-coverage success | Count a validated reduced-source briefing as success only under an explicit sufficiency rule; decide whether Calendar is mandatory. | Graceful degradation preserves usefulness, but accepting too little coverage can make the briefing misleading. | TBD |
| 6. Google Calendar continuity | Approve a separate bounded move to refreshable authorization under the unchanged read-only Calendar scope. | Fewer interruptions require a longer-lived credential and therefore more durable authority. | TBD |
| 7. Jira continuity | Initially keep short-lived Jira access and omit Jira honestly when expired; consider `offline_access` only if omissions materially reduce value. | Least authority causes periodic missing Jira coverage; offline access improves continuity but expands scope and durable authority. | TBD |
| 8. Success/failure notification | Use a private-safe local macOS notification plus an inspectable non-content local status record. | Immediate visibility adds a local notification surface that must avoid private content. | TBD |
| 9. Bounded scheduled trial | Require an attended, time-bounded trial before any unattended schedule is approved. | Acceptance takes longer, but verifies host, wake, Keychain, network, idempotency, and notification behavior safely. | TBD |

Related design:

- [Scheduled Morning Generation v1](scheduled-morning-generation-v1.md)
- [ADR-0009: Connector Authorization Continuity](../../decisions/0009-choose-connector-authorization-continuity.md)
- [ADR-0010: Scheduled Morning Generation Mechanism](../../decisions/0010-choose-scheduled-morning-generation-mechanism.md)
