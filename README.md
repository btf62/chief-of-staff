# Chief of Staff

Chief of Staff is a documentation-first project for a cross-domain AI
chief-of-staff system serving one primary user. The source systems will remain
authoritative; this project will provide a unified interpretation layer for
identifying priorities, commitments, and useful signals.

## Status

**Phase:** Milestones 1–5 complete; Milestone 6 Work Gmail in progress

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
929-word combined briefing. Milestone 6's live trial is complete; Brad's human
trust review remains before acceptance. The repeatable validation
authorization ended at success, so another live retrieval requires new
explicit approval. Personal Gmail and Google Drive remain deferred and
unauthorized.

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
The combined-MVP Work Gmail trial is complete and stopped. It must not be
repeated or broadened without new explicit approval.

## Run the on-demand briefing

After the supported environment and approved connector credentials are
configured, generate the current private briefing with:

```text
make briefing
```

See the [on-demand briefing runbook](docs/operations/runbooks/on-demand-briefing.md)
for output locations, partial-coverage behavior, and safe failure handling.

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
