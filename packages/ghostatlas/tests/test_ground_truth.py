"""Ground-truth verification bar (PLAN.md): on the fixture repo, the
map edges, the reading-order top pick, and the dead-zone list must
match the fixture's stated truth.
"""

from __future__ import annotations

import re
from pathlib import Path

from conftest import requires_core, section_after


def _edges_from_data(data: dict | None) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    if not data:
        return edges
    # GhostSlice graph shape: {"graph": {src: {"imports": [dst, ...]}}}
    graph = data.get("graph") if isinstance(data, dict) else None
    if isinstance(graph, dict):
        for src, node in graph.items():
            if isinstance(node, dict):
                for dst in node.get("imports", []):
                    edges.add((str(src).rsplit("/", 1)[-1], str(dst).rsplit("/", 1)[-1]))

    def walk(node):
        if isinstance(node, dict):
            src = node.get("from") or node.get("source") or node.get("src")
            dst = node.get("to") or node.get("target") or node.get("dst")
            if isinstance(src, str) and isinstance(dst, str):
                edges.add((src.rsplit("/", 1)[-1], dst.rsplit("/", 1)[-1]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            if len(node) == 2 and all(isinstance(x, str) for x in node):
                edges.add((node[0].rsplit("/", 1)[-1], node[1].rsplit("/", 1)[-1]))
            for value in node:
                walk(value)

    walk(data)
    return edges


def _edges_from_text(text: str) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    pattern = re.compile(
        r"([\w./-]+\.py)\s*(?:->|→|--+>|—>|=>)\s*([\w./-]+\.py)"
    )
    for src, dst in pattern.findall(text):
        edges.add((src.rsplit("/", 1)[-1], dst.rsplit("/", 1)[-1]))
    return edges


@requires_core
def test_map_edges_match_truth(build, ground_truth: Path, truth: dict):
    built = build(ground_truth)
    assert built.result.returncode == 0, built.result.stderr
    edges = _edges_from_data(built.data) | _edges_from_text(built.html + "\n" + built.atlas_md)
    assert edges, "no machine- or text-readable import edges found in Atlas output"
    for src, dst in truth["edges"]:
        if src.startswith("test_"):
            continue  # test files may be grouped in a test panel; app edges are the bar
        assert (src, dst) in edges, f"Atlas map is missing known edge {src} -> {dst}"


@requires_core
def test_reading_order_top_pick_is_entry_point(build, ground_truth: Path, truth: dict):
    built = build(ground_truth)
    assert built.result.returncode == 0, built.result.stderr
    brief = built.atlas_md
    section = section_after(brief, "start here", "reading order")
    assert section, "ATLAS.md has no start-here / reading-order section"
    mentions = re.findall(r"[\w.-]+\.py", section)
    assert mentions, "reading-order section names no files"
    assert mentions[0] == truth["entry_point"], (
        f"reading order starts with {mentions[0]}, ground truth entry point is "
        f"{truth['entry_point']}"
    )


@requires_core
def test_dead_zones_list_dead_file(build, ground_truth: Path, truth: dict):
    built = build(ground_truth)
    assert built.result.returncode == 0, built.result.stderr
    combined = built.atlas_md + "\n" + built.html
    section = section_after(combined, "dead zone", "dead-zone", "worth asking about")
    assert section, "Atlas output has no dead-zones section"
    for dead in truth["dead_files"]:
        assert dead in section, f"{dead} is not listed as a dead zone"
    # Dead means dead: it must not show up as a start-here pick.
    start = section_after(built.atlas_md, "start here", "reading order")
    for dead in truth["dead_files"]:
        assert dead not in start


@requires_core
def test_most_depended_on_is_named_with_reason(build, ground_truth: Path, truth: dict):
    built = build(ground_truth)
    assert built.result.returncode == 0, built.result.stderr
    brief = built.atlas_md
    lines = [ln for ln in brief.splitlines() if truth["most_depended_on"] in ln]
    assert lines, "most depended-on module never mentioned in ATLAS.md"
    joined = " ".join(lines).lower()
    assert "depend" in joined or "import" in joined or "caller" in joined
