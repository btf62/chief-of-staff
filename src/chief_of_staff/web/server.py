"""Supported Waitress launch command for the loopback-only web interface."""

from __future__ import annotations

import argparse
import sys
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


def main(arguments: list[str] | None = None) -> int:
    """Validate local state and serve Chief of Staff on IPv4 loopback."""

    parser = argparse.ArgumentParser(
        description="Open the local-only Chief of Staff briefing interface.",
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    parsed = parser.parse_args(arguments)

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
    except KeyboardInterrupt:
        print("Chief of Staff stopped.")
    finally:
        if server is not None:
            server.close()
        close_application(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
