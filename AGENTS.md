# AGENTS.md

## Project phase

This is a documentation-first repository in its initialization phase. There is
currently no approved application architecture, technology stack, or
implementation plan.

## Working rules

- Do not add functional code, dependencies, build systems, generated projects,
  or deployment configuration unless the task explicitly authorizes
  implementation.
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

## Before implementation

Implementation work should not begin until, at minimum:

1. The vision and intended users are defined.
2. The constitution and leadership model are reviewed.
3. Initial requirements and non-goals are reviewed.
4. Data, privacy, and security constraints are recorded.
5. The high-level architecture is accepted.
6. The first implementation milestone has clear acceptance criteria.

## Validation

For documentation-only changes, verify:

- Markdown is readable and internally consistent.
- Relative links resolve.
- No accidental executable or generated files were added.
- `git diff` contains only the intended changes.
