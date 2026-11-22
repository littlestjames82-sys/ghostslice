"""Touch-vs-edit (hash decides) and symbol staleness."""
from __future__ import annotations

import os

from conftest import check_json, combined


def test_touch_only_stays_fresh(snapshotted_project):
    # PLAN verification bar: mtime moved, bytes identical -> NOT stale.
    p = snapshotted_project / "src/app.py"
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 0, combined(proc)
    assert report["verdict"] == "fresh"
    paths = [f["path"] for f in report["findings"]["touched_only"]]
    assert "src/app.py" in paths
    assert report["findings"]["changed_in_bundle"] == []


def test_renamed_bundled_symbol_is_stale_by_symbol(snapshotted_project):
    p = snapshotted_project / "src/app.py"
    p.write_text(p.read_text().replace("def compute_total", "def compute_sum")
                 .replace("compute_total(items)", "compute_sum(items)"))
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 1, combined(proc)
    entries = [f for f in report["findings"]["stale_symbols"]
               if f["path"] == "src/app.py"]
    assert entries, report["findings"]
    assert "compute_total" in entries[0]["removed"]
    assert "compute_sum" in entries[0]["added"]


def test_deleted_bundled_symbol_is_stale(snapshotted_project):
    p = snapshotted_project / "src/util.py"
    text = p.read_text()
    start = text.index("def clamp")
    p.write_text(text[:start].rstrip() + "\n")
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 1, combined(proc)
    entries = [f for f in report["findings"]["stale_symbols"]
               if f["path"] == "src/util.py"]
    assert entries and "clamp" in entries[0]["removed"]


def test_symbol_added_to_bundled_file_reports_symbols(snapshotted_project):
    p = snapshotted_project / "src/app.py"
    p.write_text(p.read_text() + '\n\ndef brand_new():\n    return "new"\n')
    proc, report = check_json(snapshotted_project)
    # Content changed too, so stale either way; the symbol delta is named.
    entries = [f for f in report["findings"]["stale_symbols"]
               if f["path"] == "src/app.py"]
    assert entries and "brand_new" in entries[0]["added"]


def test_symbol_change_in_unbundled_file_stays_fresh(project_factory):
    # PLAN symbol bar: a symbol added to an out-of-bundle file is
    # context only and must not invalidate the bundle. Bundle here
    # ships only src/app.py, so src/util.py is out-of-bundle code.
    from conftest import make_bundle, snapshot
    project = project_factory(with_bundle=False)
    make_bundle(project, files=["src/app.py"])
    assert snapshot(project).returncode == 0
    p = project / "src/util.py"
    p.write_text(p.read_text() + '\n\ndef extra_util():\n    return "x"\n')
    proc, report = check_json(project)
    assert proc.returncode == 0, combined(proc)
    assert report["verdict"] == "fresh"
    assert all(f["path"] != "src/util.py"
               for f in report["findings"]["stale_symbols"])
    paths = [f["path"] for f in report["findings"]["changed_not_in_bundle"]]
    assert "src/util.py" in paths
