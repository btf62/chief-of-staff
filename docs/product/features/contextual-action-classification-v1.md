# Feature: Contextual Action Classification v1

- **Status:** Accepted
- **Version:** 1
- **Owner:** Brad
- **Last updated:** 2026-07-29

## Responsibility

`contextual_action_classification` is Milestone 8's first and only approved
model-assisted inference task. It evaluates one minimized candidate when
deterministic processing cannot safely decide whether the evidence describes:

- a contextual commitment;
- a person possibly waiting on Brad;
- preparation possibly needed;
- something not actionable; or
- insufficient evidence.

This task does not rank the day, generate the Chief of Staff Note, compose a
briefing, retrieve source data, query SQLite, use tools, create source facts,
convert an inferred claim into an explicit claim, or perform an external
action.

## Deterministic and model responsibilities

Deterministic application code remains authoritative for:

- source retrieval, normalization, explicit Milestone 7 detections, and
  authoritative facts;
- candidate generation and whether a candidate is unresolved;
- sensitivity eligibility and secret exclusion;
- evidence selection, minimization, identifiers, and size limits;
- local correction and dismissal state;
- schema, provenance, policy, and presentation validation; and
- deterministic reduced-mode behavior.

The model may classify only an unresolved contextual candidate. It may
recommend exclusion, and `insufficient_evidence` is a successful result.
Explicit Milestone 7 detections bypass this task. No section quota or required
positive result exists.

## Evidence packet

Each request contains evidence for exactly one candidate and uses these
conservative Version 1 limits:

| Limit | Value |
| --- | ---: |
| Relevant evidence items | 3 |
| Characters per minimized item | 600 |
| Total minimized evidence characters | 1,200 |
| Human-readable explanation | 400 characters |

The limits are intentionally smaller than typical model context windows. The
task asks a narrow classification question, so additional context would
increase privacy exposure and make provenance harder to evaluate without
demonstrated benefit.

Deterministic minimization:

- removes quoted history, signatures, tracking material, unrelated fragments,
  and attachments;
- replaces unnecessary email addresses with stable local person references;
- retains stable local evidence-reference IDs;
- rejects empty or over-limit packets rather than broadening them; and
- never includes credentials, authentication data, or secret-like strings.

## Sensitivity eligibility

Sensitivity is classified before the provider boundary:

| Classification | Hosted eligibility in Milestone 8 |
| --- | --- |
| Tier 1 — ordinary operational | Eligible for a future separately approved hosted trial |
| Tier 2 — heightened sensitivity | Ineligible |
| Tier 3 — highly sensitive | Ineligible |
| Unknown or ambiguous | Ineligible |
| Mixed sensitivity | Ineligible |
| Credential or secret | Prohibited |

Conservative exclusion is accepted behavior. The classifier is a deterministic
policy control, not an infallible assessment of meaning. Eligibility for one
item or category does not authorize another.

## Provider-neutral input

The application-owned request includes:

- task name and task version;
- prompt, schema, policy, and model-configuration versions;
- one candidate ID and evidence fingerprint;
- permitted result classifications;
- stable evidence-reference IDs;
- minimized evidence facts or excerpts;
- deterministic constraints on the result; and
- the sensitivity classification and eligibility decision.

Provider SDK objects, response IDs, tools, conversation state, credentials,
source connectors, and database handles are not part of this request model.

## Provider-neutral output

The application-owned result includes:

- one permitted classification;
- stable evidence references;
- a concise human-readable explanation;
- categorical uncertainty;
- an inclusion or exclusion recommendation;
- refusal or inability status when applicable;
- task, prompt, schema, policy, and model-configuration versions;
- deterministic validation results;
- provider and model audit metadata without private content; and
- token, latency, request, and estimated-cost metadata without prompts or
  responses.

An actionable inferred classification is presentable only when its evidence
references were supplied, its uncertainty and explanation satisfy the
precision-first policy, and deterministic validation accepts it.

## Validation and exclusion

Reject results that:

- fail the application-owned schema;
- use an unsupported classification;
- invent or omit required evidence references;
- conflict with a deterministic fact or candidate-specific policy;
- omit uncertainty;
- recommend inclusion for `not_actionable` or `insufficient_evidence`;
- exceed the explanation limit; or
- imply an explicit claim, a source fact, a tool use, or an external action.

Schema validity is not factual validity. Provenance and policy validation are
separate, deterministic gates.

## Correction state

The evidence fingerprint is evaluated against Brad's local disposition state.
A dismissal or other suppressing disposition prevents materially unchanged
evidence from producing a visible inference again. A correction remains
locally authoritative. Materially changed evidence receives a new fingerprint
and may be reconsidered with an explanation.

Correction state changes local interpretation only; it does not modify the
external source or train a provider model.

## Failure and reduced mode

The accepted deterministic briefing remains available when:

- hosted inference is disabled;
- evidence is ineligible or prohibited;
- approved provider configuration is incomplete;
- a Keychain credential is unavailable;
- the provider refuses, times out, is rate limited, or is unavailable;
- schema or provenance validation fails; or
- deterministic policy rejects a result.

Reduced mode discloses limited contextual inference without describing a
provider failure as source failure. Existing Milestone 7 output is unchanged
when contextual inference is disabled.

## Evaluation scenarios

Synthetic and mocked evaluation covers:

- contextual promises and implied response expectations;
- meeting preparation;
- stale or non-actionable discussion;
- forwarded or quoted requests;
- automated notifications;
- tentative language and requests addressed to someone else;
- a later response resolving an earlier request;
- conflicting and insufficient evidence;
- corrected or dismissed prior inference;
- sensitivity exclusion;
- malformed output and invented evidence references;
- refusal, timeout, rate limiting, and provider unavailability; and
- deterministic reduced mode.

Results report true positives, false positives, false negatives, correct
exclusions, insufficient-evidence results, sensitivity exclusions, schema
failures, provenance failures, and correction regressions by classification.
Mocked evaluation does not select a production model.

The 2026-07-29 mocked implementation gate exercised 25 synthetic scenarios.
It recorded three true positives, five correct exclusions, three
insufficient-evidence results, four sensitivity or secret exclusions, one
schema failure, one provenance failure, one policy failure, and four provider
failure fallbacks, with zero false positives, false negatives, or correction
regressions. This completes the synthetic gate only; live evaluation and
production-model selection remain unapproved.

## OpenAI API verification

The following provider facts were verified on 2026-07-29. They must be
rechecked at the live authorization gate because provider behavior and
eligibility can change:

- The [Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses)
  is recommended for new projects and uses `POST /v1/responses`.
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
  uses an application-supplied JSON Schema under `text.format`; strict schemas
  require `strict: true`, all fields required, and
  `additionalProperties: false`.
- [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data)
  distinguish abuse-monitoring logs from application state. Standard abuse
  monitoring may retain customer content for up to 30 days.
- Responses application state is retained by default. `store=false` disables
  that application-state storage, but it does not mean Zero Data Retention.
- Modified Abuse Monitoring and Zero Data Retention require eligibility and
  approval. Endpoint, feature, and model eligibility can differ.
- [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching#prompt-cache-retention)
  has separate retention behavior. On current GPT-5.6-family guidance, cache
  TTL controls a minimum rather than a maximum, and cached material may remain
  eligible longer.
- [Production guidance](https://developers.openai.com/api/docs/guides/production-best-practices#api-keys)
  requires API keys to remain outside code and public repositories in secure
  secret storage.

The disabled adapter sets `store=false`, uses no background mode, tools,
conversation history, files, vector stores, hosted containers, fine-tuning,
or provider memory. Prompt caching and organization retention remain visible
live-gate decisions rather than assumptions hidden in adapter code.

The synthetic gate adds no provider SDK or inference-framework dependency.
The adapter translates to the documented Responses request shape through an
injected transport contract, which permits complete mocked validation while
leaving any live HTTP transport unimplemented until the authorization gate.

## Related documents

- [Daily Briefing v1](daily-briefing-v1.md)
- [Deterministic Explicit Detection v1](deterministic-explicit-detection-v1.md)
- [Architecture Overview](../../architecture/overview.md)
- [ADR-0004: SQLite and bounded local data lifecycle](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
- [ADR-0005: OAuth and macOS Keychain](../../decisions/0005-adopt-oauth-and-macos-keychain.md)
- [ADR-0006: Provider-Neutral Inference with OpenAI](../../decisions/0006-adopt-provider-neutral-inference-with-openai.md)
- [Milestone 8 live-evaluation gate](../../operations/milestone-8-live-evaluation-gate.md)
