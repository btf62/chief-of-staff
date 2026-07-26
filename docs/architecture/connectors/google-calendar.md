# Google Calendar Connector

- **Status:** Accepted
- **Version:** 2
- **Owner:** Brad
- **Last updated:** 2026-07-26

This specification defines the implemented read-only Google Calendar
connector and the explicitly approved bounded live trial that completed
Milestone 4. It does not authorize continuing live access, broader Calendar
access, another account, or another connector.

## Source authority

Google Calendar remains authoritative for current event titles, times,
statuses, locations, meeting links, and other Calendar-owned facts. The
connector retrieves event facts and provenance only. It does not rank
priorities, infer commitments, replace the live calendar with a stored
schedule, or modify Calendar.

## Account and resource boundary

Version 1 retrieval is restricted to:

- One Google Workspace account explicitly selected and confirmed by Brad
  during authorization. Its address remains absent from Git.
- That account's `primary` calendar only.
- A bounded window supplied by the briefing invocation.
- Expanded recurring-event instances ordered by start time.
- Deleted events excluded.
- All result pages followed until complete or a bounded failure occurs.

Secondary calendars, calendar-list discovery, free/busy access, settings,
ACLs, and cross-account fallback are not authorized. The OAuth application
belongs to a Northridge-controlled Google Cloud project with an internal
audience.

## OAuth scope

The only accepted scope is:

```text
https://www.googleapis.com/auth/calendar.events.owned.readonly
```

Google documents this scope as viewing events on calendars the user owns. It
supports `events.list`, is narrower than event access across all accessible
calendars, and does not grant Calendar event mutation. It is treated as
sensitive because it reads private Calendar events. The implementation rejects
missing, broader, or additional scopes rather than silently accepting scope
expansion.

The provider scope can technically read events on other calendars the user
owns. The application accepts that residual provider limitation while fixing
every request to `calendarId=primary` and enforcing the boundary in contract
tests.

Official references:

- [Google Calendar API scopes](https://developers.google.com/workspace/calendar/api/auth)
- [Google Calendar `events.list`](https://developers.google.com/workspace/calendar/api/v3/reference/events/list)
- [Google Calendar pagination](https://developers.google.com/workspace/calendar/api/guides/pagination)
- [Google OAuth for desktop applications](https://developers.google.com/identity/protocols/oauth2/native-app)
- [Google sensitive-scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)

## Authorization and credential boundary

The implemented authorization follows
[ADR-0005](../../decisions/0005-adopt-oauth-and-macos-keychain.md):

- Google OAuth installed-application authorization-code flow.
- System browser and loopback redirect.
- Cryptographically random state with validation.
- PKCE using `S256`.
- Explicit account selection and a Brad-confirmed account identity.
- Exact-scope validation after token exchange.
- No offline access or refresh token for the bounded trial.
- OAuth client secret and access token stored only in macOS Keychain.
- Non-secret OAuth project, client, account, scope, expiry, health, and
  Keychain lookup metadata stored in SQLite.

Secret values are never written to SQLite, Git, configuration, logs, fixtures,
or command output. The account identity and credential health can be displayed
without revealing a secret.

## Read-only transport contract

The provider transport exposes only `list_events`. It uses `GET` against the
Google Calendar `events.list` resource and fixes:

- Calendar ID `primary`.
- Bounded `timeMin` and `timeMax`.
- Invocation timezone.
- `singleEvents=true`.
- `showDeleted=false`.
- `orderBy=startTime`.
- A bounded page size and optional opaque page token.

The connector and transport expose no insert, create, update, patch, delete,
move, import, watch, ACL, settings, send, or other mutation operation.

## Retrieved and normalized data

The live boundary reads only the provider fields needed to normalize:

- Stable Google event ID.
- Title.
- Status.
- Provider event type, used to distinguish working-location and out-of-office
  status signals from appointments.
- Timezone-aware start and end, including all-day dates.
- Optional location summary.
- Event update time as freshness.
- Authoritative event link when available.
- Retrieval and source-coverage metadata.

Descriptions, attendees, attachments, conference payloads, and private
extended properties are ignored. Invalid events are omitted with partial
coverage rather than converted into unsupported facts.

Working-location and similar routine status signals remain available to
schedule interpretation but are normally suppressed from visible briefing
sections. Provider-identified out-of-office events, explicit preparation, or
other authoritative materiality evidence may make a status signal visible.

## Pagination and failure behavior

- All pages retrieved: `complete`, including a legitimate zero-event result.
- A later page fails after earlier events were retrieved: retain those events
  and report `partial`.
- The first page fails: `unavailable`.
- Authorization is missing, expired, revoked, or scope-mismatched:
  `unauthorized`, distinct from an empty calendar.
- A malformed event: omit it and report `partial`.
- A repeated page token or the 100-page safety limit: stop and report
  `partial`.

Warnings disclose the failure category and page boundary without provider
response content. The connector does not broaden scope, change accounts,
substitute cached events, or retry through a write-capable endpoint.

## Persistence, retention, and observability

No Calendar source cache is authorized. Raw provider pages and normalized
events are transient pipeline inputs. The accepted local run graph stores:

- Non-secret authorization and credential-health metadata.
- Connector status, approved scope, bounded retrieval window, freshness,
  coverage, safe error category, and page count.
- Minimal source record identifiers, authoritative links, timestamps, and
  evidence fingerprints.
- Application-owned briefing-run metadata and private ignored output.

It does not store event excerpts or raw provider payloads. This lifecycle
follows
[ADR-0004](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md).

## Implemented validation

Synthetic contract and integration tests demonstrate:

- Exact read-only scope enforcement.
- State and PKCE authorization parameters without offline access.
- Keychain-only secret handling.
- Authorized, expired, missing, and unauthorized behavior.
- Empty-calendar distinction.
- Primary-calendar-only live requests.
- Multi-page retrieval and retention of prior pages after partial failure.
- All-day and timezone-aware normalization.
- Freshness, coverage, source provenance, and minimal persistence.
- Transient raw payloads and ignored private briefing output.
- Absence of mutation operations.
- Presentation-budget compliance in deterministic on-demand briefings.

One explicitly approved trial validated the live boundary against the selected
primary calendar using the beginning of the trial day through seven days ahead
in the configured timezone. It invoked no hosted inference, other connector,
external-link retrieval, or Calendar mutation.

## Bounded live-trial authorization

Brad explicitly approved one bounded trial subject to this specification. The
trial is complete, and the mandatory stop is in effect.

No further Calendar retrieval, reauthorization, token refresh, account change,
scope change, secondary-calendar access, or additional live connector is
authorized without a new explicit approval.
