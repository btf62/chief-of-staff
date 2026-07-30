"""SQLite connection, transaction, and migration management."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Final, Self

_MIGRATION_NAME: Final = re.compile(r"(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql")


class MigrationError(RuntimeError):
    """Raised when migration history is invalid or cannot be applied safely."""


@dataclass(frozen=True, slots=True)
class Migration:
    """One ordered, checksummed schema migration."""

    version: int
    name: str
    sql: str
    checksum: str

    @classmethod
    def create(cls, version: int, name: str, sql: str) -> Self:
        """Create a migration and derive its stable checksum."""

        checksum = hashlib.sha256(sql.encode()).hexdigest()
        return cls(version=version, name=name, sql=sql, checksum=checksum)


class Database:
    """One application-owned SQLite connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    @classmethod
    def open(cls, path: Path) -> Self:
        """Open a configured path, enforce integrity, and migrate it."""

        path.parent.mkdir(parents=True, exist_ok=True)
        # Waitress owns its single request worker even though the application
        # opens and closes the connection on the foreground server thread.
        # Callers must continue to serialize access; the supported web server
        # enforces one worker thread.
        connection = sqlite3.connect(
            path,
            isolation_level=None,
            check_same_thread=False,
        )
        path.chmod(0o600)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            connection.close()
            raise RuntimeError("SQLite foreign-key enforcement is unavailable")

        database = cls(connection)
        try:
            apply_migrations(connection)
        except BaseException:
            connection.close()
            raise
        return database

    def close(self) -> None:
        """Close the underlying SQLite connection."""

        self.connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a single explicit transaction and roll back on error."""

        if self.connection.in_transaction:
            raise RuntimeError("nested transactions are not supported")

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()


def load_migrations() -> tuple[Migration, ...]:
    """Load ordered SQL migrations packaged with the application."""

    migration_root = resources.files("chief_of_staff.persistence.migrations")
    migrations: list[Migration] = []
    for entry in migration_root.iterdir():
        match = _MIGRATION_NAME.fullmatch(entry.name)
        if match is None:
            continue
        sql = entry.read_text(encoding="utf-8")
        migrations.append(
            Migration.create(
                version=int(match.group("version")),
                name=match.group("name"),
                sql=sql,
            )
        )

    migrations.sort(key=lambda migration: migration.version)
    _validate_migration_sequence(migrations)
    return tuple(migrations)


def apply_migrations(
    connection: sqlite3.Connection,
    migrations: Sequence[Migration] | None = None,
) -> None:
    """Apply pending migrations and verify checksums for applied versions."""

    selected = tuple(load_migrations() if migrations is None else migrations)
    _validate_migration_sequence(selected)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )

    applied_rows = connection.execute(
        "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    selected_by_version = {migration.version: migration for migration in selected}
    for row in applied_rows:
        migration = selected_by_version.get(int(row[0]))
        if migration is None:
            raise MigrationError("database contains an unknown migration version")
        if row[1] != migration.name or row[2] != migration.checksum:
            raise MigrationError("an applied migration no longer matches its checksum")

    applied_versions = {int(row[0]) for row in applied_rows}
    for migration in selected:
        if migration.version in applied_versions:
            continue
        _apply_one_migration(connection, migration)


def _validate_migration_sequence(migrations: Sequence[Migration]) -> None:
    versions = [migration.version for migration in migrations]
    expected = list(range(1, len(versions) + 1))
    if versions != expected:
        raise MigrationError(
            "migrations must be non-empty, ordered, unique, and contiguous"
        )


def _apply_one_migration(
    connection: sqlite3.Connection,
    migration: Migration,
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        for statement in _iter_sql_statements(migration.sql):
            connection.execute(statement)
        connection.execute(
            """
            INSERT INTO schema_migrations(version, name, checksum, applied_at)
            VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (migration.version, migration.name, migration.checksum),
        )
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def _iter_sql_statements(sql: str) -> Iterator[str]:
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                yield statement
            buffer = ""
    if buffer.strip():
        raise MigrationError("migration contains an incomplete SQL statement")
