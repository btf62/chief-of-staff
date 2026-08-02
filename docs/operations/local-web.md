# Local Web Interface Operations

- **Status:** Accepted
- **Owner:** Brad
- **Last updated:** 2026-07-31

This document describes the implemented Milestone 10 local interface under
[ADR-0008](../decisions/0008-adopt-flask-local-web-interface.md). It does not
authorize remote exposure, live retrieval, hosted inference, background
operation, scheduling, or external-source writes. Brad reviewed the actual
interface, a successful five-source July 30 briefing, correction controls and
evidence links, and the four-page PDF rendering, then accepted Milestone 10.

## Start

Create or refresh the supported environment, then run:

```text
make bootstrap
make web
```

`make bootstrap` refreshes an older editable installation as well as creating
the project-owned environment. It installs the `chief-of-staff-web` entry
point, but normal repository operation does not depend on a shell activation
or a previously installed entry point.

`make web` opens and migrates `.local/state.sqlite3`, starts Waitress with
one application thread, binds only to `127.0.0.1:8765`, and prints the safe
local URL and operational status. It does not open a browser.

Open the browser automatically after the server is ready with:

```text
make web-open
```

The module-based launch remains supported:

```text
.venv/bin/python -m chief_of_staff.web.server
.venv/bin/python -m chief_of_staff.web.server --open
```

Use another explicit local port only when needed:

```text
chief-of-staff-web --port 8767
```

The selected port becomes part of the exact trusted Host and Origin boundary.
The command fails if the port is unavailable; it does not silently choose
another port.

Use a different explicit database path for synthetic review or recovery:

```text
chief-of-staff-web --database /absolute/path/to/state.sqlite3
```

Do not pass a database from an untrusted source.

## Open again

While the process is running, open the exact URL printed at startup. With the
default configuration, that URL is:

```text
http://127.0.0.1:8765
```

`localhost`, a LAN address, `0.0.0.0`, and a remote hostname are not supported
aliases. The interface intentionally uses plain HTTP over IPv4 loopback only.
Its session cookie is therefore `HttpOnly` and `SameSite=Strict` with a
bounded lifetime, but not `Secure`; marking it `Secure` would prevent correct
operation over the accepted loopback HTTP boundary. Remote or TLS use requires
a new security decision.

## Stop

Press Control-C in the foreground terminal, or stop the exact project-owned
process from another terminal:

```text
make web-stop
```

The stop command uses a private mode-`0600` PID file beside the local database,
verifies the process belongs to the current user and matches the supported
Chief of Staff server command, and refuses to signal an unrelated process.
Waitress and the application-owned SQLite connection shut down before the
command exits. Milestone 10 creates no background service, login item, worker,
or scheduled web process.

The local interface never invokes a connector. When no completed briefing
exists, it directs Brad to run `make briefing` in Terminal and refresh.

When a Scheduled Morning trial exists, the home page also shows its enabled or
completed state, accepted date boundary, count of recorded eligible dates, and
latest safe outcome. This view contains no connector content, account
identity, credential value, or source record. It remains a read-only status
surface; opening the interface never triggers a scheduled or on-demand run.

## Time and print presentation

The briefing heading shows when the selected-day briefing was generated.
Timed items use written `Earlier today`, `In progress`, and `Upcoming` labels
as well as visual treatment. Earlier items remain visible and secondary;
generation time never removes the earlier shape of the day.

Print styles keep the Chief of Staff Note and individual items together when
practical, avoid isolated headings, reduce interactive review links, and use
clean page margins. Browser-added print headers and footers are controlled by
the browser print dialog, not by Chief of Staff; disable them there when a
clean PDF is needed.

## Local data

The default database is:

```text
.local/state.sqlite3
```

It is ignored by Git and created with mode `0600`. The local web tables contain
only structured briefing presentation, source links, correction events,
derived current state, and minimal deletion tombstones. They do not contain
credentials, raw Gmail bodies, MIME payloads, provider responses, hidden model
reasoning, or browser-held private records.

Every correction form states that it changes Chief of Staff's local
interpretation only. Gmail, Calendar, Todoist, Jira, and other authoritative
sources remain unchanged.

## Diagnose startup errors

### Local database error

The command reports a local database error without printing records or
credential metadata when the path cannot be opened, migration validation
fails, or SQLite integrity requirements are unavailable.

- Confirm that the parent directory is writable.
- Confirm that the database is not an untrusted copy.
- Run `make check` before changing migration or database code.
- Do not delete the default database merely to bypass a migration error.

### Local port unavailable

The command reports that the local port is unavailable and exits.

- Stop the prior `chief-of-staff-web` process with Control-C, or
- restart with another explicit port and use the exact printed URL.

The command does not bind another interface or trust proxy headers as a
fallback.

## Security boundary

- Waitress, not Flask's development server, is the supported server.
- Debug mode and interactive tracebacks are disabled.
- Unexpected Host, Origin, remote-address, and forwarded-header values are
  rejected. A sandboxed local browser's opaque `null` Origin is accepted only
  when browser-controlled Fetch Metadata identifies a same-origin navigation.
  The exact Host, loopback address, session-bound CSRF, SameSite cookie, and
  signed version and idempotency token remain mandatory.
- Mutations use POST, session-bound CSRF protection, version and idempotency
  tokens, request-size limits, server validation, and post/redirect/get.
- Responses use a local-only content security policy, no-store caching, MIME
  sniffing protection, frame denial, no-referrer behavior, and a restrictive
  permissions policy.
- Templates escape source-derived and user-entered text. Source URLs are
  limited to ordinary HTTP or HTTPS links.
- The interface exposes no CORS policy, remote API, external assets,
  telemetry, service worker, or browser storage for private records.

## Acceptance

Brad accepted the Milestone 10 local interface after reviewing it at normal
browser zoom with a successful five-source July 30 briefing, its correction
controls and evidence links, and the four-page PDF rendering.

The Milestone 11 synthetic interface review passed at 1280 and 560 CSS pixels
without horizontal overflow. Its three-page letter-size PDF kept the Chief of
Staff Note and individual briefing items together, avoided isolated headings,
and retained readable secondary source links without clipping or overlap.
On 2026-07-30, Brad reviewed the corrected private package and explicitly
approved it. That human review—not artifact presence or passing automation
alone—accepted Milestone 11 and the on-demand Daily Briefing v1 MVP.
