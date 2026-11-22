"""GhostLift tests. Bootstrap import paths so both pytest and a
plain ``python -m unittest`` run from the repo root can find the
core (``src/``) and the example lifters (``examples/``)."""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
for _part in (_ROOT / "src", _ROOT / "examples"):
    if _part.is_dir() and str(_part) not in sys.path:
        sys.path.insert(0, str(_part))
