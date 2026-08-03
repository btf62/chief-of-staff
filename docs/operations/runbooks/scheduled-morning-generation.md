# Operate Scheduled Morning Generation

- **Status:** Accepted
- **Owner:** Brad
- **Last updated:** 2026-08-02

This runbook operates the self-limiting Milestone 12 trial on Brad's approved
primary Mac. It does not authorize routine unattended use after the trial,
another host, another account, a broader connector scope, hosted inference, or
an external write.

The governing product contract is
[Scheduled Morning Generation v1](../../product/features/scheduled-morning-generation-v1.md).
[ADR-0011](../../decisions/0011-require-durable-authorization-for-scheduled-connectors.md)
governs credential continuity, and
[ADR-0010](../../decisions/0010-choose-scheduled-morning-generation-mechanism.md)
governs the user-level LaunchAgent.

## Accepted operating boundary

- Host: Brad's current primary Mac
- Timezone: `America/New_York`
- Trigger: 6:00 a.m. Monday through Thursday, Saturday, and Sunday
- Ineligible day: Friday
- Catch-up: one invocation may proceed through 11:00 a.m.; after that it
  records a miss without retrieving a source
- Required evidence: repository context, Calendar, and at least one of Work
  Gmail or Todoist
- Optional evidence: Jira
- Trial length: seven eligible local dates, whether each date succeeds, fails,
  or is missed
- Retry: no automatic whole-run retry

The LaunchAgent invokes one command and exits. It does not keep the application
resident, update software, open a browser authorization flow, or run the local
web server.

## Host expectations

Scheduled generation requires:

- the approved user to be logged in;
- the Mac to be awake, or to wake while the catch-up window remains open;
- the repository and its project-owned `.venv` to remain at their configured
  paths;
- the system timezone to remain `America/New_York`;
- network access for approved connectors;
- the user's login Keychain to be unlocked and available; and
- the accepted application version and SQLite migrations to remain compatible.

Shutdown, logout, FileVault startup, a locked or unavailable Keychain, lost
network access, or a wake after the cutoff can prevent a briefing. The product
records the safe outcome; it does not promise that a powered-off Mac can run at
6:00 a.m.

## Validate without installing or retrieving

Run all repository checks:

```text
make check
make milestone-11-eval
```

Preview the exact bounded policy and LaunchAgent definition without changing
local state or contacting a connector:

```text
make scheduled-dry-run
```

Inspect host and connector readiness without retrieving source records:

```text
make scheduled-readiness
```

The readiness report contains safe health categories only. It must show
healthy refresh continuity for Calendar, Work Gmail, Todoist, and Jira
individually. It also requires the reviewed application commit to have no
tracked or untracked repository changes. Runtime provider failures may still
produce honest reduced coverage under the accepted source-sufficiency policy.

## Establish accepted authorization continuity

Calendar refresh requires one separately approved, attended browser flow under
the unchanged exact scope:

```text
https://www.googleapis.com/auth/calendar.events.owned.readonly
```

Use:

```text
.venv/bin/python -m chief_of_staff.live_cli authorize \
  --account-identity <approved-work-account> \
  --refreshable
```

Confirm the expected Google account, OAuth project, and exact single scope in
the provider screen. Stop if any value differs. The installed application flow
uses state and PKCE, stores access and refresh credentials only in macOS
Keychain, and stores only non-secret metadata in SQLite.

Work Gmail and Todoist retain their existing exact-account, exact-scope refresh
paths. Jira requires one separately approved, attended authorization with the
unchanged `read:jira-work` data permission plus `offline_access` for rotating
refresh continuity:

```text
.venv/bin/python -m chief_of_staff.jira_live_cli authorize \
  --expected-account <approved-work-account> \
  --account-reference primary-user \
  --resource-reference approved-site
```

Confirm the expected Atlassian account, application, one selected Jira site,
and exact permissions. Stop if any differ. Access and rotating refresh tokens
remain only in macOS Keychain. The attended authorization command performs
site binding but no project or issue retrieval. Scheduled operation may
refresh the stored exact grant; it never opens an interactive authorization
flow.

Run `make scheduled-readiness` again after the attended Calendar and Jira
flows. Do not perform a source retrieval merely to test installation.

## Install the bounded trial

Install and load the exact current-user service:

```text
make scheduled-install
```

Installation:

- records the first seven eligible dates in private local state;
- writes one mode-`0600` plist under the current user's
  `~/Library/LaunchAgents/`;
- loads
  `org.northridge.chief-of-staff.scheduled-morning`;
- configures no `RunAtLoad`, `KeepAlive`, or automatic retry; and
- performs no Calendar, Gmail, Todoist, or Jira retrieval.

The first eligible date is the first configured 6:00 a.m. occurrence strictly
after installation. The command refuses to replace an existing trial.

Before the first eligible date, an explicitly approved trigger-time change can
be applied without resetting or extending the trial:

```text
make scheduled-update-time
```

The update command requires a clean reviewed application version, an unstarted
trial, and the same host and connector readiness gates. It unloads and replaces
only the exact LaunchAgent, preserves the accepted first and final dates, and
leaves the trial enabled only after the replacement is loaded successfully.

## Verify installation safely

Inspect the non-content local state and LaunchAgent health:

```text
make scheduled-status
```

Test the fixed private-safe macOS notification:

```text
make scheduled-notify-test
```

Exercise reversible disablement without deleting the plist or briefing
history:

```text
make scheduled-disable
make scheduled-status
make scheduled-enable
make scheduled-status
```

These checks do not retrieve a source or consume an eligible trial date.

## Understand scheduled outcomes

The private status record uses only:

- `full_success`
- `reduced_success`
- `already_completed`
- `ineligible_day`
- `before_window`
- `missed_after_cutoff`
- `insufficient_sources`
- `credential_attention_required`
- `transient_failure`
- `configuration_failure`
- `trial_complete`

A successful scheduled briefing has a distinct immutable run ID and
`scheduled_morning` invocation mode. A repeated trigger after terminal success
returns `already_completed`. A failure is terminal for that eligible date; the
application does not retry the whole run.

Normal bounded Gmail partial coverage produces `reduced_success`. Calendar is
mandatory. Work Gmail and Todoist may substitute for one another only under
the accepted one-of-two action-source rule. Jira is optional. An unavailable
source is never represented as empty.

Notifications say only that a briefing is ready, has reduced coverage, was
missed, or needs attention. They never include event titles, message content,
task content, issue content, people, links, account identities, or credential
values.

The local interface shows the latest briefing plus a non-content scheduled
trial summary:

```text
make web-open
```

## Disable or remove

Disable the trial while preserving its definition and history:

```text
make scheduled-disable
```

Re-enable only the same incomplete accepted trial:

```text
make scheduled-enable
```

Unload and remove only the exact LaunchAgent plist while preserving local
briefing and trial history:

```text
make scheduled-remove
```

Removal does not revoke connector credentials or delete `.local/state.sqlite3`.
Those are separate lifecycle operations.

## Trial completion

Missed and failed eligible dates count toward the seven-date boundary. After
the seventh eligible date, the command disables its trial state and becomes
inert before connector inspection or retrieval. The LaunchAgent may remain
loaded, but later invocations return `trial_complete`.

Brad must review the seven-date results and explicitly accept, revise, extend,
or remove scheduling. Do not reset the trial, extend its dates, migrate it to a
Mac mini, or accept routine unattended operation without a new documented
decision.
