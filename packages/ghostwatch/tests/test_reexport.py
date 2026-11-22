"""--reexport delegation: graceful failure when GhostSlice is absent,
failure when it errors, success via a fake GhostSlice executable.

PLAN bar: --reexport on a stale bundle with no GhostSlice available
must exit 1 with `reexport: unavailable`, no traceback, no bundle
written. Watch never slices anything itself.
"""
from __future__ import annotations

import json

from conftest import (FAKE_FAIL, assert_no_traceback, check, check_json,
                      combined, install_fake_ghostslice, load_default_snapshot,
                      no_ghostslice_env)


def _make_stale(project):
    p = project / "src/app.py"
    p.write_text(p.read_text() + "\n# drift makes this bundle stale\n")


def test_reexport_unavailable_when_ghostslice_absent(snapshotted_project):
    _make_stale(snapshotted_project)
    manifest_before = (snapshotted_project / ".claude_context/manifest.json").read_bytes()
    proc, report = check_json(snapshotted_project, "--reexport",
                              env_extra=no_ghostslice_env())
    assert proc.returncode == 1, combined(proc)
    assert report["verdict"] == "stale"
    assert report["reexport"]["status"] == "unavailable"
    assert report["reexport"]["reason"]
    assert_no_traceback(proc)
    # No bundle was written by Watch itself.
    assert (snapshotted_project / ".claude_context/manifest.json").read_bytes() == manifest_before


def test_reexport_unavailable_text_summary(snapshotted_project):
    _make_stale(snapshotted_project)
    proc = check(snapshotted_project, "--reexport",
                 env_extra=no_ghostslice_env())
    assert proc.returncode == 1, combined(proc)
    assert "reexport: unavailable" in combined(proc)
    assert_no_traceback(proc)


def test_reexport_failed_when_ghostslice_errors(snapshotted_project, tmp_path):
    _make_stale(snapshotted_project)
    env = install_fake_ghostslice(tmp_path, script=FAKE_FAIL)
    proc, report = check_json(snapshotted_project, "--reexport", env_extra=env)
    assert proc.returncode == 1, combined(proc)
    assert report["reexport"]["status"] == "failed"
    assert_no_traceback(proc)


def test_reexport_success_refreshes_snapshot(snapshotted_project, tmp_path):
    _make_stale(snapshotted_project)
    env = install_fake_ghostslice(tmp_path)  # FAKE_OK by default
    proc, report = check_json(snapshotted_project, "--reexport", env_extra=env)
    # By design (cli.py) THIS run still reports the stale verdict it was
    # asked about; the re-export is recorded on the report.
    assert proc.returncode == 1, combined(proc)
    assert report["reexport"]["status"] == "ok"
    assert report["reexport"].get("snapshot_refreshed") is True
    # The refreshed snapshot now matches the newly written bundle...
    import hashlib
    new_manifest = (snapshotted_project / ".claude_context/manifest.json").read_bytes()
    snap = load_default_snapshot(snapshotted_project)
    assert snap["bundle"]["manifest_sha256"] == hashlib.sha256(new_manifest).hexdigest()
    # ...and a plain check against the refreshed baseline is fresh.
    proc2, report2 = check_json(snapshotted_project)
    assert proc2.returncode == 0, combined(proc2)
    assert report2["verdict"] == "fresh"


def test_reexport_not_attempted_when_fresh(snapshotted_project):
    proc, report = check_json(snapshotted_project, "--reexport",
                              env_extra=no_ghostslice_env())
    assert proc.returncode == 0, combined(proc)
    assert report["reexport"] is None
