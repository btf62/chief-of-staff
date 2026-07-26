# AGENTS.md

## Project phase

This is a documentation-first repository with an accepted Version 1 design
baseline for Daily Briefing v1. The product requirements, feature
specification, architecture, and ADR-0001 through ADR-0006 are accepted.
Milestones 0 through 4 are complete. Milestone 5 has begun with a mock-only
Todoist retrieval contract. Work is paused at the explicit Todoist live-access
gate in `docs/architecture/connectors/todoist.md`, and no Todoist live access
or broader Calendar access is authorized.

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
4. The Architecture Overview and ADR-0001 through ADR-0006 are accepted.
5. The implementation roadmap defines milestone dependencies, deliverables,
   acceptance gates, and exclusions.

Implementation may proceed only when a task explicitly authorizes it. The
one-trial Google Calendar gate in
`docs/architecture/connectors/google-calendar.md` has been exercised; do not
repeat live retrieval, broaden Calendar access, refresh authorization, or
begin another connector without new explicit approval. Satisfy a milestone's
acceptance gate before beginning dependent work. Record material new product
or architecture decisions before implementing them.

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
