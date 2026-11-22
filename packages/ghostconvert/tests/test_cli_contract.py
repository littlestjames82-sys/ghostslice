"""CLI contract tests: targets, inspect, argument and exit-code shape."""
from __future__ import annotations

from conftest import combined, read_manifest, run_gc, snapshot_tree


def test_targets_lists_all_four_and_their_artifacts():
    proc = run_gc("targets")
    assert proc.returncode == 0, combined(proc)
    out = proc.stdout
    for target in ("agents", "cursor", "copilot", "generic"):
        assert target in out
    assert "AGENTS.md" in out
    assert "copilot-instructions.md" in out
    assert "prompt.md" in out
    assert ".mdc" in out


def test_version_flag():
    proc = run_gc("--version")
    assert proc.returncode == 0, combined(proc)
    assert "0.1.0" in proc.stdout


def test_inspect_reports_bundle_without_writing(golden_bundle, tmp_path):
    before = snapshot_tree(golden_bundle)
    proc = run_gc("inspect", str(golden_bundle))
    assert proc.returncode == 0, combined(proc)
    manifest = read_manifest(golden_bundle)
    from pathlib import Path
    assert Path(manifest["root"]).name in proc.stdout
    # Mode census and totals from the manifest show up.
    modes = {e["mode"] for e in manifest["files"]}
    for mode in modes:
        assert mode in proc.stdout
    assert str(manifest["total_sliced_tokens"]) in proc.stdout
    assert str(manifest["total_original_tokens"]) in proc.stdout
    # inspect writes nothing: bundle unchanged, no stray files in cwd area.
    assert snapshot_tree(golden_bundle) == before


def test_inspect_missing_bundle_exits_2(tmp_path):
    proc = run_gc("inspect", str(tmp_path / "no-such-bundle"))
    assert proc.returncode == 2, combined(proc)


def test_inspect_names_files_with_missing_bodies(golden_bundle):
    # The golden bundle's strip-tests entry has no body on disk; inspect
    # must not pretend the bundle is complete.
    proc = run_gc("inspect", str(golden_bundle))
    assert proc.returncode == 0, combined(proc)
    bodyless = [e["path"] for e in read_manifest(golden_bundle)["files"]
                if e["mode"] not in ("exclude",)
                and not (golden_bundle / "files" / e["path"]).is_file()]
    assert bodyless, "fixture premise: golden bundle has a bodyless entry"
    for path in bodyless:
        assert path in combined(proc)


def test_convert_unknown_target_exits_2(golden_bundle, tmp_path):
    proc = run_gc("convert", str(golden_bundle), "--to", "word",
                  "-o", str(tmp_path / "out"))
    assert proc.returncode == 2, combined(proc)
    assert not (tmp_path / "out").exists()


def test_convert_without_target_exits_2(golden_bundle, tmp_path):
    proc = run_gc("convert", str(golden_bundle), "-o", str(tmp_path / "out"))
    assert proc.returncode == 2, combined(proc)


def test_no_command_exits_2():
    proc = run_gc()
    assert proc.returncode == 2, combined(proc)
