"""Entry point for ``python3 -m ghostatlas``.

Delegates to :func:`ghostatlas.cli.main`; see that module for the
command syntax (``build`` / ``scan``) and the exit-code contract.
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
