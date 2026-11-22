"""Harden pass (Oct 18, 2026): bugs demonstrated before the fix.

- A manifest `symbols_included` entry that was not a string (e.g. a
  dict) crashed the heuristic check with `TypeError: unhashable`.
- A snapshot whose `symbols` list contained a non-string crashed
  `check` the same way instead of the clean exit 2 corrupt-snapshot
  handling added in polish pass 1.
- Snapshot mode never reported a bundled file that was missing on
  disk AND absent from the baseline (bundle created after the
  snapshot): the verdict was a confident, wrong `fresh`.
- `watch --interval -1` / `nan` crashed with a ValueError traceback
  from time.sleep; `inf` would have slept forever; `--max-polls 0`
  silently ran one poll.
- Report/snapshot writes to a bad path (output is a directory,
  parent missing) crashed with an OSError traceback.
- A timezone-less manifest `generated_at` was parsed in local time,
  so the heuristic comparison depended on the machine's timezone.
"""
from __future__ import annotations

import json
import os
import sys
import time

import pytest

from conftest import (WATCH_SRC, assert_no_traceback, check, check_json,
                      combined, make_bundle, snapshot, watch)

if str(WATCH_SRC) not in sys.path:
    sys.path.insert(0, str(WATCH_SRC))

from ghostwatch import core  # noqa: E402
from ghostwatch.cli import build_parser  # noqa: E402


# ---------- corrupt symbols never crash ----------

def test_manifest_non_string_symbol_is_filtered_not_a_crash(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(json.dumps({
        "generated_at": "2999-01-01T00:00:00+00:00",
        "files": [{"path": "src/app.py", "mode": "full",
                   "symbols_included": ["compute_total", {"x": 1}, 42, None]}],
    }))
    info = core.read_bundle_info(bundle)
    assert info["files"][0]["symbols_included"] == ["compute_total"]


def test_check_with_garbage_manifest_symbols_is_clean(project_factory):
    project = project_factory()
    manifest_path = project / ".claude_context" / "manifest.json"
    data = json.loads(manifest_path.read_text())
    data["files"][0]["symbols_included"] = ["compute_total", {"x": 1}]
    manifest_path.write_text(json.dumps(data, indent=2) + "\n")
    proc, report = check_json(project)  # heuristic path uses symbols_included
    assert proc.returncode == 2, combined(proc)  # unknown, no baseline
    assert report["verdict"] == "unknown"
    assert_no_traceback(proc)


def test_snapshot_non_string_symbol_is_clean_exit_2(snapshotted_project):
    snap_path = snapshotted_project / ".ghostwatch" / "snapshot.json"
    snap = json.loads(snap_path.read_text())
    snap["files"]["src/app.py"]["symbols"] = ["compute_total", {"x": 1}]
    snap_path.write_text(json.dumps(snap))
    proc = check(snapshotted_project)
    assert proc.returncode == 2, combined(proc)
    assert "symbols" in combined(proc)
    assert_no_traceback(proc)


# ---------- snapshot mode: missing bundled file ----------

def test_snapshot_mode_missing_bundle_file_never_baselined_is_stale(project_factory):
    # Snapshot taken project-only; the bundle is created afterwards
    # and lists a file that does not exist on disk.
    project = project_factory(with_bundle=False)
    assert snapshot(project).returncode == 0
    make_bundle(project, files=["src/app.py", "src/gone.py"])
    proc, report = check_json(project)
    assert proc.returncode == 1, combined(proc)
    assert report["verdict"] == "stale"
    paths = [f["path"] for f in report["findings"]["missing_bundle_file"]]
    assert "src/gone.py" in paths


# ---------- watch argument validation ----------

@pytest.mark.parametrize("bad", ["-1", "nan", "inf", "abc"])
def test_watch_interval_rejected_cleanly(project_factory, bad):
    project = project_factory()
    proc = watch(project, "--interval", bad, "--max-polls", "3")
    assert proc.returncode == 2, combined(proc)
    assert "interval" in combined(proc)
    assert_no_traceback(proc)


def test_watch_max_polls_zero_rejected_cleanly(project_factory):
    project = project_factory()
    proc = watch(project, "--interval", "0.05", "--max-polls", "0")
    assert proc.returncode == 2, combined(proc)
    assert "max-polls" in combined(proc)
    assert_no_traceback(proc)


def test_parser_rejects_non_finite_interval_without_subprocess():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["watch", "p", "--interval", "inf"])


# ---------- write failures are clean errors, missing parents created ----------

def test_snapshot_output_is_a_directory_is_clean_exit_2(project_factory, tmp_path):
    project = project_factory()
    proc = snapshot(project, "-o", str(tmp_path))  # tmp_path is a directory
    assert proc.returncode == 2, combined(proc)
    assert_no_traceback(proc)


def test_check_json_out_creates_missing_parent(snapshotted_project, tmp_path):
    out = tmp_path / "new-dir" / "watch-report.json"
    proc = check(snapshotted_project, "--json-out", str(out))
    assert proc.returncode == 0, combined(proc)
    assert json.loads(out.read_text())["verdict"] == "fresh"


def test_check_json_out_is_a_directory_is_clean_exit_2(snapshotted_project, tmp_path):
    proc = check(snapshotted_project, "--json-out", str(tmp_path))
    assert proc.returncode == 2, combined(proc)
    assert_no_traceback(proc)


# ---------- generated_at parsing is timezone-independent ----------

def test_parse_ts_naive_generated_at_is_utc_not_local():
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    try:
        assert core._parse_ts("2020-01-01T00:00:00") == \
            core._parse_ts("2020-01-01T00:00:00+00:00") == 1577836800.0
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()
