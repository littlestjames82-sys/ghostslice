"""Module entry point: ``python3 -m ghosthandoff ...``.

Equivalent to the ``ghosthandoff`` console script; all behaviour
lives in :mod:`ghosthandoff.cli`. Examples::

    python3 -m ghosthandoff pack <project>
    python3 -m ghosthandoff show ./handoff-out
    python3 -m ghosthandoff --help
"""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
