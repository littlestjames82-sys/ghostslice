"""Module entry point: ``python -m ghostworktree ...`` (same CLI as the script)."""
import sys
from .cli import main
if __name__ == "__main__":
    sys.exit(main())
