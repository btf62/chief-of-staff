# Deterministic Briefing Operations

- **Status:** Draft
- **Owner:** Brad
- **Last updated:** 2026-07-25

This document describes the implemented Milestone 3 deterministic
reduced-briefing pipeline. It supports safe development and evaluation with
synthetic records only. It does not authorize live source access, hosted
inference, external writes, private fixtures, or unattended scheduling.

## Run the synthetic briefing

Create the supported development environment as described in
[the contribution guide](../../CONTRIBUTING.md), then run:

```text
make demo-synthetic
```

The command prints one repository-owned synthetic briefing to standard output.
It does not read credentials, use the network, modify an external source, or
persist application state.

Run the complete quality gate with:

```text
make check
```

## Implemented flow

The reduced pipeline:

1. Resolves an explicit briefing date, IANA timezone, workday status,
   invocation mode, run identity, and bounded retrieval window.
2. Invokes only the retrieval operation exposed by each read-only connector.
3. Records connector scope, coverage, freshness, warnings, and failures.
4. Normalizes minimal calendar, task, and context facts with source
   provenance.
5. Collapses only semantically identical copies with the same source-owned
   identity and preserves conflicting records.
6. Selects factual items using visible deterministic priority inputs.
7. Builds a structured plan in the canonical Daily Briefing order, omitting
   sections without material content.
8. Renders Markdown and validates provenance, duplicate keys, section order,
   section item limits, the 150-word note limit, and the 1,000-word briefing
   maximum.

The ordinary target remains 800 words or fewer. The synthetic demonstration is
also tested against that preferred budget.

## Failure and trust behavior

A connector retrieval failure becomes `unavailable` source coverage and is
disclosed in the Chief of Staff Note. Partial coverage and connector warnings
are also disclosed. Malformed connector output, inconsistent record counts,
or an invalid briefing plan fails validation instead of producing an
apparently trustworthy result.

Every briefing item retains its authoritative source name, source record
identifier, and display link when supplied. Priority recommendations expose
the deterministic facts used to include them; there is no hidden composite
score.

## Current limitations

- All source records are synthetic and held in memory.
- The connector contract is implemented, but no production connector or live
  authorization exists.
- The reduced composer does not infer people waiting, commitments at risk, or
  a recommended focus block.
- The pipeline does not yet apply the Milestone 2 correction state during
  briefing composition.
- Invocation is manual and output is printed to standard output.
- The demonstration is not a product-acceptance claim.
