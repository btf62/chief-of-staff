# Connector Specifications

This directory is the authoritative location for external source integration
specifications. Create one specification per external source.

Each specification should eventually define source authority, supported data,
access boundaries, authentication references, synchronization behavior,
failure handling, privacy constraints, and observability. Do not place
credentials or private source content in a connector specification.

## Connector index

No connectors have been specified.

## Planned specifications

| Source | Planned specification |
| --- | --- |
| Google Calendar | `google-calendar.md` |
| Gmail | `gmail.md` |
| Todoist | `todoist.md` |
| Jira | `jira.md` |
| Asana | `asana.md` |
| Approved Google Drive content | `google-drive.md` |
| Approved repository context | `repository-context.md` |

Each future specification should implement the common read-only connector
contract in the [Architecture Overview](../overview.md#4-connector-model)
without selecting priorities or mutating its source.

## Related documents

- [Technical architecture](../overview.md)
- [Product requirements](../../product/requirements.md)
