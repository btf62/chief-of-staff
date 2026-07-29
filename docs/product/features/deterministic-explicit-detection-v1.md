# Feature: Deterministic Explicit Detection v1

- **Status:** Accepted
- **Version:** 1
- **Owner:** Brad
- **Last updated:** 2026-07-29

## Summary

Milestone 7 adds precision-first, deterministic detection of explicit
requests, promises, deadlines, acknowledgment obligations, meeting
preparation, people waiting, and endangered source-owned work. It does not use
hosted inference, embeddings, opaque scoring, or speculative identity
matching.

The feature favors false negatives over false positives. Missing or ambiguous
evidence produces `insufficient_evidence`; it never becomes an explicit claim.

## Problem and evidence

Daily Briefing v1 can already retrieve the complete MVP input set and present
source-owned Calendar, Todoist, Jira, repository, and Work Gmail facts. Brad
accepted the Milestone 6 Work Gmail review as logically sound. The next useful
step is to make the narrow deterministic conclusions more complete and
explainable without crossing into contextual model inference.

## Goals

- Identify only explicit, attributable, source-backed obligations.
- Preserve authoritative links and source-specific facts.
- Distinguish source facts, deterministic conclusions, future contextual
  inference, and insufficient evidence.
- Support local correction recurrence for new Gmail conclusion types.
- Provide a representative synthetic evaluation corpus before live use.

## Non-goals

- Contextual model inference or hosted inference.
- Treating age, assignment, priority, or overdue state as a human promise.
- Inferring preparation from a Calendar title.
- Broad natural-language interpretation, embeddings, or opaque scoring.
- External writes, notifications, scheduling, or unattended operation.

## Evidence classifications

Every evaluated item has exactly one classification:

| Classification | Meaning |
| --- | --- |
| `direct_source_fact` | A fact supplied directly by its authoritative source |
| `explicit_deterministic_conclusion` | A conclusion supported by a narrow documented rule and authoritative evidence |
| `contextual_inference` | A future Milestone 8 inference; not produced in Milestone 7 |
| `insufficient_evidence` | Evidence is missing, ambiguous, incomplete, contradicted, or outside a supported rule |

Persisted Milestone 7 conclusions remain `explicit` in the existing
application-owned conclusion model. The more precise evidence classification
is attached to deterministic detection and review output; it does not relabel
source facts as conclusions.

## User scenarios

1. Given a direct human email with an explicit request and no later bounded
   outbound response, the briefing may show People Waiting with the Gmail link.
2. Given a sent message containing Brad's current attributable promise, the
   system records an explicit commitment.
3. Given that promise plus a tightly supported date expression, the system may
   identify a commitment at risk when the date is due soon or overdue.
4. Given an explicit request to acknowledge receipt, the system labels the
   obligation as acknowledgment rather than a generic question.
5. Given explicit preparation content in an approved source or an explicitly
   linked source requirement, the briefing may show Preparation Needed.
6. Given weak, stale, incomplete, quoted, signature-only, or conflicting
   evidence, the system returns insufficient evidence.

## Requirements

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| M7-001 | Direct inbound requests require an explicit supported request phrase and no later bounded outbound response. | Synthetic direct-request and answered-thread cases pass. |
| M7-002 | Sent commitments require a current attributable first-person promise. | Quoted-history, signature-only, and vague-language cases remain negative. |
| M7-003 | Deadline parsing supports only `by today`, `by tomorrow`, an ISO date, a full month and day with optional year, or a named weekday. | Supported expressions normalize deterministically; ambiguous relative expressions remain undated. |
| M7-004 | Explicit acknowledgment requests are distinguishable from other direct requests. | Acknowledgment phrases produce an explicit acknowledgment obligation with authoritative evidence. |
| M7-005 | Meeting preparation requires explicit source preparation content or an explicit stable linked-source requirement. | Explicit Calendar/source preparation displays; important-sounding Calendar titles alone do not. |
| M7-006 | Task-system assignment or overdue state cannot create People Waiting or a human commitment. | Todoist and Jira negative cases pass. |
| M7-007 | Endangered Jira work remains a Jira-owned source-risk claim. | The briefing states that the result is not a human-promise claim. |
| M7-008 | Every displayed conclusion retains authoritative provenance. | Validation rejects missing evidence links. |
| M7-009 | Unsupported evidence is classified as `insufficient_evidence`. | Rejected review cases expose the classification and a safe reason. |
| M7-010 | Local disposition recurrence applies to materially unchanged Gmail request, commitment, and preparation conclusions. | Synthetic suppress-and-replace tests pass. |
| M7-011 | Cross-source relationships require explicit identifiers or source links and preserve conflicts. | Title similarity alone does not merge; linked records retain all source links and conflicting dates. |
| M7-012 | Private live examples never enter Git fixtures. | Credential/private-data scans and repository review remain clean. |

## Deterministic rules

- Email age alone is insufficient.
- A question mark alone is insufficient.
- Calendar titles alone cannot create preparation requirements.
- Assignment alone cannot create People Waiting.
- Todoist or Jira overdue status alone cannot create a human commitment.
- Quoted history and signatures cannot create a promise.
- Direct inbound requests require no later bounded outbound response.
- A thread whose relevant reply history begins outside the bounded evidence
  window is insufficient.
- Instruction-like email content remains inert and is insufficient evidence.
- Ambiguous relative dates do not receive a deadline.
- Conflicting authoritative facts remain visible and are not silently merged.

## Review artifact

The private mode-`0600` review groups:

- displayed conclusions;
- supported but nondisplayed conclusions;
- rejected and insufficient-evidence cases;
- correction recurrence results; and
- source-coverage limitations.

It includes only the minimum evidence needed for Brad's trust decision and
does not become an inbox summary.

## Evaluation

The privacy-safe synthetic corpus covers the required positive and negative
scenarios for People Waiting, explicit commitments, commitment at risk,
preparation, deadline parsing, source-owned risk, and insufficient evidence.
Each category is evaluated separately. A false positive fails the gate even
when aggregate accuracy would otherwise appear high.

## Constraints and risks

- Work Gmail retains the accepted metadata-first retrieval, 120-body cap,
  MIME minimization, attachment exclusion, and partial-coverage disclosure.
- Live Calendar descriptions remain discarded; synthetic Calendar preparation
  represents an explicit approved field, not authorization to retain provider
  descriptions.
- Milestone 7 is read-only toward all external systems.
- Personal Gmail, Google Drive, Asana, Rock, hosted inference, and new
  connectors remain excluded.

## Open questions

- None for implementation. Brad's review of the private Milestone 7 evidence
  remains the acceptance gate.

## Related documents

- [Product requirements](../requirements.md)
- [Daily Briefing v1](daily-briefing-v1.md)
- [Work Gmail connector](../../architecture/connectors/gmail.md)
- [Implementation roadmap](../../roadmap.md)
- [ADR-0004: SQLite and bounded local data lifecycle](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
