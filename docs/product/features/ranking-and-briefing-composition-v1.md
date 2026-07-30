# Feature: Ranking and Briefing Composition v1

- **Status:** Accepted
- **Version:** 3
- **Owner:** Brad
- **Last updated:** 2026-07-30

## Responsibility

`ranking_and_briefing_composition_v1` converts approved normalized facts,
explicit detections, accepted contextual inferences, governing context, source
coverage, and local correction state into an explainable structured plan and
a concise Daily Briefing.

This feature ranks and presents only records already admitted by approved
source, detection, inference, sensitivity, and correction boundaries. It does
not retrieve source data, reinterpret governing documents as daily content,
create source facts, modify external systems, or give a model independent
control of the briefing.

## Deterministic responsibility

Application-owned deterministic code:

- applies corrections and suppressing dispositions before visible ranking;
- establishes candidate eligibility and preserves Todoist degraded-ranking
  behavior;
- attaches every applied factor to supporting source facts;
- assigns qualitative priority bands and deterministic tie breakers;
- associates likely duplicates conservatively without deleting source
  records;
- preserves material source conflicts;
- creates the structured `BriefingPlan`;
- selects no more than three supported outcomes without manufacturing a quota;
- composes deterministic prose from approved plan inputs; and
- validates provenance, section order, item caps, word budgets, inference
  labels, source coverage, and the read-only boundary.

## Optional future model responsibility

Milestone 9 uses no model for ranking or prose. Two later inference tasks may
be evaluated independently:

- `priority_comparison` could compare a genuinely qualitative tie after
  deterministic factors are exhausted. Its deterministic fallback retains
  both candidates, records that comparison could help, and uses the published
  stable tie breaker.
- `briefing_section_synthesis` could improve natural language after priority
  and section selection are fixed. Its deterministic fallback is the accepted
  template composer operating only on validated plan inputs.

Neither task has a selected provider or model. The task-specific Luna
selection for
[`contextual_action_classification`](contextual-action-classification-v1.md)
does not transfer to either task.

## Candidate eligibility

A candidate must already be within the approved source boundary and must have
enough current evidence for its intended section. Source assignment, overdue
status, recency, or a source priority alone may retain an item as background
context but cannot force it into Today's Outcomes.

The candidate gate:

- excludes completed, cancelled, ineligible, policy-rejected, and immaterial
  records;
- requires direct explanation and low uncertainty for a visible contextual
  inference;
- preserves the stricter Todoist gate when relative ranking is degraded;
- excludes Jira assignment or priority without current relevance; and
- applies accepted local corrections and suppressions before ordering.

Absence of a factor is not negative evidence. No fixed number of outcomes or
other items is required.

## Explainable ranking

The ranking model uses qualitative bands:

1. `critical`
2. `today`
3. `approaching`
4. `strategic`
5. `background`

Applied factors may include:

- explicit hard deadline;
- due today or approaching due date;
- Calendar-bound obligation;
- preparation dependency;
- another person or team blocked;
- primary stewardship;
- ministry or relationship consequence;
- official six-month goal;
- current seasonal initiative;
- explicit source priority;
- age and freshness;
- blocker or dependency state;
- delegation opportunity;
- source-supported effort;
- available Calendar window;
- documented energy pattern;
- opportunity cost; and
- correction or disposition state.

Every factor retains its factor type, rationale, source, source record ID,
display link when available, fact name, and fact value. Sensitive pastoral or
relational work is never assigned a hidden performance score.

Source priority is one source-owned signal, not final Chief of Staff judgment.
Effort is used only when supplied by a source. Calendar capacity remains
separate from task effort, and free time is not automatically filled.

## Deterministic ties

Candidates within the same band first use the number of supported consequence
factors, then:

1. earliest source due date;
2. freshest source fact;
3. source name;
4. source record ID; and
5. stable application record ID.

When two candidates retain the same qualitative band and consequence-factor
shape, the plan records that bounded qualitative comparison could help. The
deterministic order remains the Milestone 9 fallback. No OpenAI call occurs.

## Correction state

A suppressing disposition removes materially unchanged evidence before factor
extraction or ranking. A correction replaces local presentation wording
before ranking while retaining source provenance. Confirmation or another
applicable disposition remains an inspectable factor.

Correction state changes local interpretation only. It does not rewrite an
external source or train a provider model.

## Duplicate and conflict handling

Strong association evidence includes explicit cross-source identifiers or
URLs, a Jira key in Todoist, another stable source cross-reference, or a
compatible set of ownership, project, date, and title facts. Title similarity
alone is insufficient for destructive merging.

One combined visible recommendation may represent associated records, but the
plan retains:

- the representative and suppressed record IDs;
- every authoritative source link;
- source-specific status and dates; and
- the reason presentation suppression was safe.

Conflicting dates, owners, status, or priority remain attached to the plan.
The briefing attributes each conflicting value to its source rather than
silently choosing one value as canonical. An urgent value may keep conflict
resolution eligible for attention, but the prose qualifies that urgency and
recommends verification. Source freshness or authority may influence the
explanation only when retained evidence supports the comparison. Completion
conflicts receive the same treatment as date, owner, status, and priority
conflicts.

## Structured briefing plan

The application-owned plan precedes Markdown rendering and contains:

- workday classification and approved source coverage;
- ordered eligible candidates, qualitative bands, factors, and tie behavior;
- selected outcome IDs and canonical planned sections;
- Calendar items and preparation;
- explicit and inferred conclusions with explanation and uncertainty;
- recommendation items and focus-window evidence;
- supported Chief of Staff Note inputs;
- suppressed duplicates and correction suppressions;
- unresolved conflicts; and
- coverage warnings.

Content roles distinguish authoritative source facts, explicit detections,
inferred conclusions, recommendations, and presentation-only synthesis. The
plan does not introduce unsupported facts or prose.

## Canonical composition

Composition follows
[Daily Briefing v1](daily-briefing-v1.md):

- Chief of Staff Note is normally no more than 150 words.
- Total output is no more than 1,000 words, with 800 or fewer preferred.
- Today's Outcomes contains no more than three supported outcomes.
- Up Next, People Waiting, Commitments at Risk, and Important Tasks normally
  contain no more than three items.
- Empty or immaterial sections are omitted.
- Present sections retain canonical order.
- Calendar items remain chronological.
- Source Coverage is always final.
- Inferred items show their uncertainty and explanation.
- Partial, stale, unavailable, or missing coverage is disclosed.
- No item is repeated unless the second placement adds necessary context.

The Chief of Staff Note is composed only from structured workday, schedule,
outcome, focus-window, conflict, and ranking-confidence inputs. It does not
introduce connector counts, a new fact, shame, divine guidance, or an
implication of complete knowledge.

Visible ranking rationale uses complete natural sentences rather than
priority-band names or internal factor labels. Calendar synthesis preserves
separate commitment blocks and describes total scheduled time, gaps, tight
transitions, and open windows without treating the first-to-last span as
continuous occupancy.

## Focus and capacity

Focus recommendations preserve Calendar transition margin and distinguish the
available window from the proposed assignment. A task receives a sized
assignment only when the source provides effort. Unsupported remaining time is
left unassigned.

The documented stronger-morning energy pattern may influence fit only when the
task's energy need is also supported. Non-workday and Sunday ministry rules
remain authoritative. The composer does not fill every free interval.

## Reduced mode

Deterministic ranking and composition are the complete Milestone 9 mode, not a
failure state. If contextual inference is disabled, ineligible, or
unavailable, the plan uses approved source facts and explicit detections and
discloses the limited inference boundary. Model unavailability never becomes
source unavailability.

## Evaluation

The local synthetic corpus covers at least:

- normal, meeting-heavy, open-morning, non-workday, and Sunday ministry days;
- one, zero, and many supported outcomes;
- explicit waiting, accepted contextual inference, and policy rejection;
- commitments at risk and preparation dependencies;
- duplicates and conflicts;
- Todoist saturation and irrelevant Jira work;
- partial and unavailable coverage;
- correction recurrence and sensitive-content exclusion;
- supported and unsupported effort;
- adversarial priority claims;
- empty sections; and
- genuinely useful Looking Ahead preparation.

The evaluation measures canonical structure, selection, factor traceability,
duplicate suppression, conflict disclosure, provenance, inference labeling,
correction recurrence, item and word budgets, focus behavior, unsupported
claims, and external-write prohibition. A false-positive actionable
recommendation is the primary trust failure.

## Acceptance

All 26 representative scenarios passed with zero unsupported claims or
false-positive actionable recommendations. Conflict claims are
source-attributed; duplicate suppression preserves authoritative records and
links; ranking factors remain inspectable and source-backed; and the word,
section, outcome, focus-block, and canonical-order rules passed. No provider,
connector, or external-write operation occurred.

Brad reviewed the corrected representative briefings and explicitly accepted
Milestone 9. Minor presentation refinements may continue without reopening
this trust gate. Acceptance does not authorize hosted inference, live
retrieval, external writes, scheduling, or work outside an explicitly
authorized later milestone.

## Related documents

- [Daily Briefing v1](daily-briefing-v1.md)
- [Contextual Action Classification v1](contextual-action-classification-v1.md)
- [Leadership Model](../../foundations/leadership-model.md)
- [Architecture Overview](../../architecture/overview.md)
- [ADR-0004: SQLite and bounded local data lifecycle](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
- [ADR-0006: Provider-neutral inference with OpenAI](../../decisions/0006-adopt-provider-neutral-inference-with-openai.md)
