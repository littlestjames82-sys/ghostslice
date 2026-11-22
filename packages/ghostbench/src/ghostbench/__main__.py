"""Entry point for ``python3 -m ghostbench``; see ``cli.py``.

Equivalent to the installed ``ghostbench`` console script.
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
