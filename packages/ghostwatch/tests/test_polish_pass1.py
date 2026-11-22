"""Polish pass 1 regressions (Oct 14, 2026): gitignore-lite git
semantics, corrupt-snapshot clean errors, watch output flushing.

Each test pins a bug demonstrated before the fix:
- '/notes.txt' (root-anchored) also ignored src/notes.txt.
- 'logs/' (dir-only) also ignored a FILE named logs.
- 'docs/*.md' matched docs/sub/b.md ('*' crossed '/').
- A snapshot whose per-file entry was not an object crashed check
  with an AttributeError traceback instead of a clean exit 2.
- Watch prints were block-buffered when stdout was redirected, so
  nothing was readable (and on SIGTERM, nothing survived) until exit.
"""
from __future__ import annotations

import json
import signal
import subprocess
import sys
import time

from conftest import (WATCH_SRC, assert_no_traceback, base_env, check,
                      combined, load_default_snapshot, snapshot)


# ---------- gitignore-lite semantics ----------

def test_gitignore_anchored_pattern_only_matches_root(project_factory):
    project = project_factory()
    (project / ".gitignore").write_text("/notes.txt\n")
    (project / "src" / "notes.txt").write_text("nested, must survive\n")
    assert snapshot(project).returncode == 0
    files = load_default_snapshot(project)["files"]
    assert "notes.txt" not in files          # root file: anchored hit
    assert "src/notes.txt" in files          # nested file: NOT ignored


def test_gitignore_dir_only_pattern_spares_same_named_file(project_factory):
    project = project_factory()
    (project / ".gitignore").write_text("logs/\n")
    (project / "logs").write_text("a file named logs, must survive\n")
    (project / "src" / "logs").mkdir()
    (project / "src" / "logs" / "x.py").write_text("def x():\n    pass\n")
    assert snapshot(project).returncode == 0
    files = load_default_snapshot(project)["files"]
    assert "logs" in files                   # the file is not a directory
    assert "src/logs/x.py" not in files      # the directory is ignored


def test_gitignore_mid_slash_glob_does_not_cross_directories(project_factory):
    project = project_factory()
    (project / ".gitignore").write_text("docs/*.md\n")
    (project / "docs").mkdir()
    (project / "docs" / "a.md").write_text("ignored\n")
    (project / "docs" / "sub").mkdir()
    (project / "docs" / "sub" / "b.md").write_text("must survive\n")
    assert snapshot(project).returncode == 0
    files = load_default_snapshot(project)["files"]
    assert "docs/a.md" not in files
    assert "docs/sub/b.md" in files


def test_gitignore_default_dirs_do_not_eat_same_named_file(project_factory):
    project = project_factory()
    (project / "build").write_text("a file named build, must survive\n")
    assert snapshot(project).returncode == 0
    assert "build" in load_default_snapshot(project)["files"]


# ---------- corrupt snapshot handling ----------

def test_corrupt_snapshot_entry_is_clean_exit_2(snapshotted_project):
    project = snapshotted_project
    snap_path = project / ".ghostwatch" / "snapshot.json"
    snap = json.loads(snap_path.read_text())
    snap["files"]["src/app.py"] = "junk-not-an-object"
    snap_path.write_text(json.dumps(snap))
    proc = check(project)
    assert proc.returncode == 2, combined(proc)
    assert_no_traceback(proc)
    assert "src/app.py" in combined(proc)


def test_corrupt_snapshot_bundle_field_is_clean_exit_2(snapshotted_project):
    project = snapshotted_project
    snap_path = project / ".ghostwatch" / "snapshot.json"
    snap = json.loads(snap_path.read_text())
    snap["bundle"] = "junk-not-an-object"
    snap_path.write_text(json.dumps(snap))
    proc = check(project)
    assert proc.returncode == 2, combined(proc)
    assert_no_traceback(proc)


# ---------- watch flushing ----------

def test_watch_output_is_readable_while_running(snapshotted_project, tmp_path):
    project = snapshotted_project
    out_path = tmp_path / "watch.out"
    with open(out_path, "w") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "ghostwatch", "watch", str(project),
             "--interval", "0.2"],
            stdout=out, stderr=subprocess.STDOUT, env=base_env())
        try:
            seen = ""
            deadline = time.time() + 10
            while time.time() < deadline and proc.poll() is None:
                seen = out_path.read_text(errors="replace")
                if "watching" in seen and "verdict:" in seen:
                    break
                time.sleep(0.1)
            assert proc.poll() is None, "watch exited early: " + seen
            assert "watching" in seen, f"header not flushed while running: {seen!r}"
            assert "verdict:" in seen, f"verdict not flushed while running: {seen!r}"
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
            proc.wait(timeout=10)
    final = out_path.read_text(errors="replace")
    assert "stopped" in final
    assert proc.returncode == 0
