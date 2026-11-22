"""Command line for the GhostConsole app.

    ghostconsole-app [--host 127.0.0.1] [--port 8760]
                     [--workflow-home DIR] [--engine-home DIR]

Binds 127.0.0.1 unless --host says otherwise, and prints the bind
address and URL on start: this app has no authentication, so where
it listens is a fact the user should never have to guess.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .runner import Runner
from .server import make_server

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8760


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ghostconsole-app",
        description=(
            "Local web front end for the Ghost ecosystem. Register "
            "projects, run ghostworkflow on them, and read the "
            "evidence it writes. Local only: there is no "
            "authentication, so the server binds 127.0.0.1 unless "
            "--host explicitly says otherwise."
        ),
    )
    parser.add_argument("--version", action="version",
                        version=f"ghostconsole-app {__version__}")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help="address to bind (default: %(default)s; "
                             "anything else exposes an unauthenticated "
                             "server - the UI states the bind either way)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="port to bind (default: %(default)s). If "
                             "the port is taken the app fails with a "
                             "message; it never picks another silently.")
    parser.add_argument("--workflow-home", default=None,
                        help="where the ghostworkflow checkout lives "
                             "(or a directory containing it); overrides "
                             "GHOSTCONSOLE_APP_WORKFLOW_HOME, PATH, and "
                             "sibling-checkout discovery")
    parser.add_argument("--engine-home", default=None,
                        help="passed through to ghostworkflow run as "
                             "--engine-home (where the four engine "
                             "checkouts live)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runner = Runner(workflow_home=args.workflow_home,
                    engine_home=args.engine_home)
    try:
        server = make_server(args.host, args.port, runner)
    except OSError as exc:
        print(
            f"ghostconsole-app: cannot listen on {args.host}:{args.port} "
            f"({exc}). The port may already be in use; choose another "
            "with --port.",
            file=sys.stderr,
        )
        return 2
    host, port = server.server_address[:2]
    print(f"GhostConsole app listening on http://{host}:{port}/", flush=True)
    print(f"Bind address: {host}:{port} (local only unless you changed "
          "--host). No authentication - do not expose this server "
          "beyond your own machine.", flush=True)
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()
    return 0
