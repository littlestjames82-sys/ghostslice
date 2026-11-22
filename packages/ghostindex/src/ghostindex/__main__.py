"""Module entry point: ``python3 -m ghostindex ...`` runs the CLI.

All commands, flags, and exit codes are documented in
``ghostindex --help`` and in each subcommand's ``--help``.
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
