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
6. Retains approved governing context for pipeline use without rendering
   context documents as standalone daily items.
7. Classifies Calendar facts as fixed commitments, tentative holds, provider
   status signals, all-day context, or scheduled events without title-based
   inference. Routine working-location signals remain available as context but
   are suppressed from visible sections unless explicit evidence makes them
   material.
8. Selects factual items using visible deterministic priority inputs and
   applies the lighter non-workday presentation policy.
9. Synthesizes only timestamp-obvious schedule implications: confirmed span,
   overlaps, back-to-back events, transitions of 15 minutes or less, and
   tomorrow-morning sequences. `ONL` may be expanded to the approved
   `Online Campus` label when every event in a sequence contains that alias.
   On a non-workday, an unusually early or tightly sequenced next-day block
   informs a concise preparation cutoff in the Chief of Staff Note.
10. Builds a structured plan in the canonical Daily Briefing order, omitting
    content sections without material content and appending Source Coverage.
11. Renders Markdown and validates provenance, duplicate keys, section order,
    coverage placement, section item limits, the 150-word note limit, and the
    1,000-word briefing maximum.

The ordinary target remains 800 words or fewer. The synthetic demonstration is
also tested against that preferred budget.

## Failure and trust behavior

A connector retrieval failure becomes `unavailable` Source Coverage. Partial
coverage, record counts, safe connector warnings, and error categories appear
in the final Source Coverage appendix rather than the Chief of Staff Note.
Schedule synthesis is phrased as based on retrieved Calendar facts so it does
not imply completeness. Malformed connector output, inconsistent record
counts, or an invalid briefing plan fails validation instead of producing an
apparently trustworthy result.

Every briefing item retains its authoritative source name, source record
identifier, and display link when supplied. Priority recommendations expose
the deterministic facts used to include them; there is no hidden composite
score.

On a non-workday, the reduced composer omits task-driven outcomes, Up Next,
Important Tasks, and focus-block recommendations. It retains current Calendar
commitments, explicit preparation, concise future awareness, and Source
Coverage. An explicit invocation override may classify that date as a workday.

## Current limitations

- The demonstrations described here use only synthetic source records held in
  memory.
- The bounded live Calendar trial is complete and stopped; these commands do
  not use its authorization or make live requests.
- The reduced composer does not infer people waiting, commitments at risk, or
  a recommended focus block.
- The pipeline does not yet apply the Milestone 2 correction state during
  briefing composition.
- Invocation is manual and output is printed to standard output.
- The demonstration is not a product-acceptance claim.
