# Chief of Staff

Chief of Staff is a documentation-first project for a cross-domain AI
chief-of-staff system serving one primary user. The source systems will remain
authoritative; this project will provide a unified interpretation layer for
identifying priorities, commitments, and useful signals.

## Status

**Phase:** Repository initialization and discovery

There is no functional application, runtime, or selected technology stack yet.
The first planned product milestone is a concise daily briefing, but its
specification has not yet been written. Implementation should begin only after
the foundational documents, product requirements, and architecture decisions
are documented and accepted.

## Repository map

```text
.
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
├── templates/              Reusable documentation templates
├── AGENTS.md               Canonical instructions for repository agents
├── CHANGELOG.md            Notable repository changes
├── CONTRIBUTING.md         Contribution workflow
├── LICENSE                 MIT License
└── README.md               Project entry point
```

## Start here

1. Read [the product vision](docs/product/vision.md).
2. Review the [assistant constitution](docs/foundations/constitution.md) and
   [leadership model](docs/foundations/leadership-model.md).
3. Capture product scope in
   [the requirements document](docs/product/requirements.md).
4. Define implementable behavior in
   [feature specifications](docs/product/features/README.md).
5. Record consequential technical or product choices in
   [decision records](docs/decisions/README.md).
6. Use [the roadmap](docs/roadmap.md) to sequence approved work.

## Documentation principles

- Document the problem before proposing a solution.
- Label assumptions and unresolved questions explicitly.
- Prefer small, reviewable documents with clear owners and status.
- Record decisions and their rationale, not just their outcome.
- Link to the authoritative document instead of duplicating governing content.
- Keep documentation synchronized with any future implementation.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the current documentation-focused
workflow.

## License

This project is available under the [MIT License](LICENSE).
