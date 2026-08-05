"""Reversible user LaunchAgent management for the bounded morning trial."""

from __future__ import annotations

import os
import plistlib
import pwd
import subprocess
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from chief_of_staff.scheduling import TRIGGER_HOUR, TRIGGER_MINUTE

LAUNCH_AGENT_LABEL: Final = "org.northridge.chief-of-staff.scheduled-morning"
LAUNCH_AGENT_FILENAME: Final = f"{LAUNCH_AGENT_LABEL}.plist"
LAUNCHD_WEEKDAYS: Final = (0, 1, 2, 3, 4, 6)
CAFFEINATE_PATH: Final = Path("/usr/bin/caffeinate")


def launch_agent_payload(
    *,
    repository_root: Path,
    python_executable: Path,
) -> dict[str, object]:
    """Return the exact non-secret, non-persistent LaunchAgent definition."""

    root = repository_root.resolve(strict=True)
    requested_python = python_executable.resolve(strict=True)
    python = root / ".venv" / "bin" / "python"
    expected_python = python.resolve(strict=True)
    if (
        requested_python != expected_python
        or not python.is_file()
        or not os.access(python, os.X_OK)
    ):
        raise RuntimeError("the configured Python executable is not usable")
    return {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            str(CAFFEINATE_PATH),
            "-i",
            str(python),
            "-m",
            "chief_of_staff.scheduled_cli",
            "run",
        ],
        "WorkingDirectory": str(root),
        "StartCalendarInterval": [
            {
                "Weekday": weekday,
                "Hour": TRIGGER_HOUR,
                "Minute": TRIGGER_MINUTE,
            }
            for weekday in LAUNCHD_WEEKDAYS
        ],
        "ProcessType": "Background",
        "KeepAlive": False,
        "RunAtLoad": False,
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
        "Umask": 0o077,
    }


def default_plist_path() -> Path:
    """Return the exact current-user service path."""

    return Path.home() / "Library" / "LaunchAgents" / LAUNCH_AGENT_FILENAME


def current_launch_domain() -> str:
    """Return the launchd GUI domain for the current user."""

    return f"gui/{os.getuid()}"


@dataclass(frozen=True, slots=True)
class LaunchAgentCommandResult:
    """Safe command outcome without process output."""

    returncode: int


LaunchAgentCommandRunner = Callable[[tuple[str, ...]], LaunchAgentCommandResult]


def _run_launchctl(arguments: tuple[str, ...]) -> LaunchAgentCommandResult:
    completed = subprocess.run(  # noqa: S603 - fixed /bin/launchctl boundary
        arguments,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return LaunchAgentCommandResult(completed.returncode)


@dataclass(frozen=True, slots=True)
class LaunchAgentManager:
    """Install, disable, re-enable, inspect, or remove one exact service."""

    repository_root: Path
    python_executable: Path
    plist_path: Path = field(default_factory=default_plist_path)
    command_runner: LaunchAgentCommandRunner = field(
        default=_run_launchctl,
        repr=False,
        compare=False,
    )

    def install_and_load(self) -> None:
        """Write the exact plist with mode 0600 and load it for this user."""

        self._write_definition()
        try:
            self._require_success(
                (
                    "/bin/launchctl",
                    "enable",
                    f"{current_launch_domain()}/{LAUNCH_AGENT_LABEL}",
                ),
                "LaunchAgent could not be enabled",
            )
            self._require_success(
                (
                    "/bin/launchctl",
                    "bootstrap",
                    current_launch_domain(),
                    str(self.plist_path),
                ),
                "LaunchAgent could not be loaded",
            )
        except BaseException:
            self.plist_path.unlink(missing_ok=True)
            raise

    def refresh_definition(self, *, load: bool) -> None:
        """Replace the exact definition while preserving trial enablement."""

        previous = self.plist_path.read_bytes() if self.plist_path.is_file() else None
        was_loaded = self.loaded()
        self.disable()
        try:
            if load:
                self.install_and_load()
            else:
                self._write_definition()
        except BaseException:
            self.plist_path.unlink(missing_ok=True)
            if previous is not None:
                self.plist_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                temporary = self.plist_path.with_suffix(".plist.rollback")
                temporary.write_bytes(previous)
                temporary.chmod(0o600)
                temporary.replace(self.plist_path)
                self.plist_path.chmod(0o600)
                if was_loaded:
                    with suppress(RuntimeError):
                        self.enable()
            raise

    def _write_definition(self) -> None:
        """Atomically write the current exact LaunchAgent definition."""

        payload = launch_agent_payload(
            repository_root=self.repository_root,
            python_executable=self.python_executable,
        )
        self.plist_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.plist_path.with_suffix(".plist.tmp")
        with temporary.open("wb") as stream:
            plistlib.dump(payload, stream, sort_keys=True)
        temporary.chmod(0o600)
        temporary.replace(self.plist_path)
        self.plist_path.chmod(0o600)

    def disable(self) -> None:
        """Unload and disable the service without deleting trial history."""

        self.command_runner(
            (
                "/bin/launchctl",
                "bootout",
                current_launch_domain(),
                str(self.plist_path),
            )
        )
        self._require_success(
            (
                "/bin/launchctl",
                "disable",
                f"{current_launch_domain()}/{LAUNCH_AGENT_LABEL}",
            ),
            "LaunchAgent could not be disabled",
        )

    def enable(self) -> None:
        """Enable and load the exact existing service."""

        if not self.plist_path.is_file():
            raise RuntimeError("the Scheduled Morning LaunchAgent is not installed")
        self._require_success(
            (
                "/bin/launchctl",
                "enable",
                f"{current_launch_domain()}/{LAUNCH_AGENT_LABEL}",
            ),
            "LaunchAgent could not be enabled",
        )
        self._require_success(
            (
                "/bin/launchctl",
                "bootstrap",
                current_launch_domain(),
                str(self.plist_path),
            ),
            "LaunchAgent could not be loaded",
        )

    def remove(self) -> None:
        """Unload and delete only the exact service definition."""

        self.command_runner(
            (
                "/bin/launchctl",
                "bootout",
                current_launch_domain(),
                str(self.plist_path),
            )
        )
        self.command_runner(
            (
                "/bin/launchctl",
                "enable",
                f"{current_launch_domain()}/{LAUNCH_AGENT_LABEL}",
            )
        )
        if self.plist_path.exists():
            self.plist_path.unlink()

    def loaded(self) -> bool:
        """Return whether launchd currently reports the exact service."""

        result = self.command_runner(
            (
                "/bin/launchctl",
                "print",
                f"{current_launch_domain()}/{LAUNCH_AGENT_LABEL}",
            )
        )
        return result.returncode == 0

    def _require_success(
        self,
        arguments: tuple[str, ...],
        message: str,
    ) -> None:
        if self.command_runner(arguments).returncode != 0:
            raise RuntimeError(message)


def host_readiness(
    *,
    repository_root: Path,
    python_executable: Path,
) -> tuple[tuple[str, bool], ...]:
    """Inspect the approved primary-Mac prerequisites without installing."""

    console_user = None
    with suppress(KeyError, OSError):
        console_user = pwd.getpwuid(os.stat("/dev/console").st_uid).pw_name
    current_user = pwd.getpwuid(os.getuid()).pw_name
    system_timezone = str(Path("/etc/localtime").resolve()).endswith(
        "/America/New_York"
    )
    return (
        ("macOS host", sys.platform == "darwin"),
        (
            "bounded sleep-prevention tool",
            CAFFEINATE_PATH.is_file() and os.access(CAFFEINATE_PATH, os.X_OK),
        ),
        ("system timezone", system_timezone),
        ("approved repository path", repository_root.is_dir()),
        (
            "supported virtual environment",
            python_executable.is_file()
            and os.access(python_executable, os.X_OK)
            and python_executable.resolve()
            == (repository_root / ".venv" / "bin" / "python").resolve(),
        ),
        (
            "logged-in GUI user",
            console_user is not None and console_user == current_user,
        ),
    )
