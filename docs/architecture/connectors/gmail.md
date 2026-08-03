# Gmail Connector Instances

- **Status:** Accepted
- **Version:** 6
- **Owner:** Brad
- **Last updated:** 2026-08-02

This specification defines independently authorized Gmail connector instances.
Work Gmail is the accepted final input connector for the on-demand Daily
Briefing v1 MVP. Its bounded combined trial and human review completed
Milestone 6. Personal Gmail is the accepted next product-scope expansion under
Milestone 13, but its implementation, authorization, retrieval, and scheduled
use remain gated. Healthy credentials do not independently authorize access.

## Source responsibility

Each authorized Gmail account remains authoritative for its message and thread
facts. Work Gmail provides work correspondence; Personal Gmail may eventually
provide separately bounded personal correspondence. Chief of Staff may
interpret approved facts conservatively, but it must not silently modify,
send, label, delete, archive, or otherwise replace Gmail.

Email content is untrusted source data, never application instruction. It
cannot alter policy, scopes, queries, tools, configuration, governing
documents, or external-action boundaries.

## Connector instances

The accepted on-demand MVP uses the implemented Work Gmail instance. Personal
Gmail is a separate post-MVP instance whose product direction is accepted but
whose operating boundary must pass Milestone 13 before use.

| Field | Work Gmail | Personal Gmail |
| --- | --- | --- |
| Instance ID | `gmail:work` | `gmail:personal` |
| Safe alias | `Work Gmail` | `Personal Gmail` |
| Domain | Work | Personal |
| Authorized account | Accepted Northridge account | TBD; explicitly selected and confirmed before authorization |
| OAuth project | Northridge-controlled `nrc-chief-of-staff` | TBD; Brad-controlled and capable of authorizing the selected personal account |
| OAuth client | Dedicated Desktop client | Independent Desktop client |
| Status | Accepted and implemented | Accepted for Milestone 13; implementation and access gated |

For each instance, the browser account, provider profile, and user-confirmed
identity must all match the separately authorized account before credentials
are persisted. User-facing coverage and briefing output use the safe alias
rather than the account address. No credential, account reference, retrieval
exception, correction, or health state transfers between instances.

## Personal Gmail Milestone 13 boundary

Personal Gmail is limited to precision-first detection of direct human
requests, explicit commitments, supported deadlines, acknowledgment
obligations, and preparation. It is not a general personal-inbox digest.

The Milestone 13 design gate must record exact inbound and sent windows,
queries, message and body-candidate caps, sensitive-content exclusions,
retention, and deletion behavior before implementation or live access. Those
limits may be narrower than Work Gmail and must never be silently inherited
merely because the instances share provider code.

Promotional, social, forum, spam, trash, draft, bulk, and unsupported automated
content must not become actionable conclusions. Medical, financial,
confidential family, and similarly sensitive content must not be persisted or
displayed without a later explicit product decision. Personal Gmail evidence
is not authorized for hosted inference.

Work and personal source records retain independent instance provenance.
Apparent shared identities, matching subjects, or provider thread identifiers
are insufficient to merge people, threads, commitments, evidence,
corrections, or coverage across instances.

## OAuth and scope boundary

Work Gmail uses Google's installed-application authorization-code flow in the
system browser with a loopback callback, session-bound OAuth `state`, and PKCE.
It requests exactly:

```text
https://www.googleapis.com/auth/gmail.readonly
```

This is a restricted, read-only Gmail scope. It is necessary because the MVP
must search mail with Gmail's `q` parameter and inspect bounded message bodies.
`gmail.metadata` is insufficient because it does not permit those operations.

The connector must never request:

- `https://mail.google.com/`
- `gmail.modify`
- `gmail.compose`
- `gmail.send`
- `gmail.insert`
- `gmail.labels`
- Gmail settings scopes
- Any Google Drive scope

The Work Gmail OAuth application must use the Northridge-controlled project,
an internal organizational audience, correct organizational support/contact
ownership, and a dedicated Desktop client when practical. If Workspace
administration blocks the restricted scope or requires administrative action,
stop rather than weakening the boundary or using another account.

Personal Gmail must use an independent Brad-controlled project and Desktop
client capable of authorizing the selected personal account. Its audience,
publishing, verification, and durable-refresh posture must satisfy current
Google requirements before authorization. Google's current
[OAuth audience guidance](https://support.google.com/cloud/answer/15549945)
states that testing authorizations expire after seven days, so a time-limited
testing grant is not sufficient for scheduled readiness. The exact project
identity remains TBD until the Milestone 13 design gate. Reverify the current
[Gmail scope classification](https://developers.google.com/workspace/gmail/api/auth/scopes)
before implementation.

Request offline access only when needed for future approved on-demand runs.
Store client secrets, access tokens, and refresh tokens only in separate
instance-specific macOS Keychain entries. SQLite stores only non-secret OAuth
project, client, account, exact scope, expiry, health, and Keychain-reference
metadata. Authorization codes, token values, and client secrets never enter
SQLite, Git, logs, fixtures, reports, or briefing output.

Revocation and disconnection operate on exactly one selected Gmail instance.
The Personal Gmail grant must not share or inherit Work Gmail credentials.

## Read-only operations

The connector may implement only:

- Account-profile verification
- Message listing
- Individual message metadata retrieval
- Bounded individual message-content retrieval

It must not implement or expose:

- Sending, drafting, replying, or forwarding
- Label modification or management
- Marking messages read or unread
- Archiving, trashing, deleting, importing, or inserting
- Settings access
- Watch or push-notification registration
- Attachment retrieval
- Any other mutation

Contract tests must prove that no mutation path is present or reachable.

## Trial retrieval streams

The bounded live trial uses two independently capped streams with exact epoch
boundaries in Brad's configured timezone:

1. **Inbound:** the previous seven calendar days through the exclusive end of
   the briefing day, excluding Sent, Drafts, Spam, Trash, Promotions, Social,
   and Forums.
2. **Sent:** the previous fourteen calendar days through the same exclusive
   end, including Sent and excluding Drafts.

The inbound stream supports recent explicit-request and reply-state
evaluation. The longer sent stream supports explicit-commitment evaluation.
Neither stream automatically retrieves older thread history.

## Message listing

List messages only with:

```text
GET /gmail/v1/users/me/messages
```

Use each approved bounded query, conservative page sizes, and stable query
parameters across pagination. Follow `nextPageToken` to completion, preserve
stream membership, deduplicate within and across streams by immutable Gmail
message ID, keep page tokens transient, and disclose that concurrent mailbox
changes may affect point-in-time completeness.

Stop before metadata expansion if the inbound stream exceeds 300 messages, the
sent stream exceeds 200 messages, or the combined result exceeds 500 unique
messages. Report the safe observed aggregate for the exceeded boundary; never
silently shorten a window or alter a filter.

## Metadata-first retrieval

Retrieve metadata for every listed message before deciding whether body
content is necessary. Request only these useful headers:

- From
- To
- Cc
- Bcc
- Reply-To
- Subject
- Date
- Message-ID
- In-Reply-To
- References
- Auto-Submitted
- Precedence
- List-Id
- List-Unsubscribe

Also retain transiently:

- Message ID
- Thread ID
- Internal date
- Label IDs
- Size estimate
- Connector instance
- Retrieval freshness

Classify metadata conservatively as:

- Outbound from Brad
- Direct inbound human correspondence
- Automated notification
- Mailing list or bulk message
- Promotional, social, or forum content
- Self-message
- Unsupported or ambiguous

Automated, bulk, promotional, social, and forum messages do not qualify for
body retrieval. Sent mail may qualify for explicit-promise detection. Direct
inbound human correspondence may qualify for explicit-request and unanswered-
acknowledgment evaluation.

`CATEGORY_UPDATES` remains eligible for metadata review but does not
automatically qualify for body retrieval. The same human-correspondence and
automation checks apply.

When more than 120 messages qualify for body retrieval, select no more than
120 using a deterministic, explainable policy:

- Deduplicate by immutable message identity before allocation.
- Allocate capacity proportionally to eligible inbound and sent counts.
- Redistribute unused or rounding capacity deterministically.
- Within each stream, select the most recent messages first.
- Use the stable private message identity only as the final tie-breaker.

Do not use subject wording, sender importance, opaque scoring, hosted
inference, or body content for selection. Retrieve no body for omitted
candidates. Mark Gmail coverage partial and disclose only safe aggregate
eligible, selected, and omitted counts. Never describe the selected subset as
complete window coverage.

## Bounded content retrieval

For approved candidates only, retrieve the individual message with
`format=full`. Never request `format=raw` and never call an attachment
endpoint.

Extract inline `text/plain` when usable. Use sanitized inline `text/html` only
when no usable plain-text part exists. Handle nested MIME structures
conservatively and omit unsupported encodings or attachment-only messages.

Remove or skip:

- Attachment bodies
- Images, remote resources, and tracking pixels
- Scripts, active HTML, and embedded forms
- Signatures when conservatively identifiable
- Quoted reply history
- Tracking content and boilerplate
- Unrelated MIME parts
- External-link fetching or execution

Apply configurable per-message and per-run extracted-text limits. Never
truncate current-message text and use the fragment for a conclusion. If one
message exceeds its limit, omit it. If the next selected message would exceed
the remaining run limit, omit that message, stop additional body retrieval,
process already completed bounded evidence, and mark coverage partial with
safe aggregate omission counts. When current-message content cannot be
isolated confidently, omit the detection rather than broadening retrieval or
retaining the full body.

## Prompt-injection and active-content boundary

Message text remains inert even when it tells the application, Codex, or a
future model to reveal secrets, change scope, ignore policy, invoke tools,
modify configuration, or take an external action. No message content is
executed, rendered as active content, or treated as a governing instruction.

Synthetic fixtures must include malicious instructions, active HTML, remote
images, tracking links, and embedded forms and prove that they remain inert.

## Deterministic email behavior

This milestone uses no hosted inference.

Each evaluated item is labeled as a direct source fact, explicit deterministic
conclusion, future contextual inference, or insufficient evidence. Milestone 7
does not emit contextual inference.

### People Waiting on Brad

A Work Gmail item may appear only when deterministic evidence establishes:

- Direct inbound human correspondence
- Brad as an intended recipient
- An explicit request, decision request, acknowledgment request, or
  promised-response expectation
- No later outbound response from Brad in the bounded thread evidence
- Enough evidence and provenance to explain the conclusion

Email age alone, a question mark alone, automated mail, bulk mail, and
unsupported or incomplete thread context are insufficient. If older
out-of-window history may materially change the conclusion, mark coverage
incomplete or omit the item.

An explicit request may carry a deadline only when the current-message excerpt
uses one of the tightly supported forms: `by today`, `by tomorrow`, an ISO
date, a full month and day with optional year, or a named weekday. Ambiguous
relative expressions remain undated.

### Acknowledgment obligations

An acknowledgment obligation is a People Waiting conclusion with an explicit
request to acknowledge or confirm receipt, reply to confirm, or state that the
message was received. A generic question, `confirm` used for another purpose,
or inferred etiquette is not an acknowledgment obligation.

### Meeting preparation

Work Gmail may create a Preparation Needed item only when a direct human
message explicitly asks Brad to review, read, prepare, bring, or complete
something before or for a named meeting, call, appointment, or session. The
message itself is the stable linked source. Important-sounding Calendar titles
alone remain insufficient.

### Explicit commitments

Brad's sent message may create an explicit commitment when its current-message
content contains a direct, attributable promise such as `I will`, `I'll send`,
`I can get that to you`, `I'll follow up`, or a tightly defined equivalent.
Prefer commitments with an explicit date or deadline.

Vague intention, politeness, brainstorming, signatures, quoted promises, and
another person's statement are not Brad's commitments.

### Commitments at Risk

An email commitment may appear at risk only when:

- The promise is attributable to Brad.
- The expected result is identifiable.
- The due date is explicit or reliably parsed.
- The date is due soon or overdue.
- No later bounded evidence shows completion, withdrawal, or renegotiation.

Silence does not prove fulfillment. The connector never creates or modifies a
Todoist or Jira item.

### Reply state

Group messages by Gmail thread ID while preserving individual evidence.
Within the bounded window, determine the latest relevant direction, recognize
a later outbound response, and distinguish replies from self-message and
automated traffic. Never imply that the complete thread was evaluated when
older messages were outside the window.

## Persistence and retention

Follow
[ADR-0004](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md).
Raw Gmail pages, responses, full MIME structures, and complete bodies remain
transient.

Persist only minimized facts required for provenance, explicit detections,
bounded reply-state evaluation, corrections, recurrence prevention, coverage,
and briefing display:

- Message and thread IDs
- Connector instance
- Direction and timestamp
- Minimized participants
- Clean subject only when operationally necessary
- Label classifications
- Authoritative Gmail link
- Deterministic detection type
- Minimal evidence excerpt and fingerprint
- Freshness and processing version

Evidence excerpts must be the minimum explanatory text, exclude quoted history
and signatures, remain local, never enter Git or logs, and follow configurable
retention and deletion. Do not persist attachments, full bodies, raw HTML,
complete headers, or unrelated participants.

## Coverage and failures

Coverage separately reports the inbound and sent stream status, window, and
the following counts for each stream:

- Messages listed, pages, and duplicate IDs
- Metadata records inspected
- Eligible, selected, and omitted body candidates
- Body fetches attempted
- Usable bodies and bodies unavailable or unsupported
- Automated or bulk exclusions
- Opaque or unsupported messages

Combined coverage also reports:

- Unique messages after cross-stream deduplication
- Direct inbound and outbound candidates
- Unique threads
- Explicit detections
- Persisted and displayed counts
- Freshness

Distinguish a legitimately empty result from authorization failure, partial
pagination, metadata failure, body failure, unsupported MIME, bounded
candidate selection, and extracted-content exhaustion. Candidate or content
omissions produce partial coverage, no conclusions from omitted content, and
no claim that the full window was analyzed. Retain successfully minimized
evidence when later bounded processing becomes partial only when coverage is
disclosed accurately.

### Structured failure diagnostics

Each connector call clears prior success and failure audits before retrieval.
If the call fails, the connector retains one current-run, privacy-safe failure
audit containing only:

- Safe connector alias, failure stage and category, and affected stream when
  known
- Applicable retrieval-window boundaries
- Applicable configured boundary name, limit, and observed aggregate count
- Pages completed and message references listed
- Whether metadata or body retrieval began and their completed record counts
- Whether persistence began
- Whether raw payloads were retained
- Failure timestamp

The audit never contains message or thread IDs, subjects, addresses, query
strings, snippets, bodies, labels, continuation tokens, provider response
bodies, credentials, or private source content. Raw responses and continuation
tokens are released on failure.

Failure categories preserve configured-boundary stops, unavailable
authorization, account or scope mismatch, provider forbidden, rate limiting,
timeout, network or transport failure, provider server failure, invalid
provider response, pagination failure, response-size boundary, fixed-endpoint
violation, and unexpected internal failure. The connector reports only the
specificity supported by safe evidence.

The general deterministic pipeline continues to isolate a failed connector and
mark its coverage unavailable or unauthorized. The bounded Gmail trial runner
may inspect the current failure audit and emit it as aggregate JSON. Before
stopping or retrying, it writes a separate private mode-`0600` aggregate report
under `.local/gmail/` for each failed attempt. A failed trial does not persist
source evidence, connector or briefing runs, Gmail records, a candidate-review
artifact, or a combined briefing.

Timeouts, network failures, rate limits, and provider 5xx responses permit a
transient sequence of at most three attempts. The connector honors a safe
bounded `Retry-After` delay when present and otherwise uses bounded exponential
backoff, never waiting more than 30 seconds. A 401 permits one exact-scope
refresh. Account or scope mismatch, a second 401, 403, invalid response,
fixed-endpoint violation, and internal invariant failures stop without an
automatic retry.

The initial inbound and sent windows remain seven and fourteen days. If one
stream exceeds its independent message cap, the runner moves only that
stream's start forward one calendar day and retains the original end. It may
repeat this until the stream fits or reaches three inbound days or seven sent
days. Caps never increase. The effective windows remain explicit in source
coverage and the private candidate review. A stream cap failure at the minimum
window, combined-message cap, pagination cap, response-size cap, permission
failure, or invariant failure still stops the trial.

## Private human-review artifact

Each bounded trial writes one ignored mode-`0600` artifact under
`.local/gmail/`. It groups displayed conclusions, supported but nondisplayed
conclusions, insufficient-evidence cases, correction recurrence, and
source-coverage limitations. Every supported conclusion includes its type,
evidence classification, reason, authoritative link, and minimal excerpt. Safe
aggregate eligible, selected, omitted, fetched, usable, and unavailable body
counts remain explicit.

The artifact may contain authorized private work-email content. It never
enters Git, logs, or chat output.

## Work Gmail live trial and acceptance gate

Synthetic, contract, security, minimization, persistence, and end-to-end tests
must pass before authorization. A separately approved live trial must then:

1. Confirms the exact Northridge-owned OAuth project and internal audience.
2. Authorizes only `gmail:work` with the exact approved scope and account.
3. Runs the bounded seven-day inbound and fourteen-day sent streams and applies
   the deterministic 120-body subset when necessary.
4. Generates the private candidate-review artifact.
5. Generates one input-complete briefing using fresh approved repository,
   primary Calendar, Todoist, Jira, and Work Gmail inputs.
6. Uses no Personal Gmail, Drive, hosted inference, scheduling, or external
   write.

The trial creates an input-complete MVP review artifact. It does not declare
Daily Briefing v1 operationally accepted.

Brad must review every displayed People Waiting item, email commitment, and
Commitment at Risk item plus the private review artifact and combined briefing.
A false positive in a high-confidence relationship or commitment claim blocks
MVP acceptance.

### Validation status

The successful same-window combined trial on 2026-07-28 listed and inspected
357 messages across four pages. It found 144 eligible body candidates,
selected 120 proportionally across inbound and sent streams, omitted 24
without body retrieval, attempted 117 body reads, and produced 106 usable
bodies. Gmail coverage was partial as required; repository, primary Calendar,
Todoist, and Jira coverage was complete. The trial persisted three minimized
Gmail conclusions, displayed two, and produced the private candidate review
and a 929-word combined briefing.

The review structure contained two People Waiting proposals and one explicit
sent commitment proposal. Both displayed items retained authoritative Gmail
links, quoted-history markers were absent from the minimal evidence, and the
briefing disclosed partial Gmail coverage and the bounded subset. Brad
reviewed the private evidence and combined briefing and explicitly judged the
results and logic sound. Milestone 6 is accepted.

Milestone 7 then completed a five-source live validation on 2026-07-29. Work
Gmail selected all 118 eligible bounded body candidates, produced 105 usable
bodies, and disclosed partial coverage for 13 unavailable or unsupported
bodies. The other approved sources completed, and the run produced a private
deterministic-review artifact plus a 635-word briefing without hosted inference
or external writes. Brad reviewed that private evidence and briefing and
accepted the detections and supporting logic, completing Milestone 7.

Another Work Gmail or supporting-source retrieval requires explicit
current-task authorization within its accepted boundary. Personal Gmail is
accepted for Milestone 13 but remains unimplemented and unauthorized until its
design, synthetic, bounded-live, and human-review gates pass. Google Drive
remains deferred and unauthorized.

## Related documents

- [Technical Architecture](../overview.md)
- [Connector Specifications](README.md)
- [Daily Briefing v1](../../product/features/daily-briefing-v1.md)
- [ADR-0004: SQLite and Bounded Local Data Lifecycle](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
- [ADR-0005: OAuth and macOS Keychain](../../decisions/0005-adopt-oauth-and-macos-keychain.md)
- [ADR-0006: Provider-Neutral Inference](../../decisions/0006-adopt-provider-neutral-inference-with-openai.md)
- [ADR-0012: Add Personal Gmail as an Isolated Connector Instance](../../decisions/0012-add-personal-gmail-as-an-isolated-connector.md)
