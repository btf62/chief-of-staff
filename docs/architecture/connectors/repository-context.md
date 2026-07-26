# Approved Repository Context Connector

- **Status:** Accepted
- **Version:** 1
- **Owner:** Brad
- **Last updated:** 2026-07-25

This specification defines the local repository-context connector authorized
for Milestone 4. It lets the deterministic briefing consult a small, explicit
set of repository-owned Markdown documents without scanning broadly, using a
remote credential, persisting copied content, or modifying any file.

## Source authority

The selected repository documents remain authoritative for their respective
project subjects. The connector returns bounded context and provenance; it
does not reinterpret document status, make a repository document
authoritative for another domain, or replace the source file.

## Approved resource boundary

Each connector instance requires:

- One existing local repository root.
- At least one and no more than 32 exact file paths explicitly supplied by the
  caller.
- Markdown files no larger than 256 KiB each.

The connector:

- Does not recursively discover files or accept a directory as an approved
  source.
- Resolves every path and rejects files outside the configured root, including
  symlinks that escape it.
- Rejects hidden paths, duplicate paths, non-Markdown files, missing files,
  and files above the size limit.
- Sorts approved relative paths for deterministic retrieval.
- Reports only repository-relative paths in coverage and provenance so local
  machine paths do not enter briefing output.

Approval is per exact path. Approval of one file, directory name, or repository
does not imply approval of adjacent or future files.

## Authentication and authorization

Direct access to an approved local path requires no remote credential or OAuth
authorization under
[ADR-0005](../../decisions/0005-adopt-oauth-and-macos-keychain.md).
Filesystem access is limited by the local user account running Chief of Staff.
Future remote repository access requires a separate connector specification
and, when material, a separate decision.

## Retrieved and normalized data

For each approved file, the connector returns:

- The first level-one heading, or a filename-derived fallback title.
- The first ordinary prose paragraph, truncated to 280 characters, when
  present.
- The repository-relative source path as the stable source identifier.
- A `repository://` display reference using that relative path.
- File modification time as source freshness.
- Retrieval time and the exact approved relative-path set as coverage.

The connector does not return full document contents, code blocks, tables,
document metadata bullets, Git history, unapproved files, or directory
listings.

## Read-only behavior

The connector implements only the common `retrieve` operation. It has no
create, update, delete, write, commit, branch, push, or remote-network
capability. Contract and integration tests verify that approved files are
unchanged and that unapproved files are not retrieved.

## Coverage and failure behavior

- All approved files read safely: `complete`.
- Some approved files fail after connector construction: `partial`.
- No approved file can be read: `unavailable`.
- An empty approved set is invalid configuration, not empty source data.

Warnings identify safe repository-relative paths only. A failed file never
causes the connector to widen its search or substitute another file.

## Persistence, retention, and deletion

The connector has no source-content cache. Retrieved text is transient pipeline
input. Normalized provenance and any later application-owned conclusion state
remain governed by
[ADR-0004](../../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md).
No new retention or backup exception is authorized.

## Observability and privacy

Operational metadata may include connector status, item count, retrieval time,
freshness, and approved repository-relative paths. Logs and errors must not
include absolute paths, full file contents, or unapproved filenames.

Only public-safe, repository-owned content may be used in committed tests and
demonstrations. Exact runtime approval remains necessary even when a file is
already tracked by Git.

## Validation

The implementation is accepted when tests demonstrate:

- Exact-path-only retrieval.
- Repository-root containment.
- Rejection of broad, hidden, non-Markdown, duplicate, missing, and oversized
  paths.
- Minimal normalized context and stable relative provenance.
- Complete, partial, and unavailable coverage behavior.
- No file mutation or external-write capability.
- On-demand briefing integration with repository-owned content.

These conditions are implemented and exercised with synthetic temporary files
and the repository's public documentation.
