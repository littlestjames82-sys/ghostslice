"""No snapshot: manifest heuristic, never a confident fresh.

PLAN bar: with no baseline, a bundle whose files all predate the
manifest must NOT be reported fresh; definite findings (missing file,
shipped symbol gone) still make it stale; the report names the
heuristic baseline used.
"""
from __future__ import annotations

import os

from conftest import check_json, combined, make_bundle, set_mtime

OLD = 1_600_000_000.0  # 2020-09-13, before any fixture manifest
FUTURE_GEN = "2999-01-01T00:00:00+00:00"


def _old_project(project_factory, **bundle_kw):
    project = project_factory(with_bundle=False)
    for rel in ("src/app.py", "src/util.py", "notes.txt"):
        set_mtime(project / rel, OLD)
    make_bundle(project, generated_at=FUTURE_GEN, **bundle_kw)
    return project


def test_no_baseline_never_confidently_fresh(project_factory):
    project = _old_project(project_factory)
    proc, report = check_json(project)
    assert proc.returncode == 2, combined(proc)
    assert report["verdict"] == "unknown"
    assert report["baseline"] == "manifest_heuristic"
    assert report["stale"] is False


def test_no_baseline_missing_bundled_file_is_stale(project_factory):
    project = _old_project(
        project_factory, files=["src/app.py", "src/gone.py"])
    proc, report = check_json(project)
    assert proc.returncode == 1, combined(proc)
    assert report["verdict"] == "stale"
    paths = [f["path"] for f in report["findings"]["missing_bundle_file"]]
    assert "src/gone.py" in paths


def test_no_baseline_newer_source_is_flagged_not_fresh(project_factory):
    project = project_factory(with_bundle=False)
    make_bundle(project, generated_at="2000-01-01T00:00:00+00:00")
    proc, report = check_json(project)
    # No definite finding, so the verdict is unknown (never fresh),
    # and the possibly-stale files are named with the heuristic reason.
    assert proc.returncode == 2, combined(proc)
    assert report["verdict"] == "unknown"
    flagged = report["findings"]["changed_in_bundle"]
    assert flagged and all("heuristic" in f["reason"] for f in flagged)


def test_no_baseline_shipped_symbol_gone_is_stale(project_factory):
    project = _old_project(
        project_factory,
        symbols_included={"src/app.py": ["compute_total", "ghost_fn_xyz"]})
    proc, report = check_json(project)
    assert proc.returncode == 1, combined(proc)
    entries = [f for f in report["findings"]["stale_symbols"]
               if f["path"] == "src/app.py"]
    assert entries and "ghost_fn_xyz" in entries[0]["removed"]
    assert "compute_total" not in entries[0]["removed"]


def test_no_baseline_no_generated_at_uses_manifest_mtime(project_factory):
    project = project_factory(with_bundle=False)
    for rel in ("src/app.py", "src/util.py", "notes.txt"):
        set_mtime(project / rel, OLD)
    bundle = make_bundle(project)
    import json
    manifest_path = bundle / "manifest.json"
    data = json.loads(manifest_path.read_text())
    data["generated_at"] = None
    manifest_path.write_text(json.dumps(data, indent=2) + "\n")
    # Manifest file itself is now the newest thing; sources predate it.
    proc, report = check_json(project)
    assert proc.returncode == 2, combined(proc)
    assert report["verdict"] == "unknown"
    assert report["baseline"] == "manifest_heuristic"
