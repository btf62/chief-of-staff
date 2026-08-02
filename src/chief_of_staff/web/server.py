"""Supported Waitress launch command for the loopback-only web interface."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Final

from waitress.server import create_server  # type: ignore[import-untyped]

from chief_of_staff.web.app import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    close_application,
    create_app,
)

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_PATH: Final = REPOSITORY_ROOT / ".local" / "state.sqlite3"
PID_FILENAME: Final = "web-server.pid"
EXPECTED_PROCESS_MARKERS: Final = (
    "-m chief_of_staff.web.server",
    "chief-of-staff-web",
)
STOP_WAIT_SECONDS: Final = 5.0


def main(arguments: list[str] | None = None) -> int:
    """Validate local state and serve Chief of Staff on IPv4 loopback."""

    parser = argparse.ArgumentParser(
        description="Open the local-only Chief of Staff briefing interface.",
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    parser.add_argument("--stop", action="store_true")
    parsed = parser.parse_args(arguments)
    pid_path = parsed.database.parent / PID_FILENAME

    if parsed.stop:
        return _stop_running_server(pid_path)

    try:
        app = create_app(
            parsed.database,
            host=DEFAULT_HOST,
            port=parsed.port,
        )
    except OSError, RuntimeError, ValueError:
        print(
            "Chief of Staff could not open the configured local database.",
            file=sys.stderr,
        )
        return 2

    server = None
    pid_claimed = False
    previous_sigterm = None
    url = f"http://{DEFAULT_HOST}:{parsed.port}"
    try:
        server = create_server(
            app,
            host=DEFAULT_HOST,
            port=parsed.port,
            threads=1,
            clear_untrusted_proxy_headers=True,
            expose_tracebacks=False,
            ident=None,
        )
        _claim_pid_file(pid_path)
        pid_claimed = True
        previous_sigterm = signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
        print(f"Chief of Staff is ready at {url}")
        print("Press Control-C to stop the local application.")
        if parsed.open_browser:
            webbrowser.open(url, new=2)
        server.run()
    except OSError:
        print(
            "Chief of Staff could not start because the local port is unavailable.",
            file=sys.stderr,
        )
        return 3
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        print("Chief of Staff stopped.")
    finally:
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
        if server is not None:
            server.close()
        close_application(app)
        if pid_claimed:
            _release_pid_file(pid_path, os.getpid())
    return 0


def _raise_keyboard_interrupt(_signum: int, _frame: object) -> None:
    """Route a validated stop request through the normal shutdown path."""

    raise KeyboardInterrupt


def _claim_pid_file(pid_path: Path) -> None:
    """Claim one mode-0600 PID file without displacing a live process."""

    pid_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    pid_path.parent.chmod(0o700)
    existing_pid = _read_pid_file(pid_path)
    if existing_pid is not None:
        process = _inspect_process(existing_pid)
        if process is not None:
            raise RuntimeError(
                "Chief of Staff could not start because its server state is in use."
            )
        pid_path.unlink(missing_ok=True)
    descriptor = os.open(
        pid_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(f"{os.getpid()}\n")
    pid_path.chmod(0o600)


def _release_pid_file(pid_path: Path, expected_pid: int) -> None:
    """Remove only the current server's own PID file."""

    if _read_pid_file(pid_path) == expected_pid:
        pid_path.unlink(missing_ok=True)


def _read_pid_file(pid_path: Path) -> int | None:
    """Read a strict positive PID without accepting additional content."""

    try:
        raw = pid_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    value = raw.strip()
    if not value.isascii() or not value.isdecimal():
        raise RuntimeError("Chief of Staff server state is invalid; stop refused.")
    pid = int(value)
    if pid <= 1:
        raise RuntimeError("Chief of Staff server state is invalid; stop refused.")
    return pid


def _inspect_process(pid: int) -> tuple[int, str] | None:
    """Return non-secret owner and command metadata for one exact PID."""

    completed = subprocess.run(  # noqa: S603 - fixed local process inspector
        ("/bin/ps", "-p", str(pid), "-o", "uid=,command="),
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    owner, separator, command = completed.stdout.strip().partition(" ")
    if not separator or not owner.isdecimal() or not command.strip():
        return None
    return int(owner), command.strip()


def _is_expected_server(process: tuple[int, str]) -> bool:
    """Accept only this user's supported Chief of Staff web command."""

    owner, command = process
    return owner == os.getuid() and any(
        marker in command for marker in EXPECTED_PROCESS_MARKERS
    )


def _send_stop_signal(pid: int) -> None:
    """Send the one supported graceful-stop signal to a validated PID."""

    os.kill(pid, signal.SIGTERM)


def _stop_running_server(pid_path: Path) -> int:
    """Stop only the exact PID claimed by the local web interface."""

    try:
        pid = _read_pid_file(pid_path)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 4
    if pid is None:
        print("Chief of Staff web interface is not running.")
        return 0
    process = _inspect_process(pid)
    if process is None:
        pid_path.unlink(missing_ok=True)
        print("Chief of Staff web interface is not running; stale state removed.")
        return 0
    if not _is_expected_server(process):
        print(
            "Chief of Staff could not safely identify its web process; stop refused.",
            file=sys.stderr,
        )
        return 4
    try:
        _send_stop_signal(pid)
    except ProcessLookupError:
        pid_path.unlink(missing_ok=True)
        print("Chief of Staff web interface is not running; stale state removed.")
        return 0
    deadline = time.monotonic() + STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        if _inspect_process(pid) is None:
            pid_path.unlink(missing_ok=True)
            print("Chief of Staff web interface stopped.")
            return 0
        time.sleep(0.05)
    print(
        "Chief of Staff web interface did not stop within the safe wait period.",
        file=sys.stderr,
    )
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
