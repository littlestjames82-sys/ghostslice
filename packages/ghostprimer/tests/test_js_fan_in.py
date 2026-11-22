"""JS/TS fan-in (parser-lite import graph), polish round Oct 14, 2026.

Ground truth for tests/fixtures/js_project, computed by hand from the
fixture sources before the core change:

  src/index.ts          entry point (package.json main, index.ts).
                        imports ./util, ./lib/helper.js (NodeNext .js
                        specifier for the .ts source), ./polyfill
                        (side effect), re-exports ./thing, dynamic
                        import('./lazy'), and bare 'react' (a package,
                        never a project file).
  src/util.ts           imports ./lib/helper.js and ./thing, dynamic
                        import('./lazy') after three traps that mention
                        ./ghost: a line comment, a block comment, and a
                        string literal, plus a regex literal holding a
                        quote. None of the traps may count.
  src/lib/helper.ts     imports ../util.
  src/legacy.js         require('./legacy-helper'); imported by nobody.
  src/legacy-helper.js  imported by legacy.js only.
  src/ghost.ts          referenced only by the traps: fan-in 0.
  src/orphan.ts         imported by nobody: fan-in 0.

Expected fan-in: util 2, lib/helper 2, thing 2, lazy 2, polyfill 1,
legacy-helper 1, index 0, ghost 0, orphan 0, legacy 0.
"""
from __future__ import annotations

import pytest

from conftest import (build, combined, copy_fixture, file_entry,
                      load_manifest)

EXPECTED_FAN_IN = {
    "src/index.ts": 0,
    "src/util.ts": 2,
    "src/lib/helper.ts": 2,
    "src/thing.ts": 2,
    "src/lazy.ts": 2,
    "src/polyfill.ts": 1,
    "src/legacy-helper.js": 1,
}
UNREFERENCED = ("src/ghost.ts", "src/orphan.ts", "src/legacy.js")
# Entries first, then fan-in descending, path order inside a tie.
EXPECTED_ORDER = [
    "src/index.ts",
    "src/lazy.ts",
    "src/lib/helper.ts",
    "src/thing.ts",
    "src/util.ts",
    "src/legacy-helper.js",
    "src/polyfill.ts",
]


@pytest.fixture()
def js_bundle(tmp_path):
    project = copy_fixture("js_project", tmp_path / "js_project")
    out = tmp_path / "js_bundle"
    proc = build(project, out)
    assert proc.returncode == 0, combined(proc)
    return out


def test_js_fan_in_values_match_hand_computed_graph(js_bundle):
    manifest = load_manifest(js_bundle)
    for rel, expected in EXPECTED_FAN_IN.items():
        entry = file_entry(manifest, rel)
        assert entry is not None, f"{rel} missing from the starter slice"
        assert entry.get("fan_in") == expected, (
            f"{rel}: fan_in {entry.get('fan_in')} != hand-computed "
            f"{expected}")
        assert entry.get("fan_in_method") == "parser-lite", entry


def test_js_entry_point_detected(js_bundle):
    manifest = load_manifest(js_bundle)
    entry = file_entry(manifest, "src/index.ts")
    assert entry is not None
    assert entry.get("entry_point") is True, entry
    assert "src/index.ts" in manifest.get("entry_points", [])


def test_js_unreferenced_files_excluded_and_named(js_bundle):
    manifest = load_manifest(js_bundle)
    sliced = {e.get("path") for e in manifest.get("files", [])}
    not_included = {e.get("path"): e.get("reason", "")
                    for e in manifest.get("not_included", [])}
    for rel in UNREFERENCED:
        assert rel not in sliced, f"{rel} sliced in despite fan-in 0"
        assert rel in not_included, f"{rel} not named in not_included"
        assert "unreferenced" in not_included[rel], not_included[rel]


def test_js_slice_order_is_entry_then_fan_in(js_bundle):
    manifest = load_manifest(js_bundle)
    order = [e.get("path") for e in manifest.get("files", [])]
    assert order == EXPECTED_ORDER, order


def test_python_fan_in_method_is_ast(built_bundle):
    manifest = load_manifest(built_bundle)
    entry = file_entry(manifest, "src/widgetforge/core.py")
    assert entry is not None
    assert entry.get("fan_in_method") == "ast", entry
    assert entry.get("fan_in", 0) > 0, entry
