"""Entry point for ``python -m ghostprimer`` (same CLI as ``ghostprimer``)."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
