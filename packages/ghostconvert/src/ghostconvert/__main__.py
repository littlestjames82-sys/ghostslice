"""Entry point for ``python3 -m ghostconvert``.

Equivalent to the installed ``ghostconvert`` command; all argument
parsing and work live in :mod:`ghostconvert.cli`.
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
