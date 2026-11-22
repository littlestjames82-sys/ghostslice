"""Consistency verification bar (PLAN.md): every token number in
ATLAS.md must equal the number from a same-run GhostSlice scan.

Method: scan the (copied) fixture project with GhostSlice first,
record per-file estimated tokens and the total, then build the
Atlas against that same unchanged project state and compare the
numbers ATLAS.md prints.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import (
    GHOSTSLICE_SRC,
    ghostslice_available,
    numbers_on_lines_with,
    requires_core,
)

pytestmark = [
    requires_core,
    pytest.mark.skipif(not ghostslice_available(), reason="GhostSlice checkout not found"),
]

if str(GHOSTSLICE_SRC) not in sys.path:
    sys.path.insert(0, str(GHOSTSLICE_SRC))

from ghostslice.scanner import scan  # noqa: E402


@requires_core
def test_atlas_md_total_matches_ghostslice_scan(build, ground_truth: Path):
    result = scan(str(ground_truth))
    total = sum(f.tokens for f in result.files)
    built = build(ground_truth)
    assert built.result.returncode == 0, built.result.stderr
    brief = built.atlas_md
    assert brief, "ATLAS.md brief was not produced"
    total_lines_numbers = numbers_on_lines_with(brief, "total")
    assert total in total_lines_numbers, (
        f"GhostSlice same-run total is {total} estimated tokens; no line in "
        f"ATLAS.md that says 'total' carries that number "
        f"(found {sorted(set(total_lines_numbers))})"
    )


@requires_core
def test_atlas_md_per_file_tokens_match_ghostslice_scan(build, ground_truth: Path):
    result = scan(str(ground_truth))
    per_file = {f.path: f.tokens for f in result.files}
    built = build(ground_truth)
    assert built.result.returncode == 0, built.result.stderr
    brief = built.atlas_md
    checked = 0
    for name, tokens in per_file.items():
        on_lines = numbers_on_lines_with(brief, name)
        if not on_lines:
            continue  # a file may be collapsed in the brief; see checked-count below
        assert tokens in on_lines, (
            f"ATLAS.md prints {on_lines} on lines naming {name}, GhostSlice "
            f"same-run scan says {tokens}"
        )
        checked += 1
    # The brief must carry checkable per-file numbers for the code files
    # at minimum, otherwise the consistency bar cannot be met at all.
    assert checked >= 3, f"only {checked} files had token numbers in ATLAS.md"
