"""Supported local operational commands that never retrieve source data."""

from __future__ import annotations

import argparse

from chief_of_staff.auth import MacOSKeychain
from chief_of_staff.connector_health import (
    format_health_report,
    inspect_approved_connectors,
)
from chief_of_staff.gmail_live_cli import DATABASE_PATH, LOCAL_ROOT
from chief_of_staff.persistence import Database, StateStore


def main(arguments: list[str] | None = None) -> int:
    """Inspect local connector readiness without contacting providers."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("connector-status",),
    )
    parsed = parser.parse_args(arguments)
    if parsed.command != "connector-status":
        raise RuntimeError("unsupported operations command")

    LOCAL_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    LOCAL_ROOT.chmod(0o700)
    with Database.open(DATABASE_PATH) as database:
        reports = inspect_approved_connectors(
            StateStore(database),
            MacOSKeychain(),
        )
    for index, report in enumerate(reports):
        if index:
            print()
        print("\n".join(format_health_report(report)))
    return 0 if all(report.can_retrieve for report in reports) else 2


if __name__ == "__main__":
    raise SystemExit(main())
