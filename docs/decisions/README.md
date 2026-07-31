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
| [ADR-0004](0004-adopt-sqlite-and-bounded-local-data-lifecycle.md) | Adopt SQLite and a Bounded Local Data Lifecycle | Accepted | 2026-07-25 |
| [ADR-0005](0005-adopt-oauth-and-macos-keychain.md) | Adopt OAuth and macOS Keychain for Connector Credentials | Accepted | 2026-07-25 |
| [ADR-0006](0006-adopt-provider-neutral-inference-with-openai.md) | Adopt a Provider-Neutral Inference Boundary with OpenAI as the Initial Provider | Accepted | 2026-07-25 |
| [ADR-0007](0007-remove-asana-from-product-scope.md) | Remove Asana from Product Scope | Accepted | 2026-07-28 |
| [ADR-0008](0008-adopt-flask-local-web-interface.md) | Adopt Flask and Waitress for the Local Web Interface | Accepted | 2026-07-30 |
| [ADR-0009](0009-choose-connector-authorization-continuity.md) | Choose Connector Authorization Continuity | Proposed | 2026-07-30 |
| [ADR-0010](0010-choose-scheduled-morning-generation-mechanism.md) | Choose the Scheduled Morning Generation Mechanism | Proposed | 2026-07-30 |
