# Feature: Daily Briefing v1

- **Status:** Accepted
- **Version:** 15
- **Owner:** Brad
- **Last updated:** 2026-08-02

## Summary

Daily Briefing v1 is the first usable Chief of Staff product milestone. Each
workday morning, it scans approved sources, separates signal from noise, and
gives Brad a trustworthy starting point for the day.

The briefing is read-only toward external systems and advisory. It may maintain
bounded, inspectable local state so Brad can correct or disposition inferred
items. It should take approximately five minutes to read, present clarity
rather than completeness, and help Brad direct his attention without replacing
the systems where the underlying records live.

The `Accepted` status approves this specification as the Version 1 design
contract. On 2026-07-30, Brad also accepted the implemented on-demand MVP after
reviewing the corrected Milestone 11 evidence. Personal Gmail is an accepted
post-MVP expansion through Milestone 13, but it does not enter this
specification's operational source set until its separate trust gate passes.
The MVP acceptance does not authorize scheduled generation, Personal Gmail
retrieval, or any other deferred source or agency boundary.

## User Outcome

After reading the briefing, Brad should be able to answer:

1. What are the most important outcomes today, up to three?
2. What is fixed on the calendar?
3. What preparation is needed?
4. Who is waiting on Brad?
5. What commitment or important work is at risk of being forgotten?
6. What important work is coming next?

The briefing succeeds when Brad understands what deserves attention, what can
wait, and what is approaching without reviewing every source independently.

## Scope and Source Authority

The accepted on-demand MVP may read only approved content from these sources:

| Source | Authoritative responsibility |
| --- | --- |
| Google Calendar | Current calendar events, timing, participants, locations, and meeting links |
| Work Gmail | Work messages, correspondence context, replies, acknowledgments, and communication commitments |
| Todoist | Personal tasks, dates, priorities, and completion state |
| Jira | Jira-managed work, status, ownership, dependencies, and deadlines |
| Approved repository context | Approved project goals, decisions, requirements, and working context |

Personal Gmail is approved as the next isolated connector instance under
[Milestone 13](../../roadmap.md#milestone-13--personal-gmail-integration). It
may join this source set only after its independent authorization, privacy,
retrieval, retention, synthetic, bounded-live, and human-review gates pass.
Until then, the briefing must not retrieve it or claim Personal Gmail
coverage. Google Drive remains deferred and unauthorized.

Each source remains authoritative for its own records. The briefing may
interpret and prioritize records across sources, but it must not replace,
silently correct, or modify those systems.

Product-owned local state is not an authoritative source for external records.
It exists only to make briefing inferences correctable, prevent repeated false
recommendations, and remember Brad's explicit disposition of an item.

If a source is unavailable, stale, incomplete, or outside approved access, the
briefing must disclose the limitation rather than implying complete coverage.

## Governing Context and Display Content

The pipeline must distinguish context used to govern judgment from content
selected for display:

- **Governing context** includes the Vision, Constitution, Leadership Model,
  Product Requirements, accepted feature specifications, architecture,
  decisions, and approved operating rules. It constrains classification,
  prioritization, synthesis, and validation.
- **Display content** includes source facts, evidence-bounded implications,
  recommendations, and approaching work that materially help Brad understand
  the day.

Retrieving a governing document does not make its title, summary, headings, or
status a briefing item. Governing context must not be rendered as daily work
merely to prove that it was consulted. If work on a governing document is
itself relevant today, display the authoritative task or commitment record;
the document may be linked as supporting context.

Source coverage for governing context remains visible in the operational
Source Coverage appendix.

## Presentation Budget

The briefing should contain no more than 1,000 words, with 800 words or fewer
preferred. Shorter is better when the day does not require more context.

Sections with no material content should be omitted or collapsed to a concise
statement. The Source Coverage appendix is always present because it is trust
metadata. When content sections are present, keep the canonical order below.

Up Next, People Waiting on Brad, Commitments at Risk, and Important Tasks
should normally contain no more than three items each. If an exceptional
situation requires more, disclose why in the Chief of Staff Note and remain
within the overall reading budget.

Never add filler, low-confidence claims, or a manufactured priority merely to
populate a section.

## Selected-Day and Historical Semantics

A Daily Briefing describes the shape of the entire selected day. Generation
time adds context but must not erase earlier events, elapsed focus
opportunities, or completed portions of the day. Persist and distinguish:

- `briefing_date` — the day described;
- `generated_at` — when the briefing was produced;
- `as_of` — the effective evidence time; and
- `historical_mode` — current, recorded, replay, reconstructed, or synthetic.

Classify selected-day timed items in writing and visually as `Earlier today`,
`In progress`, or `Upcoming`. Color alone is not sufficient. Preserve the best
whole-day focus window even after it has elapsed; describe whether it was
upcoming, in progress with approximate remaining time, or an earlier
opportunity.

Every successful personal briefing is a separate local recorded artifact,
including multiple runs on one date and reduced-coverage runs. A recorded
briefing is never silently recomputed or overwritten. A replay uses current
logic against archived normalized facts and identifies its originating run.
A reconstruction prominently discloses that later source changes and
unavailable historical state may affect accuracy. Synthetic evaluations never
enter the personal briefing archive.

Archive only the minimized structured presentation, coverage, provenance,
applicable correction state, processing versions, lineage, and normalized
facts required for explanation or replay. Do not retain raw Gmail bodies,
MIME structures, attachments, provider payloads, credentials, or hidden
reasoning for this purpose.

## Canonical Briefing Structure

The briefing uses the following sections when they contain material
information, unless Brad gives an explicit current instruction to vary the
presentation.

### 1. Chief of Staff Note

Provide a concise synthesized assessment, normally no more than 150 words.

The note should explain:

- The shape of the day
- The strongest supported outcome
- Meaningful open work windows
- The central priority tension
- What would make the day successful
- Any important risk or opportunity

Distinguish source facts from recommendations. Avoid generic encouragement,
restating the remainder of the briefing, or presenting inference as certainty.
Do not place connector statuses, record counts, retrieval errors, or governing
document summaries in this note. Phrase synthesis as based on retrieved facts
when completeness is uncertain; all coverage limitations and detailed
metadata belong in Source Coverage.

Describe separate Calendar commitments as separate blocks. Summarize their
total scheduled time, gaps, and transition constraints without converting the
span between the first and last event into one continuous commitment. When
Todoist relative-ranking confidence is degraded, include one concise
plain-language disclosure here without source counts or a diagnostic score.

### 2. Today's Outcomes

Recommend no more than three primary outcomes. Normally the briefing should
identify three, but it may include fewer when the available evidence does not
support three meaningful outcomes. Never manufacture a third outcome to
satisfy the format.

Each outcome must include:

- The desired result
- Why it matters today
- A relevant deadline or dependency
- A link to the authoritative source record

Outcomes describe meaningful results, not merely task titles. When a
recommendation depends on inference or incomplete information, say so.

### 3. Up Next

Show a small, selective set of next-tier priorities so Brad can see what the
assistant is intentionally holding behind the top three.

This section should reduce anxiety without becoming another task list. Omit
items already represented elsewhere unless the additional context is
necessary.

A task due more than fourteen days away does not belong in Up Next unless
explicit evidence shows that preparation must begin now. Do not use Up Next as
overflow for the highest-ranked unused task.

### 4. Today's Calendar

Show today's fixed calendar commitments in chronological order. Include, when
useful:

- Time
- Title
- Location or meeting link
- Relevant participants
- Preparation needs
- Travel or transition concerns
- Conflicts or unrealistic sequencing

Google Calendar is authoritative for the current day. The briefing must not
substitute a stored schedule or Leadership Model default for the live calendar.

Classify Calendar records only from explicit provider facts:

- A confirmed timed event is a **fixed commitment**.
- A tentative timed event is a **tentative hold**, not a fixed commitment.
- A provider-identified working-location or out-of-office event is a
  **status signal**, not an appointment.
- An all-day event is **all-day context** and does not, by itself, consume the
  entire day's capacity.
- An event without sufficient status evidence is a **scheduled event** and
  must not be described more strongly.
- A cancelled event is not an active commitment and should not appear as
  current or approaching work.

Do not infer classification, priority, preparation, travel, or immovability
from an event title. Provider facts or additional authoritative evidence are
required.

Status signals are contextual inputs rather than ordinary calendar items.
Routine working-location and availability signals may inform workday,
location, availability, travel, and schedule reasoning, but should not appear
in Today's Calendar, Looking Ahead, or another visible section merely because
they were retrieved. Show one only when authoritative evidence makes it
material to the day, such as an explicit out-of-office state, preparation
requirement, location-dependent commitment, availability conflict, travel
effect, or meaningful change from the normal pattern. If suppression leaves no
visible commitment, omit the calendar section.

The briefing may deterministically synthesize obvious schedule implications
that follow directly from timestamps and classifications:

- Confirmed timed-event span
- Overlapping fixed commitments
- Back-to-back fixed commitments with no calendar margin
- Transitions of 15 minutes or less
- The presence of tentative holds or all-day context

Do not infer travel feasibility, meeting importance, cancellation likelihood,
or usable focus time without the additional evidence needed for that claim.

When tomorrow contains two or more confirmed morning commitments, Looking
Ahead may combine them into one chronological sequence so the presentation
budget does not hide later events. Preserve every source link and the
individual event titles. A friendly sequence label may expand only an
explicitly approved stable alias; the current approved mapping is `ONL` to
`Online Campus`. Do not invent a shared purpose from unrelated titles.

### 5. Preparation Needed

Surface work required before upcoming events or deadlines, such as:

- Documents to review
- Agendas or talking points to prepare
- Decisions to make
- Scripts or deliverables to complete
- People to contact

Surface preparation early enough to prevent avoidable last-minute reaction.
Connect each item to the event, deadline, or source that makes it necessary.

### 6. People Waiting on Brad

Identify people awaiting:

- A response
- A decision
- A promised deliverable
- An acknowledgment
- A status update
- Follow-up

For each item, include:

- The person
- What the person appears to be waiting for
- How long the person has been waiting, or that the duration is unknown
- Whether the expectation is explicit or inferred
- Why an inferred item appeared
- The relevant source link
- A recommended next action

Prioritize trust, relationship consequences, and explicit commitments rather
than email age alone. Clearly label inferred expectations and prioritize
precision over recall: omit a questionable inference rather than present a
false relationship claim with unwarranted confidence.

A task-system record alone does not establish that a person is waiting.
Assignment, ownership, or a due date requires separate evidence of a human
expectation before it may appear here.

### 7. Commitments at Risk

Surface meaningful commitments that appear:

- Overdue
- Due soon
- Stale
- Repeatedly postponed
- Blocked
- Missing a clear next action

Every commitment should remain accounted for until it is completed, delegated,
intentionally abandoned, or consciously rescheduled. Include the source,
current state, apparent risk, recommended disposition, and whether the
commitment is explicit or inferred. Every inferred commitment must explain the
evidence and reasoning that caused it to appear.

Daily Briefing v1 must not automatically create tasks, change dates, or alter a
source system. Prefer precision over recall: omit a weak commitment inference
rather than present it as fact.

### 8. Important Tasks

Show only Todoist or Jira work that materially affects today. Avoid
duplicating items already represented in Today's Outcomes, Preparation
Needed, People Waiting on Brad, or Commitments at Risk.

Source status and ownership must remain visible when they affect the
recommendation.

Task-system priority is a source-owned signal, not the final Chief of Staff
priority. It may influence deterministic ordering, but it does not by itself
prove an external commitment, relationship consequence, or required outcome.

When Todoist contains a saturated overdue or P1/P2 backlog, mark its
relative-ranking confidence as degraded. Continue using explicit dates,
Calendar dependencies, approved active-priority links, and other current
facts, but do not admit a task to the daily-candidate set merely because it is
overdue or P1/P2. The connector specification owns the transparent thresholds
and exact deterministic signals.

Visible task titles should remove Todoist control syntax while preserving the
authoritative source title and link internally. Do not mechanically prepend
`Complete` to an action-oriented source title. Describe Todoist priority only
with source terminology such as `Todoist P1` or `Todoist P2`, and only when it
materially explains inclusion. Render an all-day Todoist due value as a date or
relative date, never as a midnight deadline.

Source titles that resemble Markdown links must display as ordinary readable
text. Preserve meaningful visible text and the separate authoritative
source-system link, but do not interpret source HTML or create links from
untrusted title text.

Source selection and local persistence maintain a bounded background pool.
A separate date-specific daily-candidate gate determines which records
materially affect the briefing date, and section budgets determine which
candidates are displayed. Do not shrink the selected or persisted pool merely
to produce a concise briefing; omit background records at the candidate or
display stage with inspectable deterministic reasons.

### 9. Recommended Focus Block

Recommend one realistic deep-work block when the live calendar permits.
Include:

- Available time window
- Intended outcome and its expected duration when a source provides one
- Why the work deserves Brad's best available energy

Use the [Leadership Model](../../foundations/leadership-model.md) as descriptive
context. The live calendar, Brad's current energy, and explicit current
instructions override default energy assumptions.

Require enough uninterrupted time after transition margin and a
high-confidence objective. Do not assume a noon gap is suitable for deep work.
When Calendar supports a focus window but degraded Todoist confidence leaves
no sufficiently supported objective, identify the window without assigning an
arbitrary task.

Keep the available Calendar window distinct from the proposed task assignment.
When a supported objective has no reliable source effort estimate, recommend
beginning with it without implying that it will occupy or fit the entire
window; leave the remainder intentionally unassigned. When a reliable estimate
exists, size the proposed assignment to that estimate and preserve any
remaining time. Never invent an estimate from the task title, priority, due
date, or available window.

### 10. Looking Ahead

Provide selective awareness of:

- Tomorrow
- The remainder of the week
- Approaching deadlines
- Preparation opportunities
- Work that should begin before it becomes urgent

Keep this section brief and action-oriented. Do not turn it into a complete
future task list.

### Operational Appendix: Source Coverage

After the canonical content sections, show compact operational metadata for
every approved source used in the run. Distinguish records retrieved, selected,
persisted, considered as daily candidates, and displayed. For source-specific
context collections, such as Todoist projects, sections, and labels,
distinguish retrieved and persisted counts with unambiguous resource labels.
Include safe warnings or error categories when relevant. For Todoist, add the
relative-ranking confidence status and compact active, overdue, P1/P2, and
overlap counts without turning the appendix into a task-health report.

Keep this appendix out of the Chief of Staff Note. It exists to make
completeness, partial retrieval, authorization failures, and empty results
inspectable without displacing the note's synthesis.

## Non-Workday Briefing Behavior

A non-workday briefing should protect the day from ordinary work pressure
rather than present a normal workday plan with a different label.

The default weekly work pattern is:

- Monday through Thursday: full workdays.
- Friday: normal non-workday.
- Saturday: flexible half-workday.
- Sunday: ministry workday.

Friday and Saturday may switch through explicit date configuration. Workday
authority follows this order:

1. Brad's explicit current instruction or explicit date configuration.
2. Explicit PTO, vacation, retreat, day-off, or workday configuration.
3. The recurring weekly pattern.
4. Calendar evidence as a conflict signal only.

Routine Home, Office, and working-location signals never determine whether a
day is a workday. If a configured non-workday contains substantial fixed work,
surface the inconsistency and retain the most authoritative workday context
rather than silently relabeling it.

By default it should:

- Retain fixed Calendar commitments and their explicit preparation.
- Preserve concise Looking Ahead awareness.
- Omit task-driven Today's Outcomes, Up Next, Important Tasks, and a
  Recommended Focus Block.
- Avoid treating an ordinary due date, importance flag, or accepted governing
  document as sufficient reason to turn the day off into a workday.
- Use the Chief of Staff Note to protect the day in natural language and, when
  supported, identify an unusually early or tightly sequenced next-day block
  and the preparation cutoff it creates.
- Continue retrieving approved sources and disclosing Source Coverage.

Brad may explicitly override the workday classification for a particular
invocation. A later inference-capable implementation may surface a genuine
time-sensitive exception on a non-workday only when direct evidence supports
it, the reason is explained, and the exception is presented without quietly
normalizing work on protected time. The deterministic reduced mode does not
infer such exceptions.

Sunday's normal Online Campus commitments are ministry work, not evidence that
a day off was interrupted. The deterministic note should synthesize an early
or tightly sequenced ministry block, place necessary preparation before it,
and protect the remainder of Sunday from unrelated ordinary project work.

## Prioritization and Conflict Handling

Recommendations should consider:

- Brad's primary stewardship areas
- Explicit deadlines
- Calendar-bound obligations
- Official six-month goals
- Seasonal initiatives
- People who are blocked or waiting
- Ministry and relationship consequences
- Preparation requirements
- Task and commitment age
- Delegation opportunities
- Estimated effort
- Available time and energy
- The opportunity cost of saying yes

Genuine crisis, significant pain, safety, and pastoral care may interrupt
protected work. Ordinary urgency does not automatically outrank important
work.

When priorities conflict, explain the tradeoff. Use the
[Constitution](../../foundations/constitution.md) for governing judgment and
the Leadership Model for Brad-specific context. Brad's explicit current
instruction governs present execution within those boundaries.

## Trust, Provenance, and Confidence

The briefing must:

- Distinguish source facts, inference, recommendation, and speculation
- Link to authoritative records where practical
- Identify missing, unavailable, incomplete, or stale source data
- Surface conflicting information rather than silently reconciling it
- Explain which source appears most authoritative or current when sources
  conflict
- State when a recommendation has low confidence and why

Example Source Coverage disclosure:

> Todoist was unavailable. Today's recommendations are based on Calendar,
> Work Gmail, Jira, and repository context.

The briefing must not imply that absence from the approved source set proves
that no relevant work or commitment exists.

## Inference and Evaluation Standard

Relationship and commitment inferences carry a higher trust risk than direct
source display. Daily Briefing v1 must therefore:

- Classify a commitment or waiting item as **explicit** when an authoritative
  source contains a direct request, promise, assignment, acknowledgment
  obligation, or deadline.
- Classify it as **inferred** when the expectation or commitment is derived
  from context rather than directly stated.
- Explain why every inferred item appeared and link the evidence used.
- Prioritize precision over recall for People Waiting on Brad and Commitments
  at Risk.
- Track Brad's corrections and dispositions so the same mistake is not
  repeated from materially unchanged evidence.

Before Daily Briefing v1 is accepted as ready for operational use, evaluate it
against representative, human-reviewed scenarios. The evaluation set should
include explicit and inferred commitments, false-positive candidates,
cross-source duplicates, conflicting sources, source outages, priority
tradeoffs, and previously corrected items.

Measure precision separately for People Waiting on Brad and Commitments at
Risk. Review false positives and repeated mistakes explicitly. Recall may be
observed diagnostically, but it must not be improved by flooding the briefing
with questionable inferences. Brad must review the representative results
before the implemented feature is accepted for operational use.

Use synthetic, redacted, or access-controlled scenarios so evaluation does not
place private source content in the repository.

## Local State and Correction Loop

Daily Briefing v1 provides a local-only, server-rendered web interface where
Brad can inspect, correct, disposition, or delete supported local
conclusions. [ADR-0008](../../decisions/0008-adopt-flask-local-web-interface.md)
defines the framework and serving boundary; the behavior below remains the
product contract.

Local state must support at least these dispositions:

- Confirmed
- Corrected
- Dismissed
- Delegated
- Rescheduled
- Completed
- Intentionally abandoned

Each local record should preserve the source reference, the original
inference, Brad's correction or disposition, and enough timestamped history to
explain why the item is or is not shown again.

Local disposition controls briefing interpretation and presentation; it does
not rewrite the external source. If local state and an authoritative source
conflict, disclose or resolve the conflict rather than silently treating the
source as modified.

Brad must be able to inspect, correct, and delete persistent local conclusions
where technically possible, consistent with the Constitution.

## Privacy and Data Minimization

The briefing must follow the Constitution's privacy and affected-party
protections.

- Include only the sensitive detail needed to support a recommendation.
- Prefer concise summaries and authoritative links over reproducing private
  source content.
- Apply heightened care to pastoral, personnel, family, health, financial, and
  confidential organizational information.
- Do not turn correspondence, relationships, or ministry activity into hidden
  performance scoring.
- Do not expose information to a broader audience than its approved source
  context permits.

## Agency Boundaries

Daily Briefing v1 is advisory and read-only toward external systems. Writes to
the bounded local correction state described above are permitted.

It may recommend:

- Replying
- Creating a task
- Changing a deadline
- Delegating
- Reserving calendar time

It must not:

- Send communications
- Create or modify tasks
- Change calendar events
- Update Jira
- Edit Drive documents
- Take any other external action

Generating the briefing must not write to an external source, even when a
recommended action appears obvious or reversible. Local-state writes must be
inspectable and limited to briefing correction, disposition, and explanation.

## Tone and Presentation

The briefing should feel like a warm, direct, people-centered pastoral chief of
staff.

It should:

- Be concise
- Challenge gently
- Avoid shame
- Avoid false certainty
- Avoid excessive detail
- Present clarity rather than completeness

The writing should prioritize useful synthesis over raw source volume. It
should not claim divine revelation or characterize a recommendation as God's
leading.

## Non-Goals

Daily Briefing v1 is not:

- A dashboard
- A complete inbox summary
- A full task list
- A ministry analytics report
- A performance-scoring system
- An autonomous agent
- A replacement for Gmail, Google Calendar, Todoist, Jira, or Google Drive

The following sources and capabilities are outside Daily Briefing v1:

- Rock RMS
- Church Online Platform
- Ministry analytics
- Dashboards
- Autonomous or external actions

## Acceptance Criteria

| ID | Criterion |
| --- | --- |
| AC-01 | Brad can read a representative briefing in approximately five minutes; it contains no more than 1,000 words, with 800 words or fewer preferred. |
| AC-02 | The briefing recommends no more than three primary outcomes, each with a desired result, reason, relevant deadline or dependency, and authoritative source link; it includes fewer when three meaningful outcomes are not supported. |
| AC-03 | Up Next, People Waiting on Brad, Commitments at Risk, and Important Tasks normally contain no more than three items each; any exception is disclosed and remains within the reading budget. |
| AC-04 | Empty or immaterial sections are omitted or collapsed, and sections that appear retain the canonical order. |
| AC-05 | Calendar commitments appear in chronological order and correctly connect to known preparation, transition, and conflict concerns. |
| AC-06 | People waiting on Brad are surfaced with the apparent expectation, waiting duration or an explicit unknown, explicit-or-inferred classification, explanation for inference, source link, and suggested action. |
| AC-07 | Overdue, approaching, stale, postponed, blocked, or actionless commitments are identified with their source, explicit-or-inferred classification, inference explanation when applicable, and recommended disposition. |
| AC-08 | An item is not repeated across briefing sections unless the repeated placement adds necessary, non-duplicative context. |
| AC-09 | Missing, unavailable, conflicting, incomplete, or stale source data is explicitly disclosed. |
| AC-10 | Factual claims and recommendations can be traced to authoritative sources and applicable governing context where practical. |
| AC-11 | Generating the briefing creates no external writes and modifies no source system; any local write is limited to inspectable correction or disposition state. |
| AC-12 | Sensitive content is minimized and handled consistently with the Constitution's privacy and affected-party protections. |
| AC-13 | Brad can inspect, correct, dismiss, confirm, delegate, reschedule, complete, intentionally abandon, or delete supported local conclusions without modifying an external source. |
| AC-14 | A corrected or dismissed false inference does not recur from materially unchanged evidence. |
| AC-15 | Representative, human-reviewed scenarios evaluate People Waiting on Brad and Commitments at Risk separately, with precision treated as the primary trust measure and false positives explicitly reviewed. |
| AC-16 | After reading the briefing, Brad can identify what to do, what can wait, and what is approaching. |
| AC-17 | Governing context constrains briefing behavior but is not rendered as a daily item merely because it was retrieved. |
| AC-18 | Workday classification follows explicit current or date configuration, explicit leave or workday configuration, the recurring weekly pattern, and Calendar conflict evidence in that order. A non-workday briefing preserves fixed commitments, explicit preparation, concise looking-ahead context, and source coverage while suppressing ordinary task-driven work sections. A Sunday ministry briefing treats the scheduled ministry period as normal work and protects the remainder from unrelated ordinary project work. |
| AC-19 | Calendar events are classified from provider status, event type, and time shape; cancelled events are omitted, routine working-location signals remain contextual but are suppressed from visible sections, materially relevant status signals may appear, tentative events are not called fixed, and all-day events are not treated as full-day occupancy without additional evidence. |
| AC-20 | Timestamp-derived overlaps, back-to-back commitments, transitions of 15 minutes or less, confirmed schedule span, and tomorrow-morning sequences are synthesized deterministically without unsupported implications. |
| AC-21 | Source status; retrieved, selected, persisted, and displayed counts; supporting-context counts; safe warnings; and error categories appear in a final Source Coverage appendix rather than the Chief of Staff Note. |
| AC-22 | Todoist saturation uses documented aggregate thresholds; degraded relative-ranking confidence requires stronger current evidence, excludes overdue-only and priority-only tasks, preserves the selected background pool, and is disclosed concisely. |
| AC-23 | Todoist titles omit control syntax in display without changing source data; all-day due dates never render as midnight; source priority uses transparent Todoist terminology only when material. |
| AC-24 | Up Next excludes work more than fourteen days away without explicit current preparation. A Recommended Focus Block requires Calendar margin, distinguishes the available window from the proposed task assignment, uses only source-supported effort estimates, and explicitly leaves unsupported or remaining time unassigned. |

## Acceptance Record

On 2026-07-30, Brad approved the corrected Milestone 11 review package after
reviewing historical replay and reconstruction, preserved
`America/New_York` Calendar times and lineage, native 560 × 900 and
1280-pixel presentations, the three-page print artifact, partial-source
behavior, privacy and no-write boundaries, and all 14 synthetic acceptance
metrics. Passing automation alone did not produce acceptance. This approval
accepted the on-demand Daily Briefing v1 MVP. Commit
`900a3b66d40bb3596e7ebee6ab801f5321050801` is the final correction in that
boundary.

## Open Questions

The following questions require later product or architecture decisions:

- Scheduled invocation decisions for the bounded Milestone 12 trial are owned
  by the accepted
  [Scheduled Morning Generation v1](scheduled-morning-generation-v1.md)
  specification and its
  [decision checklist](scheduled-morning-generation-decision-checklist.md).
  Routine operation after that trial remains a later decision.
- Where should private one-off workday exceptions be maintained operationally?
- How should the accepted bounded Work Gmail retrieval evolve after the MVP
  trial without reducing precision or expanding access implicitly?
- Which additional representative scenarios are required before deterministic
  sent-commitment detection is trusted for operational use?
- What freshness threshold applies to each source?
- Which additional conservative associations across task systems would add
  value without weakening the accepted duplicate and conflict controls?
- How should non-Todoist inference confidence be represented without adding
  visual noise?

Do not resolve these questions through implementation assumptions. Record
significant answers in the Product Requirements, technical architecture, or an
ADR as appropriate.

## Related Documents

- [Product Requirements](../requirements.md)
- [Product Vision](../vision.md)
- [Constitution](../../foundations/constitution.md)
- [Leadership Model](../../foundations/leadership-model.md)
- [Technical Architecture](../../architecture/overview.md)
- [Ranking and Briefing Composition v1](ranking-and-briefing-composition-v1.md)
- [ADR-0001: Documentation-First Development](../../decisions/0001-documentation-first-development.md)
- [ADR-0002: Governing Document Authority](../../decisions/0002-define-governing-document-authority.md)
