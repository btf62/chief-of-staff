# Decision Records

This directory is the authoritative location for architecture decisions and
significant product decisions. Decision records preserve the context, options,
rationale, and consequences of consequential choices.

## Naming

Use a four-digit sequence and a short kebab-case title:

```text
0001-example-decision.md
```

Copy [`../../templates/decision-record.md`](../../templates/decision-record.md)
and replace every placeholder. Do not reuse numbers, including for superseded
decisions.

## Lifecycle

1. Create the record with status `Proposed`.
2. Review it with affected stakeholders.
3. Change the status to `Accepted` or `Rejected` and record the date.
4. If a later decision replaces it, mark it `Superseded` and link both records.

## Decision index

| ADR | Title | Status | Date |
| --- | --- | --- | --- |
| [ADR-0001](0001-documentation-first-development.md) | Documentation-First Development | Accepted | 2026-07-25 |
| [ADR-0002](0002-define-governing-document-authority.md) | Define Governing Document Authority and Exception Handling | Accepted | 2026-07-25 |
| [ADR-0003](0003-adopt-local-first-python-runtime.md) | Adopt a Local-First Python Runtime | Accepted | 2026-07-25 |
