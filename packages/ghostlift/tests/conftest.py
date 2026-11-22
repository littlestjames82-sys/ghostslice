"""Test bootstrap: make the (Agent A owned) core importable if present.

This file does not create or stub the core. If ``src/ghostlift`` does
not exist yet, core-contract tests skip with an explicit reason and
the fixture / example tests still run.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
EXAMPLES = ROOT / "examples"
if str(EXAMPLES) not in sys.path:
    sys.path.insert(0, str(EXAMPLES))
