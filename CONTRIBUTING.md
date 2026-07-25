# Contributing

## Current scope

The project is in a documentation and discovery phase. Contributions should
clarify the problem, requirements, constraints, decisions, or delivery plan.
Functional code and dependency setup are out of scope until explicitly
approved.

## Workflow

1. Identify the document that owns the topic.
2. State assumptions and open questions.
3. Make the smallest complete change.
4. Update related links, status fields, or decision records.
5. Review the rendered Markdown and repository diff.

## Privacy and sensitivity

All contributions must follow the authoritative
[privacy and sensitivity policy](AGENTS.md#privacy-and-sensitivity). Include
only the minimum primary-user context necessary, and keep the repository safe
to share publicly.

## Proposing a feature

Start with [`templates/feature-spec.md`](templates/feature-spec.md). A proposal
should describe the user problem, desired outcome, non-goals, constraints, and
measurable acceptance criteria without prematurely selecting an implementation.
Accepted feature specifications belong in `docs/product/features/`.

## Recording a decision

Use [`templates/decision-record.md`](templates/decision-record.md) for choices
that affect architecture, security, privacy, operations, or future flexibility.
Architecture and significant product decision records belong in
`docs/decisions/` and use the next available four-digit number.

## Commit guidance

Use concise, imperative commit messages. Keep unrelated documentation changes
separate so reviewers can understand the intent and history.
