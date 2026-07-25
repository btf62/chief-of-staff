# ADR-0001: Documentation-First Development

- **Status:** Accepted
- **Date:** 2026-07-25
- **Owners:** Brad

## Context

Chief of Staff is intended to become a long-lived system shaped by both human
collaborators and AI agents. Its product philosophy, assistant behavior,
primary-user context, feature expectations, and technical architecture are too
consequential to remain implicit in conversations or emerge accidentally from
implementation.

Beginning with code would turn unexamined assumptions into system behavior
before the problem, boundaries, and desired outcomes had been reviewed. It
would also leave future collaborators to reconstruct intent from source code,
chat history, or incomplete institutional memory.

The [Product Vision](../product/vision.md) calls Chief of Staff to restore
clarity, cultivate vision, and
[build systems that outlast individuals](../product/vision.md#build-systems-that-outlast-individuals).
The development process should embody those same commitments.

Documentation in this project is therefore not administrative bureaucracy
added around the design process. It is the primary design artifact through
which humans and AI agents develop shared understanding, evaluate tradeoffs,
preserve rationale, and collaborate over time.

## Decision drivers

- Preserve product intent and decision rationale beyond individual
  conversations.
- Give humans and AI agents a stable, reviewable source of truth.
- Surface assumptions, boundaries, risks, and unresolved questions before they
  become implementation constraints.
- Keep product, feature, and architecture decisions traceable to the
  [Vision](../product/vision.md).
- Reduce rework caused by premature or inconsistent implementation.
- Support long-term collaboration without requiring contributors to infer
  design intent from code.

## Options considered

### Option 1: Implementation-first development

Begin building immediately and allow requirements and architecture to emerge
primarily from working code. This may create early momentum, but it makes
unreviewed implementation choices the de facto design and leaves important
context undocumented.

### Option 2: Documentation alongside implementation

Write documentation concurrently with code. This reduces some delay, but
implementation can still outrun product thinking and bias unresolved decisions
toward whatever is easiest to build first.

### Option 3: Documentation-first development

Document and review significant product thinking, architecture, and feature
design before implementing the affected capability. This creates deliberate
upfront work while providing the clearest shared contract for subsequent
implementation.

## Decision

Chief of Staff will use documentation-first development.

All significant product thinking, architecture, and feature design must be
captured in the appropriate authoritative repository documents before
implementation begins. At minimum, implementation must be grounded in the
relevant Vision, governing foundations, product requirements, feature
specifications, technical architecture, and accepted decision records.

Documents do not need to predict every implementation detail or eliminate all
uncertainty. They must be sufficiently complete to communicate intent,
boundaries, tradeoffs, acceptance criteria, and known risks. Documentation
remains a living design artifact and must evolve when validated learning
changes the design.

Small, reversible implementation details that do not materially affect product
behavior, architecture, security, privacy, or future flexibility do not require
their own decision record. The purpose is disciplined clarity, not
documentation for its own sake.

## Consequences

### Positive

- Humans and AI agents can work from the same durable source of truth.
- Important assumptions and tradeoffs become reviewable before code makes them
  expensive to change.
- New collaborators can understand both what was decided and why.
- Implementation can be evaluated against explicit intent and acceptance
  criteria.
- Product philosophy, feature behavior, and technical design remain connected
  over the life of the project.

### Negative

- Meaningful implementation may begin later because design work happens first.
- Documentation requires ongoing maintenance to remain authoritative.
- Excessive detail could become wasteful or create false certainty.
- Stale documents could mislead collaborators if changes are not recorded.

### Follow-up

- Keep authoritative document responsibilities and readiness expectations
  clear in [`AGENTS.md`](../../AGENTS.md).
- Require implementable feature specifications before beginning feature work.
- Record significant product and architecture choices in this directory.
- Update the relevant documents whenever implementation learning changes an
  accepted design.

## Related records and documents

- [Product Vision](../product/vision.md)
- [Feature specifications](../product/features/README.md)
- [Technical architecture](../architecture/overview.md)
- No earlier decision records.
