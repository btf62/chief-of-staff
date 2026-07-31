"""Contract tests for the exact reversible user LaunchAgent."""

from __future__ import annotations

import plistlib
import stat
from dataclasses import dataclass, field
from pathlib import Path

from chief_of_staff.launchagent import (
    LAUNCH_AGENT_LABEL,
    LAUNCHD_WEEKDAYS,
    LaunchAgentCommandResult,
    LaunchAgentManager,
    launch_agent_payload,
)


@dataclass(slots=True)
class _FakeLaunchctl:
    calls: list[tuple[str, ...]] = field(default_factory=list)
    loaded: bool = False

    def __call__(self, arguments: tuple[str, ...]) -> LaunchAgentCommandResult:
        self.calls.append(arguments)
        operation = arguments[1]
        if operation == "bootstrap":
            self.loaded = True
        elif operation == "bootout":
            self.loaded = False
        elif operation == "print":
            return LaunchAgentCommandResult(0 if self.loaded else 113)
        return LaunchAgentCommandResult(0)


def test_payload_has_only_accepted_calendar_schedule_and_no_restart(
    tmp_path: Path,
) -> None:
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o700)
    payload = launch_agent_payload(
        repository_root=tmp_path,
        python_executable=python,
    )

    assert payload["Label"] == LAUNCH_AGENT_LABEL
    assert payload["ProgramArguments"] == [
        str(python),
        "-m",
        "chief_of_staff.scheduled_cli",
        "run",
    ]
    assert payload["KeepAlive"] is False
    assert payload["RunAtLoad"] is False
    assert payload["StandardOutPath"] == "/dev/null"
    assert payload["StandardErrorPath"] == "/dev/null"
    intervals = payload["StartCalendarInterval"]
    assert isinstance(intervals, list)
    assert tuple(item["Weekday"] for item in intervals) == LAUNCHD_WEEKDAYS
    assert all(item["Hour"] == 7 and item["Minute"] == 0 for item in intervals)
    assert 5 not in LAUNCHD_WEEKDAYS


def test_install_disable_enable_and_remove_are_exact_and_reversible(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    python = repository / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o700)
    plist_path = tmp_path / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
    runner = _FakeLaunchctl()
    manager = LaunchAgentManager(
        repository_root=repository,
        python_executable=python,
        plist_path=plist_path,
        command_runner=runner,
    )

    manager.install_and_load()

    assert manager.loaded()
    assert stat.S_IMODE(plist_path.stat().st_mode) == 0o600
    with plist_path.open("rb") as stream:
        installed = plistlib.load(stream)
    assert installed["Label"] == LAUNCH_AGENT_LABEL
    assert all(
        str(plist_path) in call or LAUNCH_AGENT_LABEL in " ".join(call)
        for call in runner.calls
    )

    manager.disable()
    assert not manager.loaded()
    assert plist_path.exists()

    manager.enable()
    assert manager.loaded()

    manager.remove()
    assert not plist_path.exists()
    assert not manager.loaded()
