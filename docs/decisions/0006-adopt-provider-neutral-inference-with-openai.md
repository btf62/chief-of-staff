# ADR-0006: Adopt a Provider-Neutral Inference Boundary with OpenAI as the Initial Provider

- **Status:** Accepted
- **Date:** 2026-07-25
- **Owners:** Brad

## Context

[Daily Briefing v1](../product/features/daily-briefing-v1.md) requires
judgment beyond deterministic parsing for tasks such as:

- Interpreting contextual commitments
- Identifying when a person appears to be waiting on Brad
- Recognizing preparation needs
- Comparing qualitatively different priorities
- Explaining ranking tradeoffs
- Producing concise briefing language

These tasks may benefit from a large language model, but the source material
can include private personal, organizational, pastoral, personnel, family,
health, and financial information.

The system must gain the value of probabilistic inference without:

- Giving a model direct access to source systems
- Sending unnecessarily broad source content
- Allowing unstructured model output to become authoritative
- Creating hidden provider dependence
- Weakening the [Constitution](../foundations/constitution.md)'s privacy,
  provenance, or agency boundaries

This decision operates within the local-first runtime in
[ADR-0003](0003-adopt-local-first-python-runtime.md), the bounded local data
lifecycle in
[ADR-0004](0004-adopt-sqlite-and-bounded-local-data-lifecycle.md), and the
Keychain secret boundary in
[ADR-0005](0005-adopt-oauth-and-macos-keychain.md).

## Decision drivers

- Add model judgment only where representative evaluation shows value.
- Keep source access, data selection, persistence, and policy enforcement under
  deterministic application control.
- Minimize private data sent to any hosted provider.
- Apply stronger restrictions as content sensitivity increases.
- Make provider, model, prompt, schema, and policy behavior replaceable and
  measurable.
- Prefer precision and explainability over broad inference coverage.
- Preserve a useful reduced briefing when hosted inference is unsafe or
  unavailable.

## Decision

### Provider-neutral inference boundary

All probabilistic inference occurs through an application-owned abstraction.
Domain, connector, persistence, ranking, and briefing modules do not depend
directly on a provider's SDK objects, response formats, conversation
identifiers, or tool protocol.

The inference boundary accepts structured requests such as:

- Commitment classification
- Waiting-item classification
- Preparation inference
- Priority comparison
- Recommendation explanation
- Briefing-section synthesis

It returns application-owned, schema-validated results containing, as
applicable:

- Classification
- Explicit-or-inferred status
- Evidence references
- Explanation
- Confidence or uncertainty
- Recommended inclusion or exclusion
- Model and prompt version
- Provider metadata needed for audit and evaluation

Provider-specific translation belongs inside an adapter. Provider neutrality
does not require multiple providers in Version 1; it prevents provider details
from becoming inseparable from the product's domain model.

### OpenAI as the initial hosted provider

The OpenAI API is the accepted initial hosted inference provider for Daily
Briefing v1 because of its:

- Strong structured-output support
- Suitable reasoning and synthesis capability
- Mature Python integration
- Provider data controls
- Model availability for classification, ranking, explanation, and concise
  synthesis

Implementation will use the current supported OpenAI API recommended for new
application development when implementation begins. This ADR does not bind the
project to one permanent model name or patch version. Representative evaluation
selects the initial model through configuration.

Every inference run records the exact provider, model identifier, request
mode, schema version, prompt version, and relevant settings. Changing
providers, enabling a local model, or materially changing the provider privacy
boundary requires review and may require a later ADR.

### Source retrieval and tools remain outside the model

The model must never:

- Authenticate to Gmail, Calendar, Drive, Todoist, Jira, or Asana.
- Call source connectors.
- Browse Brad's accounts independently.
- Query SQLite directly.
- Modify external or local state.
- Invoke email, calendar, task, or document actions.
- Determine what source content it may access.

Local deterministic application code controls:

- Connector retrieval
- Approved source scope
- Data minimization
- Normalization
- Deduplication
- Evidence selection
- Local correction-state application
- Persistence
- Final policy validation

The model receives only a bounded evidence packet selected by the application
for a specific inference task. Version 1 exposes no connector or mutation tools
to the model.

### Hosted-request minimization

Before calling a hosted model, the application must:

1. Determine whether deterministic or rules-based processing is sufficient.
2. Identify the specific inference question.
3. Select only evidence relevant to that question.
4. Remove unrelated thread history, quoted replies, signatures, boilerplate,
   tracking data, and attachments.
5. Replace unnecessary personal identifiers with stable local references where
   practical.
6. Exclude sensitive details that the result does not require.
7. Enforce task-specific size and sensitivity limits.

Do not send:

- Entire inboxes
- Broad mailbox exports
- Complete Drive folders
- Unrelated email threads
- Whole source-system snapshots
- Attachments unless separately justified
- Full pastoral or personnel narratives when a narrow fact is sufficient
- Additional context merely because it is available

Every request contains the smallest evidence packet reasonably capable of
producing a trustworthy result.

### Content-sensitivity tiers

Content is classified before hosted inference.

#### Tier 1 — Ordinary operational content

Examples include routine meeting information, general project tasks,
non-sensitive deadlines, ordinary status requests, and public or broadly
shared organizational documents.

Hosted inference is permitted with strict data minimization, provider
application-state features under application control disabled, structured
output, and normal provenance and audit controls.

#### Tier 2 — Heightened-sensitivity content

Examples include private but ordinary pastoral correspondence, confidential
internal planning, personnel-adjacent discussion, family logistics, sensitive
congregant information, and limited health or financial context that does not
require detailed analysis.

Hosted inference is excluded by default. It is permitted only when:

- Brad has explicitly approved the content category.
- Deterministic or local processing cannot adequately accomplish the task.
- The minimum necessary excerpt is used.
- Provider arrangement and retention implications have been reviewed.
- The result materially improves the briefing.

Approval of one category does not authorize another category or unrestricted
source access.

#### Tier 3 — Highly sensitive content

Examples include:

- Detailed pastoral counseling or crisis narratives
- Confessions or privileged spiritual-care information
- Confidential personnel evaluations or disciplinary matters
- Detailed health records
- Detailed financial records
- Credentials, secrets, identity documents, or regulated information
- Information whose disclosure could materially harm a congregant, teammate,
  family member, or organization

Tier 3 content is not sent to a hosted model under standard API retention. Tier
3 model inference requires either an approved Zero Data Retention or equivalent
provider arrangement reviewed for the specific use, or approved local-only
model processing.

Without one of those conditions, the application uses deterministic local
processing, shows only source-derived facts, omits the inference, or discloses
that the recommendation could not be generated safely.

Credentials and authentication secrets are never sent to any model, including
under Zero Data Retention.

### Provider application-state storage

OpenAI API requests disable every provider application-state feature under
application control so response application state is not retained, including
`store=false` where applicable.

Daily Briefing v1 does not create provider-hosted conversation history,
assistants, threads, vector stores, files, or other persistent application
state without separate review and approval. It does not use background or
stateful features merely for convenience and does not rely on the provider as
product memory.

Correction state, briefing history, provenance, and prompt or version metadata
remain within the accepted local SQLite boundary.

Application-state controls do not eliminate standard provider abuse-monitoring
retention, prompt-cache behavior, or other feature-specific retention. The
implementation and user documentation must state these distinctions clearly.

### Standard retention and Zero Data Retention

The following facts were verified on 2026-07-25 against the official
[OpenAI data-controls documentation](https://developers.openai.com/api/docs/guides/your-data).
They are not permanent provider guarantees:

- OpenAI API customer data is not used to train or improve OpenAI models unless
  the customer explicitly opts in.
- Standard API use may create abuse-monitoring logs containing prompts and
  responses. The documented default retention is up to 30 days, subject to
  stated legal and safety exceptions.
- Zero Data Retention and Modified Abuse Monitoring are eligibility- and
  approval-based controls, not assumptions available to every API account.
- `store=false` controls application-state storage where supported; it is not
  equivalent to Zero Data Retention.
- The Responses API may retain response application state for at least 30 days
  by default, so the adapter must set supported storage controls explicitly.
- Endpoint, feature, prompt-cache, model, and retention eligibility can differ
  and may change.

Before implementation, verify current official provider documentation and
record:

- Whether the project has standard retention, Modified Abuse Monitoring, or
  Zero Data Retention
- Which organization and project settings apply
- Whether the selected endpoint, features, and model are eligible
- Whether any enabled feature stores application state
- Who owns review of provider-policy changes

A later change in provider retention or eligibility triggers review of the
sensitivity policy and may automatically disable affected inference.

### Structured, schema-validated outputs

Machine-consumed inference uses provider-supported
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
or an equivalent strict schema mechanism. Free-form prose is not a trusted
internal record.

Each inference type has an application-owned schema that validates:

- Required fields
- Enumerated classifications
- Evidence-reference identifiers
- Confidence or uncertainty representation
- Explanation fields
- Inclusion or exclusion recommendation
- Refusal or inability states
- Schema and prompt version

Reject outputs that:

- Fail schema validation.
- Reference evidence that was not supplied.
- Invent source identifiers.
- Omit required uncertainty.
- Exceed task bounds.
- Conflict with deterministic policy rules.

Schema validity is not proof of factual validity. Evidence, provenance, and
semantic policy validation remain required. Natural-language briefing prose is
generated only from approved structured content.

### Separated inference stages

Models are used only where they add demonstrated value. The preferred pipeline
is:

1. Deterministic source extraction
2. Deterministic normalization
3. Rules-based explicit commitment and deadline detection
4. Bounded model-assisted contextual inference
5. Deterministic correction and disposition overlay
6. Explainable priority factors
7. Bounded model-assisted qualitative comparison when necessary
8. Structured briefing plan
9. Model-assisted or template-based prose synthesis
10. Deterministic and semantic output validation

One broad prompt does not receive all source data and independently decide the
entire briefing. Classification, ranking, and synthesis remain logically
separable and independently testable.

### Precision-first inference thresholds

For People Waiting on Brad and Commitments at Risk:

- Prefer omission over a weakly supported claim.
- Require source evidence and a human-readable explanation.
- Distinguish explicit from inferred.
- Suppress candidates below the accepted inclusion threshold.
- Permit low-confidence inclusion only when the possible consequence warrants
  attention and uncertainty is prominent.
- Apply Brad's prior corrections before presentation.
- Evaluate false positives separately for each inference category.

The model must support an `insufficient_evidence` or equivalent exclusion
result. It is never pressured to produce a fixed number of commitments, waiting
items, or outcomes.

### Model, prompt, and schema versioning

Every inference record identifies:

- Provider
- Model identifier
- Model snapshot or version when available
- Prompt or instruction version
- Schema version
- Inference-task version
- Relevant deterministic rule version
- Timestamp
- Sensitivity tier
- Whether hosted inference was permitted
- Validation result

Before changing the production model, prompt, schema, or material inference
strategy:

- Run the representative evaluation suite.
- Compare precision and false positives.
- Review correction-regression behavior.
- Review sensitivity and egress behavior.
- Obtain Brad's approval when results materially change.

The application does not automatically adopt a newly released model merely
because it is newer or more capable.

### Provider fallback behavior

The application does not silently fall back to:

- Another hosted provider
- A broader model endpoint
- A model with different retention terms
- A model without the required schema support
- Unrestricted free-form generation

When the configured model is unavailable, the application uses a deterministic
or approved local fallback when the task supports it, omits the affected
inference, discloses partial coverage, or withholds the briefing when omission
would make it misleading.

A lower-capability hosted model may be configured as a fallback only after
evaluation and explicit approval under the same or stronger privacy boundary.

### Credentials, private content, and logging

The OpenAI API key is stored in macOS Keychain under ADR-0005. It is not stored
in:

- SQLite
- Git
- `.env` files used as persistent storage
- Source code
- Logs
- Crash reports
- Fixtures
- Briefing output
- Backups

Logs may record:

- Provider
- Model identifier
- Request class
- Token or size counts
- Latency
- Cost estimate
- Sensitivity tier
- Validation result
- Error category
- Provider request identifier when safe and useful

Logs must not contain:

- Full prompts
- Full responses
- Evidence excerpts
- Private source bodies
- API keys
- Authorization headers
- Hidden model reasoning

Locally retained inference inputs and outputs follow ADR-0004's minimization,
retention, inspection, and deletion requirements.

### Cost and rate controls

The provider adapter must support:

- Explicit request-size limits
- Per-run model-call limits
- Timeouts
- Retry bounds
- Rate-limit handling
- Cost estimation or accounting
- Cancellation
- Failure disclosure

Requests containing sensitive evidence are not retried through a different
provider or model without explicit authorization. Cost optimization never
justifies broader context reuse, hidden caching, or weakened privacy controls.

### Local-only and deterministic modes

Chief of Staff remains capable of producing a reduced briefing when hosted
inference is unavailable or prohibited. A reduced briefing may still include:

- Calendar facts
- Source-owned tasks
- Explicit deadlines
- Deterministically detected requests
- Source coverage
- Previously confirmed local state
- Clearly labeled rules-based priorities

The briefing discloses when contextual inference or synthesis was limited. The
architecture permits a future local-model adapter, but this ADR does not
select, require, or approve a particular local model.

## Inference-task specification requirements

Every future inference-task specification must define:

- Deterministic-versus-model responsibility
- Evidence-packet limits
- Sensitivity eligibility
- Input and output schemas
- Confidence and exclusion behavior
- Representative evaluation scenarios
- Fallback behavior

Exact model selection remains an evaluated implementation and configuration
decision.

## Alternatives considered

### Option 1: OpenAI-specific architecture throughout the application

Direct provider integration would simplify the initial implementation and
provide immediate access to SDK features. It was not selected because it would
create lock-in, couple domain records to provider formats, make provider
privacy-policy changes harder to address, and weaken testing and future
local-model options.

### Option 2: Local models only

Local models would provide the strongest local data boundary, avoid hosted
inference retention, and improve offline control. They were not selected for
all Version 1 inference because they add hardware, model-serving, operational,
and evaluation requirements and may provide lower or less predictable quality
for nuanced prioritization and synthesis on the current Mac.

Local-only processing remains required or preferred for content that the
sensitivity policy prohibits from hosted inference.

### Option 3: Hosted provider without sensitivity tiers

A single hosted path would simplify implementation. It was not selected because
it treats materially different information as equally safe to transmit,
conflicts with the Constitution's heightened protections, and creates
unnecessary exposure.

### Option 4: Send broad source context in one request

Broad context would simplify orchestration and make more information available
to the model. It was not selected because it violates minimization, increases
privacy exposure and cost, weakens provenance and error analysis, and
encourages monolithic, untestable behavior.

### Option 5: Free-form model output

Free-form output is flexible and easy to prototype. It was not selected for
internal records because it is harder to validate, makes unsupported facts and
poor provenance more likely, and complicates regression testing.

### Option 6: Fine-tuning on Brad's private data

Fine-tuning on private personal or ministry data is rejected for Version 1.
Corrections influence behavior through explicit local state, rules, prompts,
and regression tests rather than opaque model training.

### Option 7: Silent multi-provider fallback

Silent fallback is rejected because providers may have different retention,
security, quality, and structured-output characteristics.

## Consequences

### Positive

- Provider integration remains replaceable.
- Hosted inference gains are available without giving the model source-system
  authority.
- Sensitive-content rules are explicit.
- Structured output improves validation and reproducibility.
- Local correction state remains authoritative for product behavior.
- Provider outages degrade gracefully.
- Model and prompt changes become measurable and reviewable.
- A future local model can be introduced behind the same boundary.

### Negative

- Evidence minimization and sensitivity classification add implementation
  complexity.
- Some useful inferences are omitted when content cannot safely be sent.
- Standard hosted retention prevents highly sensitive inference unless stronger
  controls are approved.
- Structured schemas and evaluation suites require maintenance.
- Model changes cannot be adopted casually.
- Multiple bounded inference stages may increase latency and cost.
- A local fallback may be less capable than the hosted provider.
- Brad must sometimes accept reduced briefing coverage for privacy reasons.

### Follow-up

- Verify and document the OpenAI organization, project, retention, endpoint,
  feature, and model eligibility before implementation.
- Select the initial model only after representative evaluation.
- Define each inference task before implementation using the requirements in
  this ADR.
- Document provider-policy review ownership and failure procedures.
- Re-evaluate the sensitivity policy before enabling a different provider,
  local model, or provider-hosted application state.

## Guardrails

- Never give a model direct connector, database, or external-action access in
  Version 1.
- Never send credentials or authentication secrets to a model.
- Never send an entire inbox, Drive corpus, or source export.
- Never treat `store=false` as equivalent to Zero Data Retention.
- Never claim that standard API use has no provider retention.
- Never enable provider-hosted application state without separate approval.
- Never send Tier 3 content under standard hosted retention.
- Never silently downgrade privacy protections during failure or fallback.
- Never accept schema validity as proof of factual correctness.
- Never permit the model to invent source references.
- Never train or fine-tune on Brad's private source content in Version 1.
- Never log full prompts, full responses, hidden reasoning, or source excerpts.
- Never choose a production model without representative evaluation.

## Related records and documents

- [ADR-0003: Adopt a Local-First Python Runtime](0003-adopt-local-first-python-runtime.md)
- [ADR-0004: SQLite and Bounded Local Data Lifecycle](0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
- [ADR-0005: OAuth and macOS Keychain](0005-adopt-oauth-and-macos-keychain.md)
- [Product Vision](../product/vision.md)
- [Constitution](../foundations/constitution.md)
- [Daily Briefing v1](../product/features/daily-briefing-v1.md)
- [Architecture Overview](../architecture/overview.md)
