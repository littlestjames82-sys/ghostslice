"""Run GhostWatch as `python -m ghostwatch ...` (see cli.py / --help)."""
from .cli import main
import sys
if __name__ == "__main__":
    sys.exit(main())
