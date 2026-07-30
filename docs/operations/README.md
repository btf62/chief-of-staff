# Operations

- **Status:** Draft
- **Owner:** TBD
- **Last updated:** 2026-07-30

This directory is the authoritative location for operational policies and
deployment documentation. The deployment model is now established; operational
content should be added as implementation reaches the roadmap milestone that
requires each policy or procedure.

## Topics to define

- Service ownership and support expectations
- Environments and release process
- Configuration and secret management
- Monitoring, alerting, and service-level objectives
- Incident response and escalation
- Backup, restoration, and disaster recovery
- Data retention and deletion
- Access reviews and audit evidence

## Runbooks

Step-by-step operational procedures belong in
[the runbooks directory](runbooks/README.md). No deployment runbook exists
because the system is not deployed or approved for operational use.

## Implemented foundations

- [Local state operations](local-state.md) — SQLite migrations, inspection,
  recurrence projection, deletion, retention pruning, reset, and current
  limitations
- [Local web interface operations](local-web.md) — loopback launch, stop,
  reopen, data location, startup diagnostics, and security boundary
- [Deterministic briefing operations](deterministic-briefing.md) — synthetic
  invocation, source coverage, composition, validation, and current
  limitations
- [First safe connector operations](first-safe-connectors.md) — approved
  repository reads, OAuth and Keychain boundaries, bounded Calendar trial,
  validation, and mandatory stop
- [Milestone 8 live-evaluation gate](milestone-8-live-evaluation-gate.md) —
  accepted and exercised OpenAI project, retention, cost, request, and
  synthetic-comparison boundary plus Brad's task-specific Luna selection; the
  one-time authorization is consumed
