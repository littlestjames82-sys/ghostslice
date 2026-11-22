"""Fixture-validity tests: these need no core and always run.

They prove the planted premises the CLI tests rely on:

- the repro bundle references exactly main.py, config.py and
  secrets_store.py, and NOT helper.py, util_math.py or
  unrelated.py;
- the import chain main.py -> helper.py -> util_math.py really
  exists in the fixture source (the closure premise);
- the planted canary lives only in secrets_store.py;
- the bundle builder writes a GhostSlice-shaped manifest whose
  hashes and totals match the bundle's own files/ copies;
- the big project's referenced files total several KB (the
  size-cap premise).
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module)
    return found


def test_repro_bundle_references_exactly_the_seed_set(tmp_path):
    bundle = helpers.build_bundle(
        helpers.REPRO_PROJECT, tmp_path / "b", helpers.REPRO_BUNDLE_FILES)
    manifest = json.loads((bundle / "manifest.json").read_text())
    paths = [f["path"] for f in manifest["files"]]
    assert paths == ["app/main.py", "app/config.py", "app/secrets_store.py"]
    for absent in ("app/helper.py", "app/util_math.py",
                   "app/unrelated.py", "notes.txt"):
        assert absent not in paths


def test_bundle_manifest_hashes_and_totals_are_consistent(tmp_path):
    bundle = helpers.build_bundle(
        helpers.REPRO_PROJECT, tmp_path / "b", helpers.REPRO_BUNDLE_FILES)
    manifest = json.loads((bundle / "manifest.json").read_text())
    total = 0
    for entry in manifest["files"]:
        copy = bundle / "files" / entry["path"]
        digest = hashlib.sha256(copy.read_bytes()).hexdigest()
        assert digest == entry["sha256"], entry["path"]
        source = helpers.REPRO_PROJECT / entry["path"]
        assert copy.read_bytes() == source.read_bytes(), entry["path"]
        total += entry["original_tokens"]
    assert manifest["total_original_tokens"] == total
    assert manifest["root"] == str(helpers.REPRO_PROJECT)


def test_import_chain_premise_main_helper_utilmath():
    main_imports = _imports_of(helpers.REPRO_PROJECT / "app/main.py")
    assert "app.helper" in main_imports
    assert "app.config" in main_imports
    helper_imports = _imports_of(helpers.REPRO_PROJECT / "app/helper.py")
    assert "app.util_math" in helper_imports


def test_unrelated_file_is_imported_by_nothing():
    for py in (helpers.REPRO_PROJECT / "app").glob("*.py"):
        assert "app.unrelated" not in _imports_of(py), py.name
        assert "unrelated" not in _imports_of(py), py.name


def test_canary_is_planted_only_in_secrets_store():
    hits = []
    for path in helpers.REPRO_PROJECT.rglob("*"):
        if path.is_file() and helpers.CANARY.encode() in path.read_bytes():
            hits.append(path.relative_to(helpers.REPRO_PROJECT).as_posix())
    assert hits == [helpers.SECRET_FILE]


def test_big_project_size_premise():
    total = 0
    for rel, _mode in helpers.BIG_BUNDLE_FILES:
        total += (helpers.BIG_PROJECT / rel).stat().st_size
    assert total > 4000, total
