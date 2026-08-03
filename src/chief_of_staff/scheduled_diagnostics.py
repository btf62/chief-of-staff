"""Bounded, non-content diagnostics for scheduled morning operation."""

from __future__ import annotations

import fcntl
import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from chief_of_staff.connector_health import APPROVED_CONNECTORS, ConnectorHealth

if TYPE_CHECKING:
    from chief_of_staff.scheduling import ScheduledExecutionReport

DIAGNOSTIC_MAXIMUM_FILE_BYTES: Final = 64 * 1024
DIAGNOSTIC_MAXIMUM_FILES: Final = 2
DIAGNOSTIC_MAXIMUM_DISPLAYED_EVENTS: Final = 100

_IDENTIFIER_PATTERN: Final = re.compile(r"[a-z0-9_]{1,80}")
_VERSION_PATTERN: Final = re.compile(r"[A-Za-z0-9.+-]{1,100}")
_SAFE_SOURCE_ALIASES: Final = frozenset(
    connector.display_name for connector in APPROVED_CONNECTORS
)
_SAFE_HEALTH_VALUES: Final = frozenset(item.value for item in ConnectorHealth)
_SAFE_NOTIFICATION_RESULTS: Final = frozenset({"delivered", "delivery_failed"})


def append_scheduled_run_diagnostic(
    path: Path,
    *,
    report: ScheduledExecutionReport,
    recorded_at: datetime,
    application_version: str,
) -> None:
    """Append one private-safe scheduler outcome without briefing content."""

    _require_aware(recorded_at)
    entry: dict[str, object] = {
        "application_version": _safe_version(application_version),
        "eligibility_decision": _safe_identifier(report.eligibility_decision),
        "event": "scheduled_invocation",
        "occurrence_date": report.occurrence_date.isoformat(),
        "outcome": _safe_identifier(report.outcome.value),
        "recorded_at": recorded_at.astimezone(UTC).isoformat(),
        "trial_ordinal": report.trial_ordinal,
    }
    if report.diagnostic_category is not None:
        entry["diagnostic_category"] = _safe_identifier(report.diagnostic_category)
    if report.notification_result is not None:
        if report.notification_result not in _SAFE_NOTIFICATION_RESULTS:
            raise ValueError("scheduled notification result is not safe to log")
        entry["notification_result"] = report.notification_result
    if report.source_health:
        entry["source_health"] = _safe_source_health(report.source_health)
    _append_entry(path, entry)


def append_version_adoption_diagnostic(
    path: Path,
    *,
    previous_version: str,
    application_version: str,
    recorded_at: datetime,
) -> None:
    """Record one reviewed in-trial version adoption without trial content."""

    _require_aware(recorded_at)
    _append_entry(
        path,
        {
            "application_version": _safe_version(application_version),
            "event": "reviewed_application_version_adopted",
            "previous_application_version": _safe_version(previous_version),
            "recorded_at": recorded_at.astimezone(UTC).isoformat(),
        },
    )


def scheduled_diagnostic_snapshot(path: Path) -> Mapping[str, object]:
    """Return the newest bounded safe events for operator inspection."""

    events: list[Mapping[str, object]] = []
    for candidate in (path.with_suffix(path.suffix + ".1"), path):
        events.extend(_read_file(candidate))
    return {
        "events": events[-DIAGNOSTIC_MAXIMUM_DISPLAYED_EVENTS:],
        "maximum_bytes_per_file": DIAGNOSTIC_MAXIMUM_FILE_BYTES,
        "maximum_files": DIAGNOSTIC_MAXIMUM_FILES,
        "private_content_included": False,
    }


def _append_entry(path: Path, entry: Mapping[str, object]) -> None:
    encoded = (json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n").encode(
        "utf-8"
    )
    if len(encoded) > 4096:
        raise ValueError("scheduled diagnostic event exceeds its safe bound")

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_descriptor = _open_file(
        lock_path,
        os.O_RDWR | os.O_CREAT | os.O_CLOEXEC,
    )
    try:
        os.fchmod(lock_descriptor, 0o600)
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        _rotate_if_needed(path, len(encoded))
        descriptor = _open_file(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC,
        )
        try:
            os.fchmod(descriptor, 0o600)
            remaining = memoryview(encoded)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("scheduled diagnostic write did not progress")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)


def _rotate_if_needed(path: Path, next_event_bytes: int) -> None:
    try:
        current_bytes = path.stat(follow_symlinks=False).st_size
    except FileNotFoundError:
        return
    if current_bytes > DIAGNOSTIC_MAXIMUM_FILE_BYTES:
        raise OSError("scheduled diagnostic file exceeds its accepted bound")
    if path.is_symlink():
        raise OSError("scheduled diagnostic path cannot be a symbolic link")
    if current_bytes + next_event_bytes <= DIAGNOSTIC_MAXIMUM_FILE_BYTES:
        return
    rotated = path.with_suffix(path.suffix + ".1")
    if rotated.is_symlink():
        raise OSError("rotated diagnostic path cannot be a symbolic link")
    path.replace(rotated)
    rotated.chmod(0o600)


def _read_file(path: Path) -> tuple[Mapping[str, object], ...]:
    try:
        descriptor = _open_file(path, os.O_RDONLY | os.O_CLOEXEC)
    except FileNotFoundError:
        return ()
    try:
        chunks: list[bytes] = []
        remaining = DIAGNOSTIC_MAXIMUM_FILE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(raw) > DIAGNOSTIC_MAXIMUM_FILE_BYTES:
        return ()
    result: list[Mapping[str, object]] = []
    for line in raw.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError, UnicodeDecodeError:
            continue
        if isinstance(value, dict) and all(isinstance(key, str) for key in value):
            result.append(value)
    return tuple(result)


def _open_file(path: Path, flags: int) -> int:
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags | no_follow, 0o600)


def _safe_source_health(
    source_health: tuple[tuple[str, str], ...],
) -> Mapping[str, str]:
    result: dict[str, str] = {}
    for alias, health in source_health:
        if alias not in _SAFE_SOURCE_ALIASES or health not in _SAFE_HEALTH_VALUES:
            raise ValueError("scheduled source health is not safe to log")
        result[alias] = health
    return dict(sorted(result.items()))


def _safe_identifier(value: str) -> str:
    if _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError("scheduled diagnostic category is not safe to log")
    return value


def _safe_version(value: str) -> str:
    if _VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("scheduled application version is not safe to log")
    return value


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("scheduled diagnostic time must be timezone-aware")
