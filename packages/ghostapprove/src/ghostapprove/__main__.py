"""Entry point for ``python3 -m ghostapprove``.

Equivalent to the ``ghostapprove`` console script: both simply call
:func:`ghostapprove.cli.main` and exit with its return code.
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
