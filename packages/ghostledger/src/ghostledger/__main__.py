"""Entry point for ``python -m ghostledger``; delegates to :func:`ghostledger.cli.main`."""
from .cli import main
import sys
if __name__ == "__main__":
    sys.exit(main())
