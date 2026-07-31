# Chief of Staff

Chief of Staff is a documentation-first project for a cross-domain AI
chief-of-staff system serving one primary user. The source systems will remain
authoritative; this project will provide a unified interpretation layer for
identifying priorities, commitments, and useful signals.

## Status

**Phase:** Milestones 1–11 and the on-demand Daily Briefing v1 MVP are
accepted; Milestone 12 implementation and its bounded trial are authorized

The Python, local-state, deterministic briefing, repository connector, and
read-only Google Calendar foundations are complete. An explicitly approved,
bounded primary-calendar trial satisfied
[Milestone 4](docs/roadmap.md#milestone-4--first-safe-connectors). The accepted
Todoist connector, its combined Calendar trial, and one explicitly approved
complete-retrieval and normal-workday quality validation now satisfy the
Todoist portion of Milestone 5. Jira has completed its resource-restricted
authorization, project discovery, and one explicitly approved, exact-project
issue-retrieval trial integrated with the deterministic briefing. Milestone 5
now covers only Todoist and Jira. Work Gmail is the final MVP input connector.
Its successful combined trial listed and inspected 357 messages, found 144
eligible body candidates, selected 120, omitted 24 without body retrieval, and
produced 106 usable bodies. Gmail coverage was partial as required while the
other four inputs were complete. The trial created the private review and a
929-word combined briefing. Brad reviewed the private evidence and combined
briefing and explicitly judged the logic sound, completing Milestone 6.
Milestone 7 added precision-first deterministic commitment, acknowledgment,
deadline, preparation, and insufficient-evidence behavior. Its synthetic
evaluation passed, and a 2026-07-29 five-source live validation produced a
private review artifact and a 635-word briefing without external writes or
hosted inference. Brad reviewed that evidence and briefing and accepted the
detections and supporting logic. Milestone 8's provider-neutral boundary,
25-scenario mocked evaluation, and one authorized twenty-call synthetic
Terra–Luna comparison are complete. Every live call completed with zero
false-positive actionable claims or schema, provenance, provider, cache, or
correction failures. Three moderate-uncertainty suggestions were safely
rejected by deterministic policy. Brad reviewed the category-specific results
and selected OpenAI `gpt-5.6-luna` with low reasoning for
`contextual_action_classification` only, completing Milestone 8. The adapter
remains disabled by default, the one-time authorization is consumed, and
routine hosted inference and private-data egress remain unauthorized. No
model is selected for ranking or synthesis. Personal Gmail and Google Drive
remain deferred and unauthorized. Milestone 9 now has explainable
deterministic ranking, an application-owned briefing plan, conservative
duplicate and conflict handling, canonical composition, and a passing
26-scenario synthetic gate. Brad reviewed and accepted the corrected private
representative briefings. All scenarios passed with zero unsupported claims
or false-positive actionable recommendations; conflicts remain
source-attributed, duplicate suppression preserves authoritative records and
links, and ranking factors remain inspectable and source-backed. No provider,
connector, or external-write operation occurred.
Milestone 10 provides the secure loopback-only briefing and correction
experience with all required local dispositions, inspectable history,
recurrence controls, and transactional deletion. Brad reviewed the actual
interface at normal browser zoom, a successful five-source July 30 briefing,
the correction controls and evidence links, and the four-page PDF rendering,
then accepted the milestone. Milestone 11 operational hardening is complete
and accepted. Brad reviewed the corrected historical replay and
reconstruction, preserved `America/New_York` times and lineage, native
560-pixel and 1280-pixel browser presentations, three-page print artifact,
partial-source behavior, privacy and no-write boundaries, and all 14
synthetic acceptance metrics. He explicitly approved the package on
2026-07-30, accepting Milestone 11 and the on-demand Daily Briefing v1 MVP.
Commit `900a3b66d40bb3596e7ebee6ab801f5321050801` is the final correction
included in that accepted boundary. Scheduled generation and all other
deferred capabilities remain outside the accepted MVP. Milestone 12 is now a
accepted bounded-trial implementation for Scheduled Morning Generation.
Routine unattended operation after seven eligible dates remains unaccepted.

## Repository map

```text
.
├── .github/workflows/     Continuous integration
├── docs/
│   ├── architecture/
│   │   ├── connectors/     External source integration specifications
│   │   └── overview.md     Overall technical architecture
│   ├── decisions/          Architecture and significant product decisions
│   ├── foundations/        Assistant constitution and leadership model
│   ├── operations/
│   │   └── runbooks/       Step-by-step operational procedures
│   ├── product/
│   │   ├── features/       Detailed feature specifications
│   │   ├── future-ideas.md Deferred ideas outside current scope
│   │   ├── requirements.md Top-level product requirements
│   │   └── vision.md       Product purpose and desired outcomes
│   ├── README.md           Documentation index
│   └── roadmap.md          Milestones and sequencing
├── examples/               Safe synthetic demonstrations
├── src/chief_of_staff/     Python application package
├── templates/              Reusable documentation templates
├── tests/                  Synthetic foundation tests
├── AGENTS.md               Canonical instructions for repository agents
├── CHANGELOG.md            Notable repository changes
├── CONTRIBUTING.md         Contribution workflow
├── LICENSE                 MIT License
├── Makefile                Developer commands
├── pyproject.toml          Python package and quality-tool configuration
└── README.md               Project entry point
```

## Start here

1. Read [the product vision](docs/product/vision.md).
2. Review the [assistant constitution](docs/foundations/constitution.md) and
   [leadership model](docs/foundations/leadership-model.md).
3. Review the accepted product scope in
   [the requirements document](docs/product/requirements.md).
4. Use the accepted
   [Daily Briefing v1 specification](docs/product/features/daily-briefing-v1.md)
   as the first implementation contract.
5. Record consequential technical or product choices in
   [decision records](docs/decisions/README.md).
6. Use [the implementation roadmap](docs/roadmap.md) to sequence approved work
   and enforce milestone gates.

## Safe demonstration

After creating the supported development environment, generate a safe
connector briefing with:

```text
make demo
```

The demonstration reads two exact repository-owned documentation paths and
uses a mocked Calendar page. It performs no live source access, credential
lookup, hosted inference, persistence, or external writes. Use
`make demo-synthetic` for the fully synthetic Milestone 3 scenario.

The bounded live-trial procedure is documented separately in
[First Safe Connector Operations](docs/operations/first-safe-connectors.md).
The combined-MVP Work Gmail trust gate and the on-demand MVP acceptance gate
are complete. Any additional live use must remain within an explicit
current-task authorization and the unchanged connector boundary.

## Run the on-demand briefing

After the supported environment and approved connector credentials are
configured, inspect connector health and generate the current private
briefing with:

```text
make connector-status
make briefing
```

See the [on-demand briefing runbook](docs/operations/runbooks/on-demand-briefing.md)
for output locations, partial-coverage behavior, and safe failure handling.

## Open the local briefing

After a structured briefing has been persisted, start the local interface and
open it in the browser:

```text
make web-open
```

It serves only `http://127.0.0.1:8765` by default and runs in the foreground
until stopped with Control-C. See
[Local Web Interface Operations](docs/operations/local-web.md) for data
location, alternate-port behavior, and safe diagnostics.

## Documentation principles

- Document the problem before proposing a solution.
- Label assumptions and unresolved questions explicitly.
- Prefer small, reviewable documents with clear owners and status.
- Record decisions and their rationale, not just their outcome.
- Link to the authoritative document instead of duplicating governing content.
- Keep documentation synchronized with any future implementation.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for Python setup, developer commands,
quality checks, documentation conventions, and the current milestone boundary.

## License

This project is available under the [MIT License](LICENSE).
