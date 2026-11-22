"""Check with a snapshot baseline: fresh, planted changes, reports."""
from __future__ import annotations

import json

from conftest import (assert_no_traceback, check, check_json, combined)


def test_fresh_when_nothing_changed(snapshotted_project):
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 0, combined(proc)
    assert report["verdict"] == "fresh"
    assert report["stale"] is False and report["pack_stale"] is False
    assert report["baseline"] == "snapshot"


def test_planted_edit_to_bundled_file_is_stale_by_name(snapshotted_project):
    # PLAN verification bar: edit a bundled file's body, symbols unchanged.
    p = snapshotted_project / "src/app.py"
    p.write_text(p.read_text().replace(
        'return "Total: %.2f" % total', 'return "TOTAL=%.2f" % total'))
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 1, combined(proc)
    assert report["verdict"] == "stale"
    paths = [f["path"] for f in report["findings"]["changed_in_bundle"]]
    assert "src/app.py" in paths


def test_edit_to_unbundled_file_is_context_not_stale(snapshotted_project):
    p = snapshotted_project / "notes.txt"
    p.write_text(p.read_text() + "Extra line.\n")
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 0, combined(proc)
    assert report["verdict"] == "fresh"
    paths = [f["path"] for f in report["findings"]["changed_not_in_bundle"]]
    assert "notes.txt" in paths


def test_added_file_is_context_not_stale_by_default(snapshotted_project):
    (snapshotted_project / "src" / "newmod.py").write_text("def new_fn():\n    return 1\n")
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 0, combined(proc)
    paths = [f["path"] for f in report["findings"]["added_not_in_bundle"]]
    assert "src/newmod.py" in paths


def test_removed_bundled_file_is_stale(snapshotted_project):
    (snapshotted_project / "src" / "util.py").unlink()
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 1, combined(proc)
    paths = [f["path"] for f in report["findings"]["removed_from_project"]]
    assert "src/util.py" in paths


def test_removed_unbundled_file_keeps_fresh(snapshotted_project):
    (snapshotted_project / "notes.txt").unlink()
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 0, combined(proc)
    assert report["verdict"] == "fresh"


def test_bundle_replaced_since_snapshot_is_stale(snapshotted_project):
    manifest = snapshotted_project / ".claude_context/manifest.json"
    data = json.loads(manifest.read_text())
    data["preset"] = "generic"  # any manifest byte change = new bundle
    manifest.write_text(json.dumps(data, indent=2) + "\n")
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 1, combined(proc)
    reasons = [f.get("reason", "") for f in report["findings"]["changed_in_bundle"]]
    assert any("manifest changed" in r for r in reasons)


def test_reports_written_and_reproducible(snapshotted_project, tmp_path):
    p = snapshotted_project / "src/app.py"
    p.write_text(p.read_text() + "\n# touched body\n")
    json_out, md_out = tmp_path / "watch-report.json", tmp_path / "WATCH.md"
    proc = check(snapshotted_project, "--json-out", str(json_out),
                 "--md-out", str(md_out))
    assert proc.returncode == 1, combined(proc)
    report = json.loads(json_out.read_text())
    assert report["verdict"] == "stale"
    import hashlib
    manifest_bytes = (snapshotted_project / ".claude_context/manifest.json").read_bytes()
    assert report["bundle_manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    md = md_out.read_text()
    assert "stale" in md and "src/app.py" in md


def test_check_missing_bundle_is_clean_error(project_factory):
    project = project_factory(with_bundle=False)
    proc = check(project)
    assert proc.returncode == 2
    assert "no bundle" in combined(proc)
    assert_no_traceback(proc)


def test_check_missing_project_is_clean_error(tmp_path):
    proc = check(tmp_path / "nope")
    assert proc.returncode == 2
    assert_no_traceback(proc)


def test_check_corrupt_manifest_is_clean_error(project_factory):
    project = project_factory()
    (project / ".claude_context/manifest.json").write_text("{ not json")
    proc = check(project)
    assert proc.returncode == 2
    assert "manifest" in combined(proc)
    assert_no_traceback(proc)
