# Chief of Staff

Chief of Staff is a documentation-first project for a cross-domain AI
chief-of-staff system serving one primary user. The source systems will remain
authoritative; this project will provide a unified interpretation layer for
identifying priorities, commitments, and useful signals.

## Status

**Phase:** Milestone 1 complete; Milestone 2 ready

The Python project foundation is complete, but there is no product
functionality yet. The next implementation milestone is
[Milestone 2 — Core Domain and Persistence](docs/roadmap.md#milestone-2--core-domain-and-persistence).

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
