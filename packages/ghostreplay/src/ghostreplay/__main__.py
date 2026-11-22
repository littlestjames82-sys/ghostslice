"""Run GhostReplay as ``python3 -m ghostreplay ...``.

Equivalent to the ``ghostreplay`` console script; all arguments
are handled by :mod:`ghostreplay.cli`. Try::

    PYTHONPATH=src python3 -m ghostreplay --help
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
