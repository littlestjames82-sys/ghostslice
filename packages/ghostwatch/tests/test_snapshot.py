"""Snapshot: source hashes, symbols, bundle record, ignores."""
from __future__ import annotations

import hashlib
import json

from conftest import (assert_no_traceback, combined, load_default_snapshot,
                      snapshot)


def test_snapshot_records_source_hashes_and_ast_symbols(project_factory):
    project = project_factory()
    proc = snapshot(project)
    assert proc.returncode == 0, combined(proc)
    assert_no_traceback(proc)
    snap = load_default_snapshot(project)
    assert snap["tool"] == "ghostwatch"
    app = snap["files"]["src/app.py"]
    # Hash is of the SOURCE bytes (unlike the manifest's sliced hash).
    assert app["sha256"] == hashlib.sha256(
        (project / "src/app.py").read_bytes()).hexdigest()
    assert app["size"] == (project / "src/app.py").stat().st_size
    assert app["symbol_method"] == "ast"
    for name in ("compute_total", "item_price", "item_count", "render_total"):
        assert name in app["symbols"]
    # No file bodies are stored, ever.
    assert "compute_total(items)" not in json.dumps(snap)


def test_snapshot_records_bundle_manifest_hash(project_factory):
    project = project_factory()
    assert snapshot(project).returncode == 0
    snap = load_default_snapshot(project)
    manifest_bytes = (project / ".claude_context/manifest.json").read_bytes()
    assert snap["bundle"]["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    manifest = json.loads(manifest_bytes)
    assert snap["bundle"]["generated_at"] == manifest["generated_at"]
    assert [f["path"] for f in snap["bundle"]["files"]] == [
        "src/app.py", "src/util.py"]


def test_snapshot_ignores_default_dirs_and_gitignore_lite(project_factory, tmp_path):
    project = project_factory()
    (project / "node_modules").mkdir()
    (project / "node_modules" / "dep.js").write_text("function dep() {}\n")
    (project / "ignored.log").write_text("noise\n")
    (project / ".gitignore").write_text("ignored.log\n")
    assert snapshot(project).returncode == 0
    snap = load_default_snapshot(project)
    assert "node_modules/dep.js" not in snap["files"]
    assert "ignored.log" not in snap["files"]
    # The bundle dir itself is never hashed as project content.
    assert not any(p.startswith(".claude_context") for p in snap["files"])
    assert not any(p.startswith(".ghostwatch") for p in snap["files"])


def test_snapshot_parser_lite_symbols_for_javascript(project_factory):
    project = project_factory()
    (project / "src" / "web.js").write_text(
        "export function greet(name) { return name; }\n"
        "export class Widget {}\n"
        "const helper = (x) => x;\n")
    assert snapshot(project).returncode == 0
    entry = load_default_snapshot(project)["files"]["src/web.js"]
    assert entry["symbol_method"] == "parser-lite"
    assert "greet" in entry["symbols"] and "Widget" in entry["symbols"]
    assert "helper" in entry["symbols"]


def test_snapshot_binary_file_hash_only_no_symbols(project_factory):
    project = project_factory()
    blob = bytes(range(256)) * 4
    (project / "src" / "blob.bin").write_bytes(blob)
    assert snapshot(project).returncode == 0
    entry = load_default_snapshot(project)["files"]["src/blob.bin"]
    assert entry["sha256"] == hashlib.sha256(blob).hexdigest()
    assert entry["symbols"] == []
    assert entry["symbol_method"] == "none"


def test_snapshot_custom_output_path(project_factory, tmp_path):
    project = project_factory()
    out = tmp_path / "elsewhere" / "snap.json"
    proc = snapshot(project, "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    assert out.exists()
    assert json.loads(out.read_text())["tool"] == "ghostwatch"


def test_snapshot_without_bundle_is_project_only(project_factory):
    project = project_factory(with_bundle=False)
    proc = snapshot(project)
    assert proc.returncode == 0, combined(proc)
    assert "none found" in combined(proc)
    assert load_default_snapshot(project)["bundle"] is None


def test_snapshot_missing_project_is_clean_error(tmp_path):
    proc = snapshot(tmp_path / "does-not-exist")
    assert proc.returncode == 2
    assert "not found" in combined(proc) or "not a directory" in combined(proc)
    assert_no_traceback(proc)
