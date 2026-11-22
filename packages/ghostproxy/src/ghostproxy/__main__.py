"""Run GhostProxy as ``python3 -m ghostproxy <command>``.

Commands: serve, doctor, report, transform. See ``--help`` (global
or per command) and README.md for the setup and undo paths.
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
