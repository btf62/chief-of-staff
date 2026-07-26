# Google Calendar Connector

- **Status:** Proposed — live-access approval required
- **Version:** 1
- **Owner:** Brad
- **Last updated:** 2026-07-25

This specification defines the implemented read-only contract and mocked OAuth
boundary for the Milestone 4 Google Calendar connector. It is ready for
live-access review, but it does not authorize OAuth registration, a live scope
request, account authorization, Keychain storage, a production transport, or
access to Calendar data.

## Source authority

Google Calendar remains authoritative for current event titles, times,
statuses, locations, meeting links, and other Calendar-owned facts. The
connector retrieves event facts and provenance only. It does not rank
priorities, infer commitments, replace the live calendar with a stored
schedule, or modify Calendar.

## Proposed account and resource boundary

Version 1 proposes:

- One Google account selected by Brad at authorization time and represented in
  application metadata by an opaque, non-email alias.
- That account's `primary` calendar only.
- A bounded window supplied by each briefing invocation.
- Expanded recurring-event instances ordered by start time.
- Deleted events excluded.
- All result pages followed until complete or a bounded failure occurs.

The exact Google account remains intentionally absent from Git and must be
confirmed at the live-access gate. Secondary calendars, calendar-list
discovery, free/busy access, settings, ACLs, and cross-account fallback are not
authorized.

## Proposed OAuth scope

The only proposed scope is:

```text
https://www.googleapis.com/auth/calendar.events.owned.readonly
```

Google documents this scope as viewing events on calendars the user owns. It
supports `events.list`, is narrower than event access across all accessible
calendars, and does not grant Calendar event mutation. It is treated as
sensitive because it reads private Calendar events. The implementation rejects
missing, broader, or additional scopes rather than silently accepting scope
expansion.

Official references:

- [Google Calendar API scopes](https://developers.google.com/workspace/calendar/api/auth)
- [Google Calendar `events.list`](https://developers.google.com/workspace/calendar/api/v3/reference/events/list)
- [Google Calendar pagination](https://developers.google.com/workspace/calendar/api/guides/pagination)
- [Google OAuth for desktop applications](https://developers.google.com/identity/protocols/oauth2/native-app)
- [Google sensitive-scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)

No scope has been configured or requested. Adding this scope to an OAuth
consent configuration or authorization request requires Brad's explicit
approval.

## Mocked authorization boundary

The implemented application boundary supplies only non-secret authorization
metadata:

- Opaque account reference.
- Exact granted-scope set.
- Opaque credential lookup reference.

Tests use a mock provider. They contain no client ID, client secret,
authorization code, access token, refresh token, account address, or Keychain
entry.

After approval, the live authorization design must follow
[ADR-0005](../../decisions/0005-adopt-oauth-and-macos-keychain.md):

- Google OAuth installed-application authorization-code flow.
- System browser and a loopback redirect suitable for a desktop application.
- `state` validation and PKCE.
- Offline access only if explicitly approved for future invocations.
- Secret values stored in macOS Keychain, never SQLite, Git, configuration,
  logs, fixtures, or output.
- A non-secret Keychain lookup reference separated by application, provider,
  environment, account alias, and credential purpose.

OAuth project ownership, consent-screen identity, client registration,
redirect details, selected account, Keychain entry names, refresh behavior,
revocation, and reauthorization remain live-gate decisions.

## Read-only transport contract

The provider transport exposes only `list_events`. Each request fixes:

- Calendar ID `primary`.
- Bounded `timeMin` and `timeMax`.
- Invocation timezone.
- `singleEvents=true`.
- `showDeleted=false`.
- `orderBy=startTime`.
- An optional opaque page token.

The connector and transport expose no insert, create, update, patch, delete,
move, import, watch, ACL, settings, send, or other mutation operation. There
is deliberately no live HTTP or Google SDK transport before authorization.

## Retrieved and normalized data

The mocked contract normalizes synthetic events into:

- Stable Google event ID.
- Title.
- Status.
- Timezone-aware start and end, including all-day dates.
- Optional location summary.
- Event update time as freshness.
- Authoritative event link when available.
- Retrieval and source-coverage metadata.

Invalid events are omitted with partial coverage rather than converted into
unsupported facts. Full provider payloads, attendees, descriptions,
attachments, conference payloads, and private extended properties are not
currently retrieved or persisted.

## Pagination and failure behavior

- All pages retrieved: `complete`, including a legitimate zero-event result.
- A later page fails after earlier events were retrieved: retain those events
  and report `partial`.
- The first page fails: `unavailable`.
- Authorization is missing, revoked, or scope-mismatched: `unauthorized`,
  distinct from an empty calendar.
- A malformed event: omit it and report `partial`.
- A repeated page token or the 100-page safety limit: stop and report
  `partial`.

Warnings disclose the failure category and page boundary without provider
response content. The connector does not broaden scope, change accounts,
substitute cached events, or retry through a write-capable endpoint.

## Persistence, retention, and observability

No Calendar source cache is authorized. Provider pages and normalized event
records are transient pipeline inputs. Coverage may include status, item count,
retrieval time, freshness, safe account alias, primary-calendar boundary, and
error category. It must never contain credential values or private event
content in logs.

Any later persistence of minimal evidence or application-owned conclusions
must follow
[ADR-0004](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md).

## Implemented validation

Synthetic contract and integration tests demonstrate:

- Exact read-only scope enforcement.
- Mocked authorized and unauthorized behavior.
- Empty-calendar distinction.
- Multi-page retrieval.
- Retention of prior pages after partial failure.
- All-day and timezone-aware normalization.
- Freshness, coverage, and source provenance.
- Absence of mutation operations.
- Partial-source disclosure in a deterministic on-demand briefing.

## Live-access approval gate

Before implementation continues, Brad must explicitly approve:

1. Registering or selecting the Google Cloud project and Desktop OAuth client.
2. The registration owner and consent-screen identity.
3. The exact Google account to authorize.
4. The `calendar.events.owned.readonly` sensitive scope above.
5. The primary-calendar-only resource boundary.
6. The loopback, PKCE, refresh, Keychain, revocation, and reauthorization
   approach.
7. A bounded live trial using private Calendar data.

Until that approval, the connector remains mock-only and no live Calendar
request is permitted.
