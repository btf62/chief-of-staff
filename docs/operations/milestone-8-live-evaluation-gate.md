# Milestone 8 Live OpenAI Evaluation Gate

- **Status:** Proposed
- **Owner:** Brad
- **Last updated:** 2026-07-29

This proposal defines a later, separately authorized comparative evaluation of
the accepted
[`contextual_action_classification`](../product/features/contextual-action-classification-v1.md)
task. It does not authorize an API key, billing setup, an API call, hosted
inference, private-data egress, or a production model.

The first live provider evaluation should use synthetic Tier 1 scenarios.
Minimized live Work Gmail evidence remains a separate, visible approval within
any later trial plan.

## Decisions Brad must approve

| Decision | Proposed bounded choice or required confirmation |
| --- | --- |
| OpenAI organization and project | Exact organization and dedicated project ID; no default-organization assumption |
| Ownership and billing | Named organizational owner, billing owner, project budget, and spend alerts |
| Retention status | Confirm standard, Modified Abuse Monitoring, or Zero Data Retention at both organization and project levels |
| Provider-policy review owner | Name the person responsible for reviewing retention, endpoint, model, and feature changes |
| Keychain identity | Approve exact service and account names; proposed pattern: `chief-of-staff/openai` and `milestone-8-evaluation-api-key` |
| Candidate models | Comparative candidates: `gpt-5.6-terra` and `gpt-5.6-luna`; reverify project, Structured Outputs, and retention eligibility immediately before use |
| Endpoint and features | `POST /v1/responses`, strict `text.format` Structured Outputs, `store=false`; no tools, stateful history, background mode, files, search, MCP, containers, or fine-tuning |
| Sensitivity | Tier 1 ordinary operational only |
| Initial evidence | Synthetic contextual promises, waiting expectations, and meeting-preparation scenarios only |
| Evidence limits | No more than 3 items, 600 characters per item, and 1,200 total evidence characters per request |
| Calls per run | Proposed maximum of 20 total calls, one response per candidate, no silent retry |
| Timeout and retry | Proposed 20-second timeout and zero automatic retries |
| Trial cost | Brad must approve an exact dollar maximum after current pricing is reviewed |
| Local retention | Persist only non-content audit metadata and accepted structured conclusions under ADR-0004; do not persist raw prompts or provider responses |
| Private review | One ignored, mode-`0600` comparison artifact containing only the minimum approved evidence and structured results |
| Acceptance thresholds | Zero false-positive actionable claims in the bounded trust set; zero schema, provenance, secret-egress, or correction regressions; category-specific precision reviewed by Brad |
| Live Work Gmail evidence | Not approved by this proposal; requires a separate explicit yes/no decision after the synthetic trial |

## Preflight

Before any request:

1. Verify the exact organization, project, owner, billing responsibility, and
   spend limit.
2. Verify the project-level retention setting and current official data-control
   documentation.
3. Verify candidate model, Structured Outputs, Responses API, and retention
   eligibility.
4. Approve the exact model configurations to compare without designating
   either as production.
5. Create the Keychain entry through a separately approved secure flow.
6. Confirm the adapter remains disabled outside the bounded evaluation.
7. Run credential, private-data, configuration, and no-network tests.

## Mandatory stop

The later synthetic live trial must stop after its bounded comparison and
private review artifact. Selecting a production model, enabling routine hosted
inference, or including minimized live Work Gmail evidence each requires
another explicit approval.
