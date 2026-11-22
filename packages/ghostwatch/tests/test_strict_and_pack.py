"""--strict-added and the Pack verdict mirror."""
from __future__ import annotations

from conftest import (check_json, combined, make_bundle, snapshot)


def test_strict_added_makes_added_bundled_file_stale(project_factory):
    # Baseline snapshot taken project-only (no bundle yet). Then a new
    # file appears AND is included in a bundle created afterwards.
    project = project_factory(with_bundle=False)
    assert snapshot(project).returncode == 0
    (project / "src" / "late.py").write_text("def late_fn():\n    return 7\n")
    make_bundle(project, files=["src/app.py", "src/late.py"])

    proc, report = check_json(project)
    assert proc.returncode == 0, combined(proc)
    assert report["verdict"] == "fresh"
    assert "src/late.py" in [
        f["path"] for f in report["findings"]["added_not_in_bundle"]]

    proc, report = check_json(project, "--strict-added")
    assert proc.returncode == 1, combined(proc)
    assert report["verdict"] == "stale"
    assert report["strict_added"] is True


def test_pack_verdict_mirrors_bundle_verdict(snapshotted_project, tmp_path):
    # A Pack directory that carries a bundle manifest is checked with
    # --bundle and gets one consistent answer: pack_stale mirrors stale.
    import shutil
    pack = tmp_path / "my-pack-bundle"
    shutil.copytree(snapshotted_project / ".claude_context", pack)

    proc, report = check_json(snapshotted_project, "--bundle", str(pack))
    assert proc.returncode == 0, combined(proc)
    assert report["pack_stale"] is False

    p = snapshotted_project / "src/app.py"
    p.write_text(p.read_text() + "\n# drift\n")
    proc, report = check_json(snapshotted_project, "--bundle", str(pack))
    assert proc.returncode == 1, combined(proc)
    assert report["verdict"] == "stale" and report["pack_stale"] is True


def test_pack_without_manifest_is_clean_error(snapshotted_project, tmp_path):
    from conftest import assert_no_traceback, check
    empty = tmp_path / "empty-pack"
    empty.mkdir()
    proc = check(snapshotted_project, "--bundle", str(empty))
    assert proc.returncode == 2
    assert "manifest" in combined(proc)
    assert_no_traceback(proc)
