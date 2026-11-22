"""Console entry point: ``python -m ghostport`` delegates to the CLI."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
