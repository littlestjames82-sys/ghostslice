"""Entry point for ``python -m ghostdeps``; delegates to :mod:`ghostdeps.cli`."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
