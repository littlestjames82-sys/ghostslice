"""Entry point for ``python3 -m ghostenv``; see :mod:`ghostenv.cli`."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
