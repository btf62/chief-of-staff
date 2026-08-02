# AGENTS.md

## Project phase

This is a documentation-first repository with an accepted Version 1 design
baseline for Daily Briefing v1. The product requirements, feature
specification, architecture, and ADR-0001 through ADR-0008 are accepted.
Milestones 0 through 4 are complete. Milestone 5 has completed the accepted
Todoist connector, one combined Calendar-and-Todoist trial, and one explicitly
approved complete-retrieval and workday-quality validation. Jira has completed
its mocked phase, one resource-restricted project-discovery trial, and one
exact-project live issue trial integrated with the deterministic briefing.
Milestone 5 now covers only Todoist and Jira and is complete. Work Gmail is the
final MVP input connector, and its synthetic implementation gate is complete.
The successful combined Work Gmail trial on 2026-07-28 listed and inspected 357
messages, found 144 eligible body candidates, selected 120, omitted 24 without
body retrieval, attempted 117 body reads, and produced 106 usable bodies. Gmail
coverage was partial as required; repository, Calendar, Todoist, and Jira
coverage was complete. The trial persisted three minimized Gmail conclusions
and produced a private candidate review plus a 929-word combined briefing.
Brad reviewed the private Work Gmail evidence and combined briefing and judged
the logic sound, completing Milestone 6. Milestone 7 deterministic explicit
detection has passed its synthetic evaluation and one five-source live
validation. Brad reviewed the private evidence and briefing and judged the
detections and supporting logic sound, completing and accepting Milestone 7.
Milestone 8 is complete and accepted. Brad reviewed the category-specific
Terra–Luna results and selected OpenAI `gpt-5.6-luna` with low reasoning for
the `contextual_action_classification` task only, using the exact evaluated
Responses configuration. The adapter remains disabled by default. The
selection does not apply to ranking, priority comparison, note synthesis, or
section prose, and it does not authorize routine hosted inference or private-
source egress. The one-time provider authorization is consumed. No repeat
provider call, source retrieval, authorization refresh, scope change, routine
hosted inference, private-data egress, or model selection for another task is
now authorized. Milestone 9 deterministic ranking and composition is complete
and accepted. Brad reviewed the corrected private representative briefings
after all 26 scenarios passed with zero unsupported claims or false-positive
actionable recommendations. The review also confirmed source-attributed
conflicts, link-preserving duplicate suppression, inspectable source-backed
ranking factors, and the accepted presentation rules. No provider, connector,
or external-write operation occurred.
Milestone 10's secure loopback-only Flask and Waitress interface, structured
briefing presentation, complete local disposition history, recurrence
projection, and transactional deletion behavior are complete and accepted.
Brad reviewed the actual interface at normal browser zoom, a successful
five-source July 30 briefing, the correction controls and evidence links, and
the four-page PDF rendering. Milestone 11 operational hardening is complete
and accepted. On 2026-07-30, Brad reviewed the corrected historical replay and
reconstruction, preserved `America/New_York` times and lineage, native
560-pixel and 1280-pixel browser presentations, three-page print artifact,
partial-source behavior, privacy and no-write boundaries, and all 14
synthetic acceptance metrics. He explicitly approved the package, completing
Milestone 11 and accepting the on-demand Daily Briefing v1 MVP. Commit
`900a3b66d40bb3596e7ebee6ab801f5321050801` is the final correction in the
accepted boundary. Milestones 1 through 11 are complete and accepted.
Milestone 12 Scheduled Morning Generation is active for a bounded
seven-eligible-date trial on Brad's current primary Mac from 2026-08-03 through
2026-08-10. The accepted schedule is 6:00 a.m. `America/New_York` on Monday
through Thursday, Saturday, and Sunday, with catch-up only through 11:00 a.m.
The trial must become inert after seven eligible dates. Routine unattended
operation after the trial is not accepted. The implementation, 419-test
repository gate, Milestone 8 and 9
evaluations, Milestone 11 evaluation, Markdown validation, and wheel packaging
are complete. The exact-scope Calendar continuity check, reversible
LaunchAgent activation, notification test, and disable/re-enable test passed.
Personal Gmail and Google Drive remain deferred and unauthorized.

## Working rules

- Do not add functional code, dependencies, build systems, generated projects,
  or deployment configuration unless the task explicitly authorizes
  implementation.
- Keep implementation within the current roadmap milestone and its acceptance
  gate. Do not begin a later milestone merely because its design is visible.
- Start by reading `README.md` and `docs/README.md`.
- Treat `docs/product/vision.md` as the source of truth for product purpose and
  `docs/product/requirements.md` as the top-level product requirements
  document.
- Treat `docs/foundations/constitution.md` as the authority for assistant
  judgment and behavior, and `docs/foundations/leadership-model.md` as the
  authority for primary-user leadership context.
- Record consequential or difficult-to-reverse technical choices as
  architecture decision records under `docs/decisions/`.
- Keep placeholders honest. Use `TBD`, open questions, and assumptions instead
  of inventing requirements.
- Link to authoritative documents instead of restating their governing
  content.
- Keep links, status labels, and the repository map current when adding,
  moving, or removing documents.
- Prefer focused edits that preserve the existing document structure and tone.

## Privacy and sensitivity

This repository may contain operationally relevant information about its
primary user, but it must remain safe to share publicly.

- Include only the minimum personal context necessary for the product to
  function.
- Do not commit passwords, tokens, credentials, private email content, medical
  details, financial details, confidential personnel information, or
  unnecessary family information.
- Prefer abstractions, configuration references, local ignored files, or
  secure secret storage for sensitive material.
- Do not commit production data.

## Documentation conventions

- Use Markdown.
- Give each planning document a status such as `Draft`, `Proposed`, `Accepted`,
  or `Superseded`.
- Include an owner and last-updated date when a document becomes active.
- Use ISO 8601 dates (`YYYY-MM-DD`).
- Wrap lines at a readable width where practical.
- Add new reusable document formats under `templates/`.

## Implementation governance

The Version 1 design-readiness requirements have been met:

1. The Vision, Constitution, and Leadership Model are accepted.
2. The Product Requirements and Daily Briefing v1 specification are accepted.
3. Data, privacy, security, agency, and source-authority constraints are
   recorded.
4. The Architecture Overview and ADR-0001 through ADR-0008 are accepted.
5. The implementation roadmap defines milestone dependencies, deliverables,
   acceptance gates, and exclusions.

Implementation may proceed only when a task explicitly authorizes it. The
Google Calendar, Todoist, Jira project-discovery, Jira issue, and combined Work
Gmail trial gates and the one-time Milestone 8 synthetic provider comparison
have been exercised. Do not repeat live retrieval or provider calls, refresh
authorization, broaden access, repeat Jira discovery, run an unrelated live
retrieval, enable routine hosted inference, select a model for another
inference task, or begin another connector without new explicit approval from
Brad. Milestones 1 through 11 and the on-demand Daily Briefing v1 MVP are
accepted. Do not perform another live retrieval, request or refresh
authorization, invoke hosted inference, enable scheduling, add a connector,
modify an external system, or begin a deferred milestone without new explicit
approval. Acceptance does not authorize unattended operation or expand any
connector, credential, inference, agency, or retention boundary. Record
material new product or architecture decisions before implementing them.
Milestone 12 implementation, one exact-scope refreshable Calendar
reauthorization, installation of the accepted user LaunchAgent, and activation
of the bounded trial are authorized only through the documented synthetic,
validation, clean-repository, connector-health, and host-verification gates.
No always-running timer, wake schedule, Jira `offline_access`, Personal Gmail,
Drive, hosted inference, external write, added source, or routine operation
after the trial is authorized.

## Validation

For Python changes, run:

```text
make check
```

For documentation-only changes, verify:

- Markdown is readable and internally consistent.
- Relative links resolve.
- No accidental executable or generated files were added.
- `git diff` contains only the intended changes.
