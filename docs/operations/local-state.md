# Local State Operations

- **Status:** Draft
- **Owner:** Brad
- **Last updated:** 2026-07-27

This document describes the implemented local-state foundation and minimized
task-source extensions. It operates within
[ADR-0004](../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
and does not authorize production data, backups, connector caching, or broader
product memory.

## Storage boundary

Chief of Staff uses one application-owned SQLite database at the explicit path
provided by `CHIEF_OF_STAFF_DATABASE_PATH`. The application does not select a
machine-specific default. Database files and common SQLite suffixes are ignored
by Git.

Opening the database:

- Creates the parent directory when needed.
- Enables and verifies SQLite foreign-key enforcement.
- Applies pending packaged SQL migrations in version order.
- Verifies the name and SHA-256 checksum of every previously applied
  migration.
- Rejects unknown, reordered, duplicate, or modified migration history.

Migrations use explicit transactions. A failed migration or state mutation is
rolled back.

## Persisted records

The implemented schema stores:

- Connector-run metadata, approved scope descriptions, coverage, and
  freshness.
- Briefing-run metadata and connector-run associations.
- Minimal source references, optional bounded excerpts, and evidence
  fingerprints.
- Explicit or inferred conclusions with processing versions.
- Ordered conclusion-to-evidence links.
- Append-oriented correction and disposition events.
- Selected normalized Todoist task facts and only their referenced project,
  section, and label context.
- Selected normalized Jira issue facts, labels, and issue-link references.

It does not define tables for credentials, tokens, raw response pages,
continuation cursors, full source payloads, attachments, or connector caches.

## Inspection and recurrence

`StateStore.inspect_state()` returns non-content record counts and migration
versions. `StateStore.inspect_conclusion()` returns one conclusion, its ordered
source evidence, and its complete disposition history.

Recurrence projection uses the conclusion's material-evidence fingerprint:

- Unseen or confirmed evidence remains eligible to appear.
- Corrected evidence returns the approved replacement.
- Dismissed, delegated, rescheduled, completed, or intentionally abandoned
  evidence is suppressed while the fingerprint remains unchanged.
- Materially changed evidence receives a new fingerprint and may be
  reconsidered.

This is an explicit local overlay. It never changes an external source.

## Deletion and reset

The store supports:

- Deleting only a conclusion's disposition history.
- Deleting a conclusion and its dependent history.
- Deleting source evidence and any conclusion left without evidence.
- Deleting a briefing-run record.
- Pruning bounded connector- and briefing-run metadata.
- Resetting all application-owned state while preserving migration history.

Deleting old run metadata does not delete still-useful correction evidence.
The relevant connector or briefing reference becomes `NULL`, while the
minimal provenance and recurrence state remain until explicitly deleted.

No tombstone remains after an explicit conclusion or evidence deletion.
Deleting local state does not modify an authoritative external system.

## Current limitations

- Inspection and deletion are Python APIs exercised through synthetic tests;
  there is no user interface or operator CLI yet.
- Retention pruning requires an explicit caller and is not scheduled.
- Application-managed backup is disabled and undocumented by design.
- The repository contains no runtime database or production fixture.

Run the complete migration and lifecycle test suite with:

```text
make check
```
