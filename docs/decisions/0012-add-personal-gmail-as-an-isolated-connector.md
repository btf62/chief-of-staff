# ADR-0012: Add Personal Gmail as an Isolated Connector Instance

- **Status:** Accepted
- **Date:** 2026-08-02
- **Owner:** Brad

## Context

The accepted Daily Briefing MVP reads Work Gmail but does not see requests,
commitments, preparation, or approaching work that exists only in Brad's
personal mailbox. Brad has decided that Personal Gmail should become the next
product input after the active Milestone 12 scheduled trial.

Gmail is already implemented as a provider, and the architecture already
distinguishes providers from independently authorized connector instances.
Treating two mailboxes as one source would nevertheless create unacceptable
ambiguity around account authorization, work and personal context, coverage,
retention, disconnection, and source provenance. Personal correspondence also
creates a higher risk of collecting unnecessary family, medical, financial,
or other sensitive information.

The active seven-date Milestone 12 trial has a fixed accepted source set.
Changing that set during the trial would weaken its evaluation and silently
expand scheduled access before Personal Gmail has passed its own trust gate.

## Decision drivers

- Surface important personal requests and commitments without creating a
  general personal-inbox summary.
- Preserve a clear boundary between work and personal records.
- Reuse the proven Gmail provider implementation without sharing authority or
  state between accounts.
- Minimize personal and third-party information throughout retrieval,
  persistence, inference, and presentation.
- Keep the current scheduled trial comparable to its accepted baseline.
- Require explicit human review before Personal Gmail participates in
  unattended scheduled generation.

## Options considered

### Option 1: Keep Personal Gmail deferred

This preserves the smallest credential and privacy footprint, but leaves a
known blind spot for personal commitments and requests that may materially
affect Brad's day.

### Option 2: Treat Work and Personal Gmail as one connector

One logical Gmail source would reduce visible configuration, but it would
encourage shared credentials, provider-global state, combined coverage, and
unsupported cross-account identity or thread merging. A failure, correction,
or retention exception could silently affect both domains.

### Option 3: Add an isolated Personal Gmail connector instance

Reuse the Gmail provider implementation while assigning Personal Gmail its
own connector identity, authorization, configuration, coverage, provenance,
retention, and failure behavior. Introduce it after a separate bounded trust
gate and leave the active Milestone 12 source set unchanged.

## Decision

Chief of Staff will add Personal Gmail as `gmail:personal`, a separately
authorized connector instance using the safe alias `Personal Gmail` and the
personal domain classification. It will reuse the Gmail provider's read-only
transport, MIME minimization, and deterministic detection where those
behaviors satisfy the Personal Gmail specification. It will not reuse or
inherit the `gmail:work` authorization or account configuration.

The Personal Gmail instance must have its own:

- Explicitly selected and confirmed Google account.
- Appropriate Brad-controlled OAuth project and Desktop client.
- Exact `https://www.googleapis.com/auth/gmail.readonly` grant.
- Instance-specific access and refresh credentials in macOS Keychain.
- Non-secret authorization and health metadata in SQLite.
- Retrieval windows, queries, caps, exclusions, retention, and deletion
  policy.
- Coverage, provenance, correction, failure, revocation, and disconnection
  behavior.

Personal Gmail remains read-only. It may list messages, inspect selected
metadata, and retrieve bounded inline content only when required by the
accepted selection policy. It must not send, draft, forward, label, archive,
delete, mark read or unread, access settings, register watches, retrieve
attachments, follow external links, or use a Google Drive scope.

The initial product purpose is limited to precision-first detection of direct
human requests, explicit commitments, supported deadlines, acknowledgment
obligations, and preparation. It is not a personal-inbox digest. Promotional,
social, forum, spam, trash, draft, bulk, and unsupported automated content
must not become actionable briefing conclusions. Medical, financial,
confidential family, and similarly sensitive content must not be persisted or
displayed without a later explicit product decision. Personal Gmail evidence
must not enter hosted inference under the current authorization.

Work and personal messages must retain separate source records and provenance.
The application must not merge people, threads, commitments, evidence,
corrections, or coverage across the two instances merely because they share a
provider or apparent identity.

Milestone 13 will finalize the exact Personal Gmail retrieval and retention
policy, implement and test the isolated instance, and conduct one attended,
bounded live trial. No Personal Gmail authorization or retrieval is authorized
before those documented gates pass. The active Milestone 12 trial from
2026-08-03 through 2026-08-10 remains unchanged.

After Brad reviews and accepts the Milestone 13 evidence, Personal Gmail may
enter a separate bounded scheduled trial. It will initially be an optional
action source: its failure must be disclosed but must not prevent a briefing
when the existing accepted source-sufficiency rule is otherwise satisfied.
Routine scheduled use still requires explicit acceptance.

## Consequences

### Positive

- The briefing can eventually include important personal commitments and
  requests that the current source set cannot see.
- Gmail provider code can be reused while authorization, state, and evidence
  remain isolated per account.
- Coverage can distinguish an empty Personal Gmail result from a failed Work
  Gmail result and vice versa.
- The current scheduled trial retains its accepted and comparable boundary.

### Negative

- Chief of Staff will hold another durable credential for a highly sensitive
  source.
- The personal-account OAuth audience, publishing, verification, and refresh
  posture must be resolved before durable operation.
- Multi-instance execution, coverage, review, retention, and correction paths
  require additional implementation and testing.
- Conservative sensitivity exclusions may omit useful personal information.

### Follow-up

- Complete the Milestone 12 post-trial review before beginning Milestone 13
  implementation.
- Finalize the Personal Gmail query, limits, sensitive-content handling,
  retention, and OAuth registration before live authorization.
- Pass synthetic isolation and privacy tests before one bounded live trial.
- Require Brad's review before adding Personal Gmail to scheduled generation.

## Related records

- [ADR-0004: Adopt SQLite and a Bounded Local Data Lifecycle](0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
- [ADR-0005: Adopt OAuth and macOS Keychain for Connector Credentials](0005-adopt-oauth-and-macos-keychain.md)
- [ADR-0011: Require Durable Authorization for Scheduled Connectors](0011-require-durable-authorization-for-scheduled-connectors.md)
- [Gmail connector specification](../architecture/connectors/gmail.md)
- [Product requirements](../product/requirements.md)
- [Implementation roadmap](../roadmap.md)
