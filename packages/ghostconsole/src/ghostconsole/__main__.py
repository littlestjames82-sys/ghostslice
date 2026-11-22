"""Module entry point: ``python3 -m ghostconsole ...``.

Equivalent to the ``ghostconsole`` command; see :mod:`ghostconsole.cli`
for the commands, options, and exit codes.
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
