# Milestone 8 Live OpenAI Evaluation Gate

- **Status:** Accepted
- **Version:** 2
- **Owner:** Brad
- **Last updated:** 2026-07-29

This document records the authorized and completed comparative evaluation of
the accepted
[`contextual_action_classification`](../product/features/contextual-action-classification-v1.md)
task. The one-time authorization permitted a dedicated project and credential
plus twenty synthetic Tier 1 Responses API calls. It did not authorize
private-source evidence or routine hosted inference.

The trial ended after its private comparison artifact was produced. Brad later
reviewed the results and selected the task-specific production configuration
without making another call. Any repeat call, private-data egress, or routine
hosted use requires new explicit approval.

## Accepted configuration

| Decision | Accepted boundary |
| --- | --- |
| OpenAI organization and project | One dedicated `Chief of Staff — M8 Evaluation` project in a verified Northridge-controlled organization; private identifiers remain only in ignored local configuration |
| Ownership and billing | Brad is an organization owner, project owner, and provider-policy review owner; existing organization API billing was active |
| Retention status | Standard provider retention; `store=false` disables Responses application-state storage but does not imply Zero Data Retention |
| Project spend control | $1 monthly hard limit, with the provider warning that enforcement is not instantaneous; the application separately enforces a $1 trial cap |
| Project model access | Allow only `gpt-5.6-terra` and `gpt-5.6-luna` |
| Service account | Project-scoped `chief-of-staff-local` with a custom Responses-only role |
| Keychain identity | Service `chief-of-staff/openai`; account `milestone-8-evaluation-api-key` |
| Endpoint and features | `POST /v1/responses`, strict `text.format` Structured Outputs, `store=false`; no tools, stateful history, background mode, files, search, MCP, containers, or fine-tuning |
| Sensitivity | Tier 1 ordinary operational only |
| Evidence | Ten synthetic contextual, exclusion, conflict, and adversarial scenarios; no live-source evidence |
| Evidence limits | No more than 3 items, 600 characters per item, and 1,200 total evidence characters per request |
| Calls | Exactly 20 maximum: 10 per model, one response per scenario, with no retry |
| Timeout and execution | 20 seconds, low reasoning effort, default service tier, non-streaming |
| Trial cost | $1 maximum; conservative preflight maximum $0.188476 |
| Prompt caching | Explicit caching mode with no breakpoints; any observed cache read or write fails the gate |
| Local retention | Persist only non-content audit metadata; do not persist raw provider responses or production conclusions |
| Private review | One ignored, mode-`0600` comparison artifact containing only the minimum approved evidence and structured results |
| Acceptance thresholds | Zero false-positive actionable claims, invented references, secret egress, correction regressions, or policy-invalid accepted results; category-specific precision reviewed by Brad |
| Work Gmail evidence | Prohibited during this trial and still not authorized for hosted inference |

## Provider-policy verification

The following facts were reverified from current provider documentation on
2026-07-29:

- [Projects and service accounts](https://help.openai.com/en/articles/9186755-managing-your-work-in-platform-with-projects)
  support project-scoped credentials, model controls, and project budgets.
- The [Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses)
  is the current recommended stateful-capable API, while this trial explicitly
  disabled provider state with `store=false`.
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
  supports strict application-owned JSON Schema output.
- [Data controls](https://developers.openai.com/api/docs/guides/your-data)
  state that API data is not used for training by default and that standard
  abuse-monitoring logs may retain content for up to 30 days. The organization
  did not expose a Modified Abuse Monitoring or Zero Data Retention selection.
- [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
  documents explicit caching mode. Omitting explicit breakpoints disables
  cache writes; the trial observed zero cached-input and cache-write tokens.
- [API-key safety](https://developers.openai.com/api/docs/guides/production-best-practices#api-keys)
  requires secure server-side storage; the project key remains only in macOS
  Keychain.
- The candidate model pages for
  [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
  and
  [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
  documented Responses and Structured Outputs support.
- [Current pricing](https://developers.openai.com/api/docs/pricing) was used
  for the application-owned cost estimate. Standard short-context rates were
  $2.50/$15.00 per million input/output tokens for Terra and $1.00/$6.00 for
  Luna.

The provider-controlled monthly hard limit may be exceeded slightly because
enforcement is not instantaneous. The application preflight and per-call
boundaries remain the authoritative trial controls.

## Completed comparison

The one-time synthetic comparison completed on 2026-07-29:

| Metric | Terra | Luna |
| --- | ---: | ---: |
| Calls attempted / completed | 10 / 10 | 10 / 10 |
| True positives | 1 | 2 |
| False positives | 0 | 0 |
| False negatives | 2 | 1 |
| Correct exclusions | 3 | 3 |
| Insufficient-evidence results | 1 | 3 |
| Safe policy rejections | 2 | 1 |
| Schema / provenance / provider failures | 0 / 0 / 0 | 0 / 0 / 0 |
| Average / maximum latency | 1,808 / 2,796 ms | 1,689.7 / 2,091 ms |
| Input / output / reasoning tokens | 2,934 / 863 / 0 | 2,934 / 1,160 / 274 |
| Estimated cost | $0.020283 | $0.009894 |

Total estimated cost was $0.030177. No cache read or write tokens were
reported, and no correction regression occurred.

The three policy rejections were moderate-uncertainty actionable suggestions.
The application correctly rejected them under its precision-first rule and
entered deterministic reduced mode; they were not policy-invalid accepted
results.

## Accepted task-specific selection

Brad reviewed the category-specific results and selected:

| Setting | Accepted value |
| --- | --- |
| Task | `contextual_action_classification` |
| Provider | OpenAI |
| Model | `gpt-5.6-luna` |
| Reasoning effort | `low` |
| Endpoint and controls | Exact configuration exercised by this comparison |

Luna produced zero false-positive actionable claims, fewer false negatives
than Terra, correct `insufficient_evidence` behavior for conflicting and
adversarial scenarios, successful schema, provenance, policy, correction, and
provider gates, slightly lower average latency, and lower cost.

This is not a universal Chief of Staff model selection. No model is selected
for ranking, priority comparison, Chief of Staff Note synthesis, section
prose, or another future inference task. The adapter remains disabled by
default, and the selected configuration does not authorize provider calls or
private-source egress.

## Mandatory stop

The synthetic live authorization is consumed. Do not repeat an API call,
refresh or broaden the credential, send private source evidence, enable
routine hosted inference, or apply the selected model to another task without
a new explicit instruction from Brad.
