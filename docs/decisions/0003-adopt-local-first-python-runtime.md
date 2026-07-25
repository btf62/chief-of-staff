# ADR-0003: Adopt a Local-First Python Runtime

- **Status:** Accepted
- **Date:** 2026-07-25
- **Owners:** Brad

## Context

[Daily Briefing v1](../product/features/daily-briefing-v1.md) is a
single-user system that reads private information from approved sources,
performs normalization and inference, maintains bounded local correction
state, and presents a daily briefing.

The initial architecture should minimize operational complexity and privacy
exposure while supporting connector integration, structured data processing,
AI-assisted inference, testing, and future scheduled execution.

A dedicated Mac mini may become available later, but implementation must not
depend on it. Brad's current Mac should be a supported initial host.

## Decision drivers

- Minimize the initial privacy, security, and operational footprint.
- Support connector integrations, structured data processing, AI-assisted
  inference, evaluation, and rapid iteration.
- Keep private state close to the single primary user.
- Support the current Mac without depending on a future dedicated host.
- Preserve clear internal boundaries and future deployment portability.
- Avoid distributed-system complexity before requirements demonstrate a need.

## Options considered

### Option 1: Hosted-first web application

A hosted application would provide better continuous availability, easier
scheduled execution, and access from multiple devices. It was not selected for
Version 1 because it would introduce a larger privacy and security boundary,
greater credential and infrastructure complexity, and a higher operational
burden before those costs are justified for a single-user experimental
system.

### Option 2: Desktop-native application

A desktop-native application could provide strong Mac integration and a
packaged user experience. It was not selected as the initial architecture
because it would require more user-interface-specific engineering before the
product pipeline is proven and would reduce implementation flexibility. A
lightweight local web interface can provide the required interaction more
simply.

### Option 3: TypeScript or Node.js runtime

TypeScript and Node.js provide a strong web ecosystem and could share a
language with a browser-based interface. Python was selected because it is a
strong fit for the project's initial emphasis on data integration, AI
inference, evaluation, transformation pipelines, testing, and automation.

A future web interface may still use browser technologies without changing
the core runtime decision.

### Option 4: Distributed or containerized services

Distributed services, queues, and containers could provide independent
scaling and deployment isolation. They were rejected as unnecessary
operational and development complexity for an initial single-user deployment.
Clear logical modules provide the needed separation without distributed
infrastructure.

## Decision

### Local-first execution

Daily Briefing v1 will initially run locally on Brad's Mac. Private runtime
data and correction state will remain local unless a later accepted decision
explicitly permits hosted storage or processing.

Local-first does not require every AI model to execute locally. This decision
does not authorize source-data egress; model-provider, data-egress, and
inference privacy decisions remain deferred to the appropriate inference ADR.

### Single-user product

Version 1 is designed specifically for Brad. Multi-user tenancy, generalized
account management, organizational administration, and software-as-a-service
deployment are outside scope.

### Python runtime

Python will be the primary implementation language and runtime because it
supports connector integrations, structured data processing, AI tooling,
testing, automation, and rapid iteration. Implementation will use a currently
supported stable Python version when it begins; this ADR does not lock the
project to a patch version.

### One-process initial deployment

The initial application will use one process containing clearly separated
internal modules. The logical boundaries in the
[Architecture Overview](../architecture/overview.md) remain important even
when deployed together.

Microservices, distributed queues, containers, and independently deployed
services will not be introduced without a demonstrated need and a later
accepted decision.

### On-demand execution first

The first implementation will support generating a briefing on demand.
Scheduled morning generation is deferred until the core briefing pipeline is
trustworthy. The architecture will preserve a replaceable scheduler boundary.

### Local web interface direction

The preferred Version 1 interaction surface is a lightweight local web
interface for:

- Reading the briefing
- Viewing source and confidence details
- Correcting or dispositioning inferred items

The specific framework and detailed interface design remain implementation
decisions unless they materially affect architecture. Command-line tools may
support development and operations, but they are not the intended final user
experience.

### Portable deployment

The application should move from Brad's current Mac to a future always-on Mac
mini with minimal change. A later hosted deployment should remain possible
without designing for distributed cloud scale now.

Implementation must avoid assumptions tied to one machine name, filesystem
layout, or always-awake host.

## Consequences

### Positive

- The initial security and operational footprint is smaller.
- The project can iterate quickly using a runtime well suited to connector,
  data, evaluation, and AI workflows.
- Private state remains close to the user.
- Deployment to Brad's current Mac is simple.
- The application has a clear migration path to a future Mac mini.
- Internal architecture can remain modular without distributed
  infrastructure.

### Negative

- Scheduled execution depends on the host being awake, connected, and
  authenticated.
- Remote access requires additional deliberate design.
- Local maintenance, backups, and credential health become Brad's operational
  responsibility.
- A local web interface still requires secure local access controls.
- Hosted AI providers may still create data-egress concerns that a future
  inference ADR must resolve.
- A future hosted or multi-user product may require architectural changes.

### Follow-up

- Decide persistence, retention, deletion, encryption, and backup boundaries
  before storing private state.
- Decide connector authentication and secret storage before implementing the
  first connector.
- Decide the inference provider boundary and data-egress policy before sending
  private source content to any hosted model.
- Select a local web framework and detailed interaction design only when
  implementation requires them.
- Select a scheduling mechanism only after on-demand briefing quality is
  trustworthy.

## Guardrails

- Local-first is not permission to persist unnecessary source content.
- Do not expose the local web interface beyond the local machine or a trusted
  network without a separate security decision.
- This ADR does not select a database, secret store, scheduler, AI provider,
  or specific web framework.
- This decision does not authorize implementation code or dependencies before
  the remaining applicable design decisions are documented.
- Keep all private runtime state outside Git.

## Related records and documents

- [ADR-0001: Documentation-First Development](0001-documentation-first-development.md)
- [ADR-0002: Governing Document Authority](0002-define-governing-document-authority.md)
- [Product Vision](../product/vision.md)
- [Constitution](../foundations/constitution.md)
- [Daily Briefing v1](../product/features/daily-briefing-v1.md)
- [Architecture Overview](../architecture/overview.md)
