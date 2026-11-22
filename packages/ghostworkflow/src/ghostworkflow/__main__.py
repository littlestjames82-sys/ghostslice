"""Module entry point: ``python3 -m ghostworkflow ...``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
