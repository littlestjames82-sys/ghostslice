"""Source-bundle immutability: the bundle is read-only input.

sha256 of every file in the source bundle must be identical before and
after every conversion, and no new file may appear inside it.
"""
from __future__ import annotations

import pytest

from conftest import combined, run_gc, snapshot_tree


@pytest.mark.parametrize("target", ["agents", "cursor", "copilot",
                                    "generic", "all"])
def test_bundle_byte_identical_after_conversion(bundle_copy, tmp_path,
                                                target):
    before = snapshot_tree(bundle_copy)
    proc = run_gc("convert", str(bundle_copy), "--to", target,
                  "-o", str(tmp_path / "out"))
    assert proc.returncode == 0, combined(proc)
    after = snapshot_tree(bundle_copy)
    assert after == before, (
        f"bundle changed under target {target}: "
        f"added={set(after) - set(before)}, "
        f"removed={set(before) - set(after)}, "
        f"changed={[k for k in before if before[k] != after.get(k)]}")


def test_inspect_leaves_bundle_byte_identical(bundle_copy):
    before = snapshot_tree(bundle_copy)
    proc = run_gc("inspect", str(bundle_copy))
    assert proc.returncode == 0, combined(proc)
    assert snapshot_tree(bundle_copy) == before


def test_failed_conversion_leaves_bundle_byte_identical(bundle_copy,
                                                        tmp_path):
    before = snapshot_tree(bundle_copy)
    # Refused run: output inside the bundle.
    proc = run_gc("convert", str(bundle_copy), "--to", "agents",
                  "-o", str(bundle_copy / "inside"))
    assert proc.returncode == 2, combined(proc)
    assert snapshot_tree(bundle_copy) == before


def test_no_output_written_into_bundle_on_success(bundle_copy, tmp_path):
    proc = run_gc("convert", str(bundle_copy), "--to", "all",
                  "-o", str(tmp_path / "elsewhere"))
    assert proc.returncode == 0, combined(proc)
    names = {p.name for p in bundle_copy.rglob("*") if p.is_file()}
    assert "AGENTS.md" not in names
    assert "LOSSES.md" not in names
    assert "prompt.md" not in names
