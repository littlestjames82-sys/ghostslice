"""Freshness analysis (deepen): score, drift, age, churn, size delta.

Reporting only: the analysis must never change the verdict, must
never give a confident score on the heuristic (no-baseline) path,
and must never mutate/refresh a bundle.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from conftest import check, check_json, combined, load_default_snapshot, make_bundle, snapshot


def test_fresh_bundle_scores_100_severity_none(snapshotted_project):
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 0, combined(proc)
    fr = report["freshness"]
    assert fr["staleness_score"] == 100
    assert fr["severity"] == "none"
    assert fr["drift"]["bundle_files_total"] == 2
    assert fr["drift"]["bundle_files_stale"] == 0
    assert fr["drift"]["bundle_files_fresh"] == 2
    assert fr["drift"]["bundle_drift_ratio"] == 0.0
    assert fr["stale_paths"] == []
    assert fr["symbol_churn"]["symbols_removed"] == 0
    assert "safe to reuse" in fr["recommendation"]


def test_one_of_two_bundled_files_stale_scores_50(snapshotted_project):
    p = snapshotted_project / "src/app.py"
    p.write_text(p.read_text() + "\n# drift\n")
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 1, combined(proc)
    fr = report["freshness"]
    assert fr["staleness_score"] == 50
    assert fr["severity"] == "medium"
    assert fr["drift"]["bundle_files_stale"] == 1
    assert fr["drift"]["bundle_drift_ratio"] == 0.5
    assert fr["stale_paths"] == ["src/app.py"]
    assert "Re-export recommended" in fr["recommendation"]


def test_removed_bundled_file_counts_in_drift_and_size_delta(snapshotted_project):
    (snapshotted_project / "src/util.py").unlink()
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 1, combined(proc)
    fr = report["freshness"]
    assert "src/util.py" in fr["stale_paths"]
    assert fr["staleness_score"] == 50
    removed = [f for f in report["findings"]["removed_from_project"]
               if f["path"] == "src/util.py"]
    assert removed and removed[0]["size_before"] > 0
    assert removed[0]["size_after"] is None
    assert removed[0]["size_delta"] == -removed[0]["size_before"]


def test_changed_file_carries_size_delta(snapshotted_project):
    p = snapshotted_project / "src/app.py"
    before = p.stat().st_size
    p.write_text(p.read_text() + "x" * 10 + "\n")
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 1, combined(proc)
    changed = [f for f in report["findings"]["changed_in_bundle"]
               if f["path"] == "src/app.py"]
    assert changed and changed[0]["size_before"] == before
    assert changed[0]["size_delta"] == changed[0]["size_after"] - before
    assert changed[0]["size_delta"] > 0


def test_symbol_removal_counts_churn_and_stale_path(snapshotted_project):
    p = snapshotted_project / "src/util.py"
    text = p.read_text()
    p.write_text(text[: text.index("def clamp")].rstrip() + "\n")
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 1, combined(proc)
    fr = report["freshness"]
    assert fr["symbol_churn"]["symbols_removed"] >= 1
    assert fr["symbol_churn"]["files_affected"] >= 1
    assert "src/util.py" in fr["stale_paths"]
    assert "symbol" in fr["recommendation"]


def test_context_only_change_does_not_lower_score(snapshotted_project):
    p = snapshotted_project / "notes.txt"
    p.write_text(p.read_text() + "Extra line.\n")
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 0, combined(proc)
    fr = report["freshness"]
    assert fr["staleness_score"] == 100
    assert fr["drift"]["context_changes"] >= 1
    assert fr["stale_paths"] == []


def test_touched_only_does_not_lower_score(snapshotted_project):
    import os
    p = snapshotted_project / "src/app.py"
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 0, combined(proc)
    assert report["freshness"]["staleness_score"] == 100
    assert report["freshness"]["drift"]["touched_only"] == 1


def test_heuristic_baseline_has_no_confident_score(project_factory):
    # No snapshot: score must stay None / unknown, never a number that
    # looks confident (hard rule: never confident without a baseline).
    project = project_factory()
    proc, report = check_json(project)
    assert report["baseline"] == "manifest_heuristic"
    fr = report["freshness"]
    assert fr["staleness_score"] is None
    assert fr["severity"] == "unknown"
    assert "snapshot" in fr["recommendation"]


def test_bundle_age_uses_manifest_generated_at(project_factory):
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    project = project_factory(with_bundle=False)
    make_bundle(project, generated_at=old)
    assert snapshot(project).returncode == 0
    proc, report = check_json(project)
    assert proc.returncode == 0, combined(proc)
    age = report["freshness"]["bundle_age_seconds"]
    assert age is not None and age >= 10 * 86400 - 60
    # Snapshot was just taken, so its age is small.
    snap_age = report["freshness"]["snapshot_age_seconds"]
    assert snap_age is not None and snap_age < 120


def test_snapshot_age_uses_snapshot_created_at(snapshotted_project):
    snap = load_default_snapshot(snapshotted_project)
    assert snap.get("created_at")
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 0, combined(proc)
    assert report["freshness"]["snapshot_age_seconds"] is not None


def test_bundle_replaced_caps_score_and_flags(snapshotted_project):
    manifest = snapshotted_project / ".claude_context/manifest.json"
    data = json.loads(manifest.read_text())
    data["preset"] = "generic"
    manifest.write_text(json.dumps(data, indent=2) + "\n")
    proc, report = check_json(snapshotted_project)
    assert proc.returncode == 1, combined(proc)
    fr = report["freshness"]
    assert fr["bundle_replaced"] is True
    assert fr["staleness_score"] is not None and fr["staleness_score"] <= 50


def test_markdown_report_includes_freshness_section(snapshotted_project, tmp_path):
    p = snapshotted_project / "src/app.py"
    p.write_text(p.read_text() + "\n# drift\n")
    md_out = tmp_path / "WATCH.md"
    proc = check(snapshotted_project, "--md-out", str(md_out))
    assert proc.returncode == 1, combined(proc)
    md = md_out.read_text()
    assert "Freshness analysis" in md
    assert "Staleness score" in md
    assert "Symbol churn" in md
    assert "Recommendation" in md


def test_compute_freshness_and_format_age_units():
    from ghostwatch.core import compute_freshness, format_age
    assert format_age(None) == "unknown"
    assert format_age(45) == "45s"
    assert format_age(125) == "2m 5s"
    assert format_age(90000).startswith("1d")
    fr = compute_freshness(
        verdict="fresh", baseline="snapshot",
        findings={"changed_in_bundle": [], "stale_symbols": [],
                  "changed_not_in_bundle": [], "added_not_in_bundle": [],
                  "touched_only": [], "removed_from_project": [],
                  "missing_bundle_file": []},
        bundle_file_count=0, checked_at="2026-10-14T00:00:00+00:00")
    assert fr["staleness_score"] == 100 and fr["severity"] == "none"
    # Clock skew: future reference yields None age, not negative.
    fr2 = compute_freshness(
        verdict="unknown", baseline="manifest_heuristic",
        findings={}, bundle_file_count=2,
        bundle_generated_at="2999-01-01T00:00:00+00:00",
        checked_at="2026-10-14T00:00:00+00:00")
    assert fr2["bundle_age_seconds"] is None
    assert fr2["staleness_score"] is None


def test_freshness_does_not_mutate_bundle(snapshotted_project):
    manifest = snapshotted_project / ".claude_context/manifest.json"
    before = manifest.read_bytes()
    proc, _ = check_json(snapshotted_project)
    assert proc.returncode == 0, combined(proc)
    assert manifest.read_bytes() == before
