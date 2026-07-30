# Contributing

## Current scope

The Version 1 design baseline and Milestones 1–10 are complete and accepted.
Milestone 11 operational hardening may proceed through its approved local and
synthetic review gate. Contributions may improve authoritative documentation
or the non-live implementation when explicitly authorized. Do not repeat live
retrieval, make a provider call, broaden an authorization boundary, refresh
credentials, begin another connector, enable scheduling, modify an external
system, or treat Milestone 11 as accepted without new explicit approval. Do
not begin a later milestone before its dependencies and acceptance gate are
satisfied.

## Python environment

The project supports CPython 3.14.x. The `.python-version` file selects the
minor line without locking contributors to one patch release; use the current
maintenance patch available for Python 3.14.

Python minor-version changes are deliberate compatibility updates. Update
`requires-python`, `.python-version`, CI, tool configuration, and this policy
together after the new minor line is evaluated.

The project uses the standard-library `venv` module and pip dependency groups.
The ignored `.venv/` directory is the default local environment. Runtime
dependencies belong in `project.dependencies`; development-only tools belong
in the `dev` dependency group in `pyproject.toml`. Direct runtime dependencies
are exact-pinned: the OpenAI SDK to the version evaluated for the bounded
Milestone 8 Responses transport, and Flask and Waitress to the releases
verified for the local web boundary in
[ADR-0008](docs/decisions/0008-adopt-flask-local-web-interface.md). Do not add
a general AI or frontend framework or change these pins without the applicable
boundary and fresh-install validation.

Create or refresh the environment:

```text
make bootstrap
```

If `python3.14` is not on `PATH`, pass its absolute path:

```text
make bootstrap PYTHON=/path/to/python3.14
```

Do not install project tools into the macOS system Python.

## Developer commands

| Command | Purpose |
| --- | --- |
| `make bootstrap` | Create `.venv`, update pip, and install the package and exact-pinned development tools |
| `make format` | Format Python and apply safe Ruff fixes |
| `make lint` | Verify formatting and run Ruff lint rules |
| `make typecheck` | Run strict mypy checks against application, test, tool, and example Python |
| `make test` | Run pytest |
| `make docs-check` | Validate local Markdown links and anchors |
| `make inference-eval` | Run the mocked Milestone 8 inference evaluation |
| `make ranking-eval` | Generate the private synthetic Milestone 9 review artifacts |
| `make demo` | Print the repository-plus-mocked-Calendar briefing |
| `make demo-synthetic` | Print the fully synthetic reduced briefing |
| `make check` | Run the complete local quality gate |

GitHub Actions runs the same `make bootstrap` and `make check` workflow on
Python 3.14.

## Configuration and logging boundaries

`chief_of_staff.config.RuntimeSettings` is the application boundary for
validated, non-secret runtime configuration. Current variables are limited to:

- `CHIEF_OF_STAFF_ENVIRONMENT`
- `CHIEF_OF_STAFF_LOG_LEVEL`
- `CHIEF_OF_STAFF_DATABASE_PATH`

Do not place tokens, credentials, or private source content in environment
configuration. Connector secrets belong in macOS Keychain under
[ADR-0005](docs/decisions/0005-adopt-oauth-and-macos-keychain.md).

Application logs are newline-delimited JSON. The logging boundary emits only
allow-listed operational metadata, drops free-form message content, redacts
secret-shaped strings, and records only exception types. Do not bypass this
boundary or add private content to the allow list.

## Workflow

1. Identify the document that owns the topic.
2. State assumptions and open questions.
3. Make the smallest complete change.
4. Update related links, status fields, or decision records.
5. Review the rendered Markdown and repository diff.

## Privacy and sensitivity

All contributions must follow the authoritative
[privacy and sensitivity policy](AGENTS.md#privacy-and-sensitivity). Include
only the minimum primary-user context necessary, and keep the repository safe
to share publicly.

## Proposing a feature

Start with [`templates/feature-spec.md`](templates/feature-spec.md). A proposal
should describe the user problem, desired outcome, non-goals, constraints, and
measurable acceptance criteria without prematurely selecting an implementation.
Accepted feature specifications belong in `docs/product/features/`.

## Recording a decision

Use [`templates/decision-record.md`](templates/decision-record.md) for choices
that affect architecture, security, privacy, operations, or future flexibility.
Architecture and significant product decision records belong in
`docs/decisions/` and use the next available four-digit number.

## Commit guidance

Use concise, imperative commit messages. Keep unrelated documentation changes
separate so reviewers can understand the intent and history.
