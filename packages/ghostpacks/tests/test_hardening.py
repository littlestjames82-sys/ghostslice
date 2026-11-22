"""Hardening regression tests (2026-10-18 improvement pass).

Each test pins a bug found by auditing the v0.1 code against the
PLAN.md hard rules:

- hidden (dot-prefixed) script/executable files slipped past the
  data-only lint sweep because dotfiles were skipped wholesale;
- a Bench report could live OUTSIDE the pack (``..`` traversal or a
  symlink), be unreadable garbage, carry a different score than the
  manifest claims, or back a non-numeric / negative "score", and the
  pack still linted clean and showed as scored;
- manifest dates only had to *look* like YYYY-MM-DD (2026-02-30
  passed);
- `remove` trusted the lockfile's recorded backup path blindly, so a
  tampered lockfile could point it at an arbitrary file outside the
  project, which was copied over the profile and then deleted;
- a lockfile whose 'packs' entries were not objects crashed merge
  with an AttributeError traceback instead of a clean error;
- a confirmation prompt on a closed stdin crashed with an EOFError
  traceback instead of counting as "no";
- `init-pack -o <a file>` crashed with NotADirectoryError.

CLI-level where the suite's helpers allow it, so the user-facing
behaviour (exit codes, no tracebacks) is what is pinned.
"""
from __future__ import annotations

import json
import os
import stat

import pytest

from conftest import combined, lint, merge, remove, run_ghostpacks


# ---------------------------------------------------------------- lint: hidden files

def test_hidden_script_file_fails_lint(pack_factory):
    pack = pack_factory(extra_files={".evil.py": "import os\n"})
    proc = lint(pack)
    out = combined(proc)
    assert proc.returncode != 0, "lint accepted a hidden script file"
    assert ".evil.py" in out, out


def test_hidden_executable_file_fails_lint(pack_factory):
    pack = pack_factory(extra_files={".hidden.txt": "innocent text\n"})
    target = pack / ".hidden.txt"
    target.chmod(target.stat().st_mode | stat.S_IXUSR)
    proc = lint(pack)
    assert proc.returncode != 0, "lint accepted a hidden executable file"
    assert ".hidden.txt" in combined(proc)


def test_symlinked_file_in_pack_fails_lint(pack_factory, tmp_path):
    pack = pack_factory()
    outside = tmp_path / "outside.md"
    outside.write_text("# elsewhere\n")
    try:
        (pack / "linked.md").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not available")
    proc = lint(pack)
    assert proc.returncode != 0, "lint accepted a symlink out of the pack"
    assert "linked.md" in combined(proc)


def test_nonregular_file_in_pack_fails_lint(pack_factory):
    pack = pack_factory()
    try:
        os.mkfifo(pack / "data.json")
    except (OSError, AttributeError):
        pytest.skip("mkfifo not available")
    proc = lint(pack)
    assert proc.returncode != 0, "lint accepted (or hung on) a fifo in a pack"
    assert "data.json" in combined(proc)


# ---------------------------------------------------------------- score honesty

def test_bench_report_outside_pack_fails_lint(pack_factory, tmp_path):
    # pack_factory puts packs under tmp_path/packs/<id>, so
    # ../../outside.json is a real file outside the pack folder.
    (tmp_path / "outside.json").write_text(json.dumps({"score": 42.0}))
    pack = pack_factory(bench={"score": 42.0, "report": "../../outside.json"})
    proc = lint(pack)
    out = combined(proc)
    assert proc.returncode != 0, (
        "lint accepted a Bench report outside the pack folder")
    assert "bench" in out.lower(), out


def test_bench_report_symlink_to_outside_fails_lint(pack_factory, tmp_path):
    outside = tmp_path / "real-report.json"
    outside.write_text(json.dumps({"score": 42.0}))
    pack = pack_factory(bench={"score": 42.0, "report": "bench-report.json"})
    try:
        (pack / "bench-report.json").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not available")
    proc = lint(pack)
    assert proc.returncode != 0, (
        "lint accepted a Bench report that is a symlink out of the pack")


def test_garbage_bench_report_fails_lint(pack_factory):
    pack = pack_factory(bench={"score": 42.0, "report": "bench-report.json"})
    (pack / "bench-report.json").write_text("not json at all\n")
    proc = lint(pack)
    assert proc.returncode != 0, (
        "lint accepted a claimed score backed by an unreadable report")
    assert "bench" in combined(proc).lower()


def test_bench_report_score_mismatch_fails_lint(pack_factory):
    pack = pack_factory(bench={"score": 42.0, "report": "bench-report.json"},
                        write_bench_report=True)
    (pack / "bench-report.json").write_text(json.dumps({"score": 1.0}))
    proc = lint(pack)
    assert proc.returncode != 0, (
        "lint accepted a claimed score that its own Bench report "
        "contradicts")


@pytest.mark.parametrize("bad_score", ["42", True, -5, {"score": 42}])
def test_non_numeric_or_negative_bench_score_fails_lint(pack_factory, bad_score):
    pack_id = f"badscore-{abs(hash(repr(bad_score))) % 100000}"
    pack = pack_factory(pack_id=pack_id,
                        bench={"score": bad_score, "report": "bench-report.json"},
                        write_bench_report=True)
    proc = lint(pack)
    assert proc.returncode != 0, (
        f"lint accepted a Bench score of {bad_score!r}")


def test_scored_pack_whose_report_agrees_still_passes(pack_factory):
    # Guard against overreach: the honest shape from the original
    # suite must keep passing.
    pack = pack_factory(bench={"score": 42.0, "report": "bench-report.json"},
                        write_bench_report=True)
    proc = lint(pack)
    assert proc.returncode == 0, combined(proc)


# ---------------------------------------------------------------- manifest dates

def test_impossible_calendar_date_fails_lint(pack_factory):
    pack = pack_factory(manifest_overrides={"date": "2026-02-30"})
    proc = lint(pack)
    assert proc.returncode != 0, "lint accepted the date 2026-02-30"
    assert "date" in combined(proc).lower()


# ---------------------------------------------------------------- remove: backup path

def test_remove_with_tampered_backup_path_deletes_nothing(
        pack_factory, project_factory, tmp_path):
    pack = pack_factory()
    project = project_factory()
    proc = merge(pack, project)
    assert proc.returncode == 0, combined(proc)
    profile_before = (project / ".ghostslice.json").read_bytes()

    victim = tmp_path / "victim.txt"
    victim.write_text("precious, do not delete\n")
    lockfile = project / ".ghostslice-packs.json"
    lock = json.loads(lockfile.read_text())
    lock["packs"][0]["backup"] = "../victim.txt"
    lockfile.write_text(json.dumps(lock))

    proc = remove("demo-python", project)
    out = combined(proc)
    assert proc.returncode != 0, (
        "remove honoured a backup path pointing outside the project")
    assert "Traceback" not in out, out
    assert victim.read_text() == "precious, do not delete\n", (
        "remove deleted a file outside the project's backup folder")
    assert (project / ".ghostslice.json").read_bytes() == profile_before, (
        "remove overwrote the profile from an outside file")


# ---------------------------------------------------------------- error handling

def test_lockfile_with_nonobject_entry_fails_cleanly(
        pack_factory, project_factory):
    project = project_factory()
    (project / ".ghostslice-packs.json").write_text(
        json.dumps({"packs": ["oops"]}))
    pack = pack_factory()
    proc = merge(pack, project)
    out = combined(proc)
    assert proc.returncode != 0, "merge accepted a corrupt lockfile"
    assert "Traceback" not in out, out
    assert "lockfile" in out.lower(), out


def test_merge_with_closed_stdin_declines_cleanly(
        pack_factory, project_factory):
    pack = pack_factory()
    project = project_factory()
    before = (project / ".ghostslice.json").read_bytes()
    proc = run_ghostpacks("merge", str(pack), str(project), stdin="")
    out = combined(proc)
    assert proc.returncode != 0, "merge proceeded with no possible consent"
    assert "Traceback" not in out, out
    assert (project / ".ghostslice.json").read_bytes() == before, (
        "merge wrote after stdin closed at the confirmation prompt")


def test_init_pack_out_path_that_is_a_file_fails_cleanly(
        project_factory, tmp_path):
    project = project_factory()
    outfile = tmp_path / "a-file"
    outfile.write_text("already here\n")
    proc = run_ghostpacks("init-pack", str(project), "-o", str(outfile))
    out = combined(proc)
    assert proc.returncode != 0, "init-pack accepted a file as its out folder"
    assert "Traceback" not in out, out
    assert outfile.read_text() == "already here\n"
