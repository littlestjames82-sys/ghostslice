"""Verify subcommand: a converted output can be audited against its
bundle after it leaves the tool.

Verify is read-only (bundle and output byte-identical afterwards,
pass or fail), exits 0 on a faithful conversion, 1 on any divergence
with the concrete divergence named, and 2 on a bad bundle. It judges
conversion fidelity only: order, mode labels, verbatim bodies,
excluded files staying out, current LOSSES.md, and no stale Cursor
rule files.
"""
from __future__ import annotations

import pytest

from conftest import (combined, entry, run_gc, snapshot_tree,
                      write_hand_bundle)


def convert_ok(bundle, target, out):
    proc = run_gc("convert", str(bundle), "--to", target, "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    return out


def verify(bundle, target, out):
    return run_gc("verify", str(bundle), str(out), "--to", target)


@pytest.mark.parametrize("target", ["agents", "cursor", "copilot",
                                    "generic"])
def test_verify_passes_on_fresh_conversion(golden_bundle, tmp_path, target):
    out = convert_ok(golden_bundle, target, tmp_path / "out")
    proc = verify(golden_bundle, target, out)
    assert proc.returncode == 0, combined(proc)
    assert "OK" in proc.stdout
    assert target in proc.stdout


def test_verify_all_passes_and_writes_nothing(golden_bundle, tmp_path):
    out = convert_ok(golden_bundle, "all", tmp_path / "out")
    before_bundle = snapshot_tree(golden_bundle)
    before_out = snapshot_tree(out)
    proc = verify(golden_bundle, "all", out)
    assert proc.returncode == 0, combined(proc)
    assert snapshot_tree(golden_bundle) == before_bundle
    assert snapshot_tree(out) == before_out


def test_verify_detects_tampered_body_and_writes_nothing(
        golden_bundle, tmp_path):
    out = convert_ok(golden_bundle, "agents", tmp_path / "out")
    artifact = out / "AGENTS.md"
    artifact.write_text(
        artifact.read_text(encoding="utf-8").replace(
            "Hello,", "Tampered,"), encoding="utf-8")
    before_out = snapshot_tree(out)
    proc = verify(golden_bundle, "agents", out)
    assert proc.returncode == 1, combined(proc)
    assert "AGENTS.md" in combined(proc)
    assert "verbatim" in combined(proc)
    assert snapshot_tree(out) == before_out


def test_verify_detects_missing_losses(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("only.py", "full")],
        bodies={"only.py": "print('only')\n"})
    out = convert_ok(bundle, "generic", tmp_path / "out")
    (out / "LOSSES.md").unlink()
    proc = verify(bundle, "generic", out)
    assert proc.returncode == 1, combined(proc)
    assert "LOSSES.md" in combined(proc)


def test_verify_detects_stale_losses(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("only.py", "full", sha256="a" * 64)],
        bodies={"only.py": "print('only')\n"})
    out = convert_ok(bundle, "agents", tmp_path / "out")
    losses = out / "LOSSES.md"
    losses.write_text("# Conversion losses: agents\n\nedited\n",
                      encoding="utf-8")
    proc = verify(bundle, "agents", out)
    assert proc.returncode == 1, combined(proc)
    assert "LOSSES.md" in combined(proc)


def test_verify_detects_out_of_order_sections(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("a.py", "full"), entry("b.py", "full")],
        bodies={"a.py": "A = 1\n", "b.py": "B = 2\n"})
    out = convert_ok(bundle, "generic", tmp_path / "out")
    text = (out / "prompt.md").read_text(encoding="utf-8")
    # Swap the two file sections by swapping their unique bodies and
    # headers together is complex; instead reverse the header order by
    # exchanging the header strings' positions via a placeholder.
    assert text.find("a.py") < text.find("b.py")
    swapped = (text.replace("# File: a.py", "# File: @@TMP@@")
               .replace("# File: b.py", "# File: a.py")
               .replace("# File: @@TMP@@", "# File: b.py"))
    (out / "prompt.md").write_text(swapped, encoding="utf-8")
    proc = verify(bundle, "generic", out)
    assert proc.returncode == 1, combined(proc)
    assert "prompt.md" in combined(proc)
    assert "order" in combined(proc)


def test_verify_detects_excluded_section_leak(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("keep.py", "full"),
                 entry("vendor/blob.py", "exclude")],
        bodies={"keep.py": "KEEP = 1\n"})
    out = convert_ok(bundle, "agents", tmp_path / "out")
    artifact = out / "AGENTS.md"
    artifact.write_text(
        artifact.read_text(encoding="utf-8")
        + "\n## File: vendor/blob.py (mode: exclude)\n\nVENDORED = True\n",
        encoding="utf-8")
    proc = verify(bundle, "agents", out)
    assert proc.returncode == 1, combined(proc)
    assert "vendor/blob.py" in combined(proc)
    assert "excluded" in combined(proc)


def test_verify_detects_stale_cursor_rule(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("src/a.py", "full")],
        bodies={"src/a.py": "A = 1\n"})
    out = convert_ok(bundle, "cursor", tmp_path / "out")
    stale = out / ".cursor" / "rules" / "ghostconvert-stale.mdc"
    stale.write_text("---\ndescription: stale\n---\n", encoding="utf-8")
    proc = verify(bundle, "cursor", out)
    assert proc.returncode == 1, combined(proc)
    assert "ghostconvert-stale.mdc" in combined(proc)


def test_verify_wrong_target_and_missing_output_fail(
        golden_bundle, tmp_path):
    out = convert_ok(golden_bundle, "agents", tmp_path / "out")
    proc = verify(golden_bundle, "copilot", out)
    assert proc.returncode == 1, combined(proc)
    proc = verify(golden_bundle, "agents", tmp_path / "no-such-out")
    assert proc.returncode == 1, combined(proc)
    assert "not found" in combined(proc)


def test_verify_bad_bundle_exits_2(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    proc = verify(tmp_path / "no-such-bundle", "agents", out)
    assert proc.returncode == 2, combined(proc)
