# Gmail Connector

- **Status:** Draft
- **Version:** 0
- **Owner:** Brad
- **Last updated:** 2026-07-27

This preliminary specification records the multi-account design boundary for a
future Gmail connector. It does not select final scopes or queries, implement
Gmail access, authorize an account, or approve a live trial.

## Intended source responsibility

Gmail may eventually provide authoritative message and thread facts needed to
identify correspondence context, replies, acknowledgments, communication
commitments, and people who may be waiting on Brad. Chief of Staff may
interpret those facts but must not silently modify, send, label, delete,
archive, or otherwise replace Gmail.

Sent mail is expected to be important for explicit promise and commitment
detection. The evidence rules, search boundary, evaluation standard, and safe
content minimization remain open and must be specified before implementation.

## Two independent connector instances

The anticipated configuration contains two Gmail connector instances served by
one read-only provider implementation:

| Safe alias | Domain | Authorization boundary |
| --- | --- | --- |
| `Work Gmail` | Work | One explicitly confirmed organizational account |
| `Personal Gmail` | Personal | One explicitly confirmed personal account |

Each instance requires its own stable application-owned ID, browser account
confirmation, OAuth grant, account reference, Keychain entries, scopes,
retrieval configuration, freshness, coverage, enabled state, retention policy,
and disconnection path. A grant or failure for one account must not affect the
other.

Briefings and operational reports display the safe alias rather than a full
address. Provider account identity may be retained only as private non-secret
authorization metadata needed to prevent wrong-account access.

## Domain and provenance boundary

Work and personal message facts remain distinct through retrieval,
normalization, persistence, inference, correction state, and presentation.
Every record and conclusion retains its connector-instance ID, domain, source
identifier, authoritative link, freshness, and coverage.

No actor, address, conversation, thread, commitment, or task is merged across
accounts automatically. When strong evidence later supports an association,
both records and both account contexts remain inspectable. A unified briefing
may present approved work and personal items together without erasing their
domain or account provenance.

Hosted-inference evidence packets must not mix work and personal content by
default. Approval of a sensitive-content category, retention exception, cache
exception, label, or search window for one account does not authorize it for
the other.

## Authorization questions

Authorization must follow
[ADR-0005](../../decisions/0005-adopt-oauth-and-macos-keychain.md) and the
[connector-instance contract](README.md). The following remain explicitly
unresolved:

- The OAuth application registration and owner for each account domain.
- Whether the work and personal instances require separate OAuth application
  registrations or may use one appropriately owned private registration.
- The exact least-privilege read-only Gmail scopes.
- Provider sensitivity or verification requirements.
- Exact redirect, PKCE, offline-access, refresh, revocation, and reauthorization
  behavior.
- The private account-confirmation mechanism.

No scope, registration owner, or live authorization is accepted by this draft.
Client secrets, access tokens, and refresh tokens will belong only in separate
macOS Keychain entries keyed by connector instance.

## Retrieval questions

Each account must have independently approved retrieval rules. Open questions
include:

- Search windows and freshness thresholds.
- Included and excluded labels.
- Inbox, sent-mail, archived-message, spam, and trash boundaries.
- Thread versus individual-message retrieval.
- Reply and acknowledgment detection.
- Explicit and inferred commitment detection in sent mail.
- Quoted-history, signature, attachment, and tracking-data minimization.
- Bounded persistence and deletion behavior for message-derived evidence.

Attachments and external links are excluded unless a later specification
justifies and approves them.

## Future implementation and live-access gate

Before any Gmail implementation or authorization:

1. Resolve the open scope, registration, query, sensitivity, and retention
   questions.
2. Implement one read-only provider connector serving independently configured
   instances.
3. Prove separate OAuth and Keychain handling, account confirmation, coverage,
   provenance, domain isolation, failure handling, and disconnection with
   synthetic contract tests.
4. Evaluate commitment and People Waiting inference against representative,
   human-reviewed scenarios with precision prioritized over recall.
5. Define one bounded live-access trial and obtain explicit approval for each
   account separately.

No Gmail access is authorized by this document.

## Related documents

- [Technical Architecture](../overview.md)
- [Connector Specifications](README.md)
- [Daily Briefing v1](../../product/features/daily-briefing-v1.md)
- [ADR-0004: SQLite and Bounded Local Data Lifecycle](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
- [ADR-0005: OAuth and macOS Keychain](../../decisions/0005-adopt-oauth-and-macos-keychain.md)
- [ADR-0006: Provider-Neutral Inference](../../decisions/0006-adopt-provider-neutral-inference-with-openai.md)
