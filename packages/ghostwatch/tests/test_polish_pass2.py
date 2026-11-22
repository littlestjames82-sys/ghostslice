"""Polish pass 2 regressions (Oct 14, 2026): the stat pre-filter.

v0.1 re-read and re-hashed every file on every check (300-file tree:
~0.3-1.2s per check, all of it hashing). `check` now passes its
baseline into the snapshot walk: a file whose size AND mtime_ns are
both unchanged reuses the baseline hash/symbols. These tests pin that
the verdicts and findings are identical to the full-hash behaviour:
- unchanged tree: fresh, everything reused, nothing re-hashed;
- mtime moved only: still hashed (stat changed), still touched_only;
- content changed with the ORIGINAL mtime restored but a different
  size: size is part of the filter, so it is re-hashed and caught.
"""
from __future__ import annotations

import json

from conftest import check_json, load_default_snapshot, set_mtime


def test_prefilter_reuses_unchanged_files(snapshotted_project):
    project = snapshotted_project
    proc, rep = check_json(project)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert rep["verdict"] == "fresh"
    assert rep["files_reused"] == 3       # app.py, util.py, notes.txt
    assert rep["files_hashed"] == 0


def test_prefilter_rehashes_when_mtime_moves(snapshotted_project):
    project = snapshotted_project
    target = project / "src" / "util.py"
    st = target.stat()
    set_mtime(target, st.st_mtime + 5)
    proc, rep = check_json(project)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert rep["verdict"] == "fresh"
    assert [f["path"] for f in rep["findings"]["touched_only"]] == ["src/util.py"]
    assert rep["files_hashed"] == 1
    assert rep["files_reused"] == 2


def test_prefilter_size_change_with_restored_mtime_is_caught(snapshotted_project):
    project = snapshotted_project
    snap = load_default_snapshot(project)
    base_mtime_ns = snap["files"]["src/app.py"]["mtime_ns"]
    target = project / "src" / "app.py"
    target.write_text(target.read_text() + "\n# a longer file now\n")
    # Restore the exact baseline mtime: only the size half of the
    # pre-filter can save this from being wrongly reused.
    import os
    os.utime(target, ns=(base_mtime_ns, base_mtime_ns))
    proc, rep = check_json(project)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert rep["verdict"] == "stale"
    assert "src/app.py" in [f["path"] for f in rep["findings"]["changed_in_bundle"]]
    assert rep["files_hashed"] >= 1
