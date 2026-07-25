# ADR-0002: Define Governing Document Authority and Exception Handling

- **Status:** Accepted
- **Date:** 2026-07-25
- **Owners:** Brad

## Context

The original Constitution expressed document authority as a simple numbered
hierarchy that placed Brad's current instruction above the Constitution and
Vision. That structure did not adequately distinguish among:

- Enduring project purpose
- Constitutional principles and boundaries
- Current execution instructions
- Lower-level product or implementation defaults

The hierarchy could be interpreted to allow an ordinary situational
instruction to silently override the project's governing purpose or
principles. At the same time, an inflexible hierarchy could prevent Brad from
adapting descriptive or implementation defaults to current circumstances.

The authority model must preserve both durable governance and appropriate
execution flexibility while keeping conflicts visible.

## Decision drivers

- Preserve the Vision as the authority for project purpose.
- Preserve the Constitution as the authority for enduring principles,
  boundaries, and judgment.
- Allow current circumstances to change execution without silently rewriting
  governing documents.
- Make material conflicts and exceptions explicit and explainable.
- Keep safety, law, privacy, confidentiality, and legitimate third-party
  interests non-overridable.
- Ensure lower-level product and architecture documents remain subordinate to
  governing purpose and principles.

## Options considered

### Option 1: Retain a simple numbered hierarchy

Continue placing Brad's current instruction above every repository document.
This is easy to apply, but it treats authorities with different
responsibilities as interchangeable and could allow a situational instruction
to silently displace the Vision or Constitution.

### Option 2: Place the Constitution above all current instructions

Make the Constitution categorically superior to every current instruction and
permit no contextual exceptions. This strongly protects enduring principles,
but it is too rigid when current circumstances legitimately require deviation
from descriptive, product, feature, or architecture defaults. It also leaves
no clear mechanism for an explicit, narrow exception to a governing rule.

### Option 3: Adopt a role-based authority model

Assign each governing source a distinct responsibility, allow current
instructions to control execution within governing boundaries, and require
material conflicts with the Vision or Constitution to be surfaced as explicit
exceptions or proposed amendments.

This option was selected because it preserves durable purpose and principles
without treating contextual flexibility as a silent change to project
governance.

## Decision

Chief of Staff will use a role-based authority model:

- The [Vision](../product/vision.md) governs project purpose.
- The [Constitution](../foundations/constitution.md) governs enduring
  principles, boundaries, and judgment.
- Brad's explicit current instruction governs present execution within those
  boundaries.
- Current instructions may override the
  [Leadership Model](../foundations/leadership-model.md),
  [Product Requirements](../product/requirements.md), feature, or architecture
  defaults when circumstances require.
- A current instruction that materially conflicts with the Vision or
  Constitution must be surfaced and treated as an explicit narrow exception or
  proposed amendment rather than as a silent override.
- Safety, applicable law, privacy, confidentiality, and legitimate third-party
  interests remain non-overridable.

An explicit exception is limited to its stated context and does not amend a
governing document. A recurring or durable change should be handled through an
intentional amendment.

## Consequences

### Positive

- Authority conflicts become more explicit and explainable.
- Current circumstances can still override descriptive or implementation
  defaults.
- Exceptions to the Vision or Constitution require conscious acknowledgment.
- Governing purpose and principles remain stable across situational
  instructions.
- Future product and architecture documents remain subordinate to the Vision
  and Constitution.

### Negative

- The assistant must sometimes pause and surface a conflict rather than
  immediately executing an instruction.
- Determining whether a conflict is material may require judgment and
  clarification.
- Explicit exceptions require additional context and may create governance
  drift if they recur without amendment.

### Follow-up

- Keep the Constitution's authority section aligned with this decision.
- Treat recurring exceptions as candidates for a documented amendment.
- Ensure future product, feature, and architecture documents identify
  governing constraints rather than redefining them.

## Related records and documents

- [ADR-0001: Documentation-First Development](0001-documentation-first-development.md)
- [Product Vision](../product/vision.md)
- [Constitution](../foundations/constitution.md)
- [Leadership Model](../foundations/leadership-model.md)
