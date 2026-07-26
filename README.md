# Chief of Staff

Chief of Staff is a documentation-first project for a cross-domain AI
chief-of-staff system serving one primary user. The source systems will remain
authoritative; this project will provide a unified interpretation layer for
identifying priorities, commitments, and useful signals.

## Status

**Phase:** Milestones 1–3 complete; Milestone 4 ready

The Python, local-state, and deterministic briefing foundations are complete.
The next implementation milestone is
[Milestone 4 — First Safe Connectors](docs/roadmap.md#milestone-4--first-safe-connectors).
No live source authorization has occurred.

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

After creating the supported development environment, generate the synthetic
deterministic briefing with:

```text
make demo
```

The demonstration uses repository-owned synthetic records only. It performs no
live source access, hosted inference, persistence, or external writes.

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
