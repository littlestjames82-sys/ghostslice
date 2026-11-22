"""Safety rules: refusal paths exit 2, never write partial output into
the wrong place, and never modify the source bundle.
"""
from __future__ import annotations

import json

from conftest import (combined, entry, run_gc, snapshot_tree,
                      write_hand_bundle)


def test_malformed_manifest_exits_2(bundle_copy, tmp_path):
    (bundle_copy / "manifest.json").write_text("{not json",
                                               encoding="utf-8")
    proc = run_gc("convert", str(bundle_copy), "--to", "agents",
                  "-o", str(tmp_path / "out"))
    assert proc.returncode == 2, combined(proc)
    assert "manifest" in combined(proc).lower()
    assert not (tmp_path / "out" / "AGENTS.md").exists()


def test_missing_manifest_exits_2(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    proc = run_gc("convert", str(empty), "--to", "agents",
                  "-o", str(tmp_path / "out"))
    assert proc.returncode == 2, combined(proc)


def test_manifest_without_files_list_exits_2(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps({"tool": "ghostslice", "files": "nope"}),
        encoding="utf-8")
    proc = run_gc("convert", str(bundle), "--to", "agents",
                  "-o", str(tmp_path / "out"))
    assert proc.returncode == 2, combined(proc)


def test_bundle_with_no_readable_bodies_exits_2(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("nothing.py", "full", sha256="0" * 64,
                       original_tokens=3, sliced_tokens=3)])
    proc = run_gc("convert", str(bundle), "--to", "agents",
                  "-o", str(tmp_path / "out"))
    assert proc.returncode == 2, combined(proc)
    assert not (tmp_path / "out" / "AGENTS.md").exists()


def test_output_equal_to_bundle_exits_2(bundle_copy):
    before = snapshot_tree(bundle_copy)
    proc = run_gc("convert", str(bundle_copy), "--to", "agents",
                  "-o", str(bundle_copy))
    assert proc.returncode == 2, combined(proc)
    assert snapshot_tree(bundle_copy) == before


def test_output_inside_bundle_exits_2(bundle_copy):
    before = snapshot_tree(bundle_copy)
    proc = run_gc("convert", str(bundle_copy), "--to", "agents",
                  "-o", str(bundle_copy / "nested" / "out"))
    assert proc.returncode == 2, combined(proc)
    assert snapshot_tree(bundle_copy) == before


def test_overwrite_refused_without_force(golden_bundle, tmp_path):
    out = tmp_path / "out"
    proc = run_gc("convert", str(golden_bundle), "--to", "agents",
                  "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    first = (out / "AGENTS.md").read_text(encoding="utf-8")
    proc = run_gc("convert", str(golden_bundle), "--to", "agents",
                  "-o", str(out))
    assert proc.returncode == 2, combined(proc)
    assert "AGENTS.md" in combined(proc)
    # The existing artifact was not touched by the refused run.
    assert (out / "AGENTS.md").read_text(encoding="utf-8") == first


def test_overwrite_allowed_with_force(golden_bundle, tmp_path):
    out = tmp_path / "out"
    proc = run_gc("convert", str(golden_bundle), "--to", "agents",
                  "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    (out / "AGENTS.md").write_text("stale hand edit\n", encoding="utf-8")
    proc = run_gc("convert", str(golden_bundle), "--to", "agents",
                  "-o", str(out), "--force")
    assert proc.returncode == 0, combined(proc)
    assert "stale hand edit" not in \
        (out / "AGENTS.md").read_text(encoding="utf-8")


def test_refused_overwrite_writes_no_partial_artifacts(golden_bundle,
                                                       tmp_path):
    # Pre-create only LOSSES.md: a refused run must not add AGENTS.md,
    # and an all-target run must not write earlier targets' artifacts
    # before hitting the collision.
    out = tmp_path / "out"
    out.mkdir()
    (out / "LOSSES.md").write_text("mine\n", encoding="utf-8")
    proc = run_gc("convert", str(golden_bundle), "--to", "agents",
                  "-o", str(out))
    assert proc.returncode == 2, combined(proc)
    assert not (out / "AGENTS.md").exists()
    assert (out / "LOSSES.md").read_text(encoding="utf-8") == "mine\n"


def test_bundle_path_that_is_a_file_exits_2(tmp_path):
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("x\n", encoding="utf-8")
    proc = run_gc("convert", str(not_a_dir), "--to", "agents",
                  "-o", str(tmp_path / "out"))
    assert proc.returncode == 2, combined(proc)
