# ADR-0008: Adopt Flask and Waitress for the Local Web Interface

- **Status:** Accepted
- **Date:** 2026-07-30
- **Owners:** Brad

## Context

[Daily Briefing v1](../product/features/daily-briefing-v1.md) requires a
local interaction surface where Brad can read briefings, inspect minimized
evidence and explanations, and correct or disposition local conclusions.
[Milestone 9](../roadmap.md#milestone-9--ranking-and-briefing-composition)
established the application-owned briefing plan and deterministic composition
boundary. Milestone 10 now needs a framework and serving decision that
preserves the existing single-user, local-first Python and SQLite
architecture.

The interface handles private local records and state-changing corrections.
It therefore needs strong default escaping, explicit request and response
protections, testable form handling, and a normal operating server that is not
a development server. At the same time, the project does not need a separate
frontend application, remote deployment, distributed services, or continuous
background work.

The following release and compatibility facts were verified on 2026-07-30:

- [Flask 3.1.3](https://pypi.org/project/Flask/) is the current stable Flask
  release. Its package metadata requires Python 3.9 or newer.
- [Waitress 3.0.2](https://pypi.org/project/waitress/) is the current stable
  Waitress release. It is a pure-Python WSGI server requiring Python 3.9 or
  newer.
- Both exact releases install and import successfully in the repository's
  CPython 3.14.3 environment. Fresh-install and application tests remain
  required as implementation validation.
- Flask's official
  [Waitress deployment guidance](https://flask.palletsprojects.com/en/stable/deploying/waitress/)
  documents explicit `127.0.0.1` binding.
- Flask's official
  [deployment guidance](https://flask.palletsprojects.com/en/stable/deploying/)
  says its development server must not be used for normal non-development
  operation, including private local operation.
- Flask's official
  [security guidance](https://flask.palletsprojects.com/en/stable/web-security/)
  covers trusted-host validation, request-size limits, Jinja escaping, CSRF
  protection, cookie settings, and browser security headers.
- Waitress's official
  [configuration guidance](https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html)
  documents clearing untrusted proxy headers and not configuring a trusted
  proxy when no proxy exists.

## Decision drivers

- Preserve the accepted local-first, single-process Python architecture.
- Reuse the existing domain, briefing, correction, persistence, and SQLite
  boundaries.
- Keep private records on the local machine and expose the server only through
  IPv4 loopback.
- Make HTML escaping, form validation, security headers, and request tests
  straightforward.
- Provide a calm server-rendered briefing instead of an analytics dashboard.
- Minimize dependencies, build tooling, JavaScript, deployment surfaces, and
  operational burden.
- Support CPython 3.14 and a future move to another local Mac with minimal
  change.

## Options considered

### Option 1: Python standard-library HTTP serving

The standard library could serve a small local interface without another
runtime dependency. It does not provide the routing, templating integration,
session handling, request validation, or test-client support needed here.
Building those controls directly would create more security-sensitive custom
code than the dependency reduction justifies.

### Option 2: FastAPI or Starlette

FastAPI and Starlette provide strong typed API and asynchronous application
patterns. Milestone 10 is a synchronous, server-rendered, single-user
interface, not an API service. Their ASGI boundary and API-oriented ecosystem
would introduce concepts the accepted architecture does not need.

### Option 3: JavaScript single-page application

A React, Vue, Svelte, or similar application could provide rich client-side
interaction. It would require Node tooling, a client application and API
boundary, browser-held state, and a larger dependency and security surface.
Those costs do not improve the required briefing and correction workflow.

### Option 4: Desktop-native shell

A native macOS or cross-platform shell could offer operating-system
integration and application packaging. It would create another UI runtime and
packaging boundary before the product interaction is validated. A loopback
web interface is smaller and remains portable to a future local Mac.

### Option 5: Flask with server-rendered templates

Flask provides a small WSGI application boundary, Jinja templates with
automatic HTML escaping, signed session support, request limits,
trusted-host configuration, and a mature test client. Waitress provides the
installed non-development WSGI server. This option directly matches the
existing synchronous Python application and requires no separate frontend or
service.

## Decision

Chief of Staff will use:

- Flask 3.1.3;
- Jinja server-rendered templates;
- local static CSS;
- minimal progressive enhancement only where necessary;
- Waitress 3.0.2 as the installed local WSGI server; and
- the existing Python application, domain boundaries, and SQLite database.

The supported server binds explicitly and only to `127.0.0.1`. It does not
bind to every interface, a LAN address, or a trusted network. Flask debug mode
and the interactive debugger are disabled, and Flask's development server is
not a supported normal-operation path.

The application validates exact loopback Host and Origin values for its
documented port, trusts no forwarded headers or proxy, uses no CORS, and
exposes no remote API. Every mutation uses a server-rendered POST form with a
session-bound CSRF token, request-size and field validation, an idempotency or
version token, and post/redirect/get behavior.

The process generates a new session-signing secret at startup. Session cookies
contain no private record data, are `HttpOnly`, use `SameSite=Strict`, and
have a bounded lifetime. They are intentionally not marked `Secure` because
the approved interface uses plain HTTP over IPv4 loopback only; a `Secure`
cookie would not operate correctly in that boundary. Any remote or TLS
deployment requires a new security decision.

Templates and responses use automatic escaping, local-only content security
policy, no-store caching, frame protection, no-referrer behavior, MIME
sniffing protection, and a restrictive permissions policy. Source links are
validated before rendering. No raw source HTML is trusted.

The interface will not add:

- React, Vue, Svelte, or another single-page application framework;
- Node or frontend build tooling;
- a separate API service;
- a remote hosting platform;
- a reverse proxy;
- a dashboard or CSS framework;
- externally hosted assets, analytics, or telemetry;
- WebSockets;
- a service worker;
- a background worker, service, or login item; or
- browser storage containing private records.

## Consequences

### Positive

- The user interface remains in the existing Python process and SQLite
  boundary.
- Jinja autoescaping and Flask's request lifecycle provide a compact,
  testable security foundation.
- Waitress supplies a supported non-development server without a compiler or
  another runtime.
- Server-rendered forms keep private state and correction authority on the
  server.
- The application remains easy to run on the current Mac and move to a future
  local Mac.

### Negative

- The local process must be running while the interface is in use.
- Loopback HTTP does not provide TLS; safety depends on strict loopback binding
  and host/origin enforcement.
- Rich client-side interaction is deliberately limited.
- A later remote, multi-user, mobile, or hosted interface would require a new
  security and deployment design.
- Flask and Waitress add direct runtime dependencies and their transitive
  maintenance obligations.

### Follow-up

- Implement the Milestone 10 briefing, evidence, disposition, recurrence, and
  deletion flows within this boundary.
- Add contract tests for loopback binding, trusted hosts, origins, CSRF,
  request limits, cookies, response headers, escaping, and the absence of
  connector, provider, and external-write calls.
- Reverify dependency and Python compatibility during routine dependency
  updates.
- Record a separate decision before adding remote access, TLS termination,
  another process, scheduling, or background execution.

## Related records and documents

- [ADR-0003: Adopt a Local-First Python Runtime](0003-adopt-local-first-python-runtime.md)
- [ADR-0004: Adopt SQLite and a Bounded Local Data Lifecycle](0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
- [ADR-0005: Adopt OAuth and macOS Keychain for Connector Credentials](0005-adopt-oauth-and-macos-keychain.md)
- [Architecture Overview](../architecture/overview.md)
- [Daily Briefing v1](../product/features/daily-briefing-v1.md)
- [Ranking and Briefing Composition v1](../product/features/ranking-and-briefing-composition-v1.md)
- [Implementation Roadmap](../roadmap.md)
