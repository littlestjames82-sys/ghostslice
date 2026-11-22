"""Run GhostRecipes as ``python3 -m ghostrecipes``.

Equivalent to the ``ghostrecipes`` console script; both call
:func:`ghostrecipes.cli.main`. From a source checkout, run it as
``PYTHONPATH=src python3 -m ghostrecipes --help``.
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
