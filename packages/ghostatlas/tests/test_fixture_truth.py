"""Fixture integrity: the ground-truth fixture really has the shape
TRUTH.json claims, judged by GhostSlice itself (scanner + graph +
entry points). These tests do not need the GhostAtlas core; they pin
the fixture so an Atlas failure cannot be a fixture lie.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import GHOSTSLICE_SRC, ghostslice_available

pytestmark = pytest.mark.skipif(
    not ghostslice_available(), reason="GhostSlice checkout not found next to this repo"
)

if str(GHOSTSLICE_SRC) not in sys.path:
    sys.path.insert(0, str(GHOSTSLICE_SRC))

from ghostslice.graph import build_graph, find_entry_points, importers_of  # noqa: E402
from ghostslice.scanner import scan  # noqa: E402


def _scan(ground_truth: Path):
    return scan(str(ground_truth))


def test_fixture_files_match_truth(ground_truth: Path, truth: dict):
    result = _scan(ground_truth)
    assert sorted(f.path for f in result.files) == sorted(truth["files"])


def test_fixture_entry_point_is_main(ground_truth: Path, truth: dict):
    result = _scan(ground_truth)
    entries = find_entry_points(result)
    assert truth["entry_point"] in entries
    assert entries[0] == truth["entry_point"]


def test_fixture_edges_match_truth(ground_truth: Path, truth: dict):
    result = _scan(ground_truth)
    graph = build_graph(result)
    edges = {
        (src, dst)
        for src, node in graph.items()
        for dst in node.get("imports", [])
    }
    for src, dst in truth["edges"]:
        assert (src, dst) in edges, f"missing known edge {src} -> {dst}"


def test_fixture_dead_file_has_no_importers(ground_truth: Path, truth: dict):
    result = _scan(ground_truth)
    graph = build_graph(result)
    importers = importers_of(graph)
    for dead in truth["dead_files"]:
        assert importers.get(dead, []) == []
        assert graph[dead].get("imports", []) == []


def test_fixture_most_depended_on(ground_truth: Path, truth: dict):
    result = _scan(ground_truth)
    graph = build_graph(result)
    importers = importers_of(graph)
    counts = {name: len(who) for name, who in importers.items()}
    top = max(counts, key=lambda k: counts[k])
    assert top == truth["most_depended_on"]


def test_fixture_token_totals_are_positive(ground_truth: Path):
    result = _scan(ground_truth)
    per_file = {f.path: f.tokens for f in result.files}
    assert all(v > 0 for v in per_file.values())
    # Ground truth recorded at fixture creation; see REPORT_B.md.
    assert sum(per_file.values()) == 280
