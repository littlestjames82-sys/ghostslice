"""v0.6 watch mode tests.

The watch loop's sleep/clock are injectable, so tests drive it
deterministically: a ScriptedSleep mutates the project on chosen poll
cycles (or raises KeyboardInterrupt to end the session) instead of the
tests waiting in real time.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from ghostslice.cli import main
from ghostslice.exporter import validate_bundle
from ghostslice.ledger import read_records
from ghostslice.scanner import scan
from ghostslice.watch import diff_snapshots, run_watch, snapshot_of

MAIN_V1 = "def main():\n    return 1\n"
MAIN_V2 = "def main():\n    return 1234567890  # a longer body line here\n"
UTIL_V1 = "def helper():\n    return 2\n"


def make_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "main.py").write_text(MAIN_V1, encoding="utf-8")
    (proj / "util.py").write_text(UTIL_V1, encoding="utf-8")
    return proj


class ScriptedSleep:
    """Fake sleep: run scripted actions per call; optionally Ctrl-C."""

    def __init__(self, actions=None, ki_at=None, real=0.0):
        self.actions = actions or {}
        self.ki_at = ki_at
        self.real = real
        self.calls = 0

    def __call__(self, seconds):
        self.calls += 1
        if self.ki_at is not None and self.calls >= self.ki_at:
            raise KeyboardInterrupt
        action = self.actions.get(self.calls)
        if action is not None:
            action()
        if self.real:
            time.sleep(self.real)


def test_snapshot_diff_detects_add_remove_change(tmp_path):
    proj = make_project(tmp_path)
    before = snapshot_of(scan(proj))
    (proj / "main.py").write_text(MAIN_V2, encoding="utf-8")
    (proj / "util.py").unlink()
    (proj / "new.py").write_text("X = 1\n", encoding="utf-8")
    after = snapshot_of(scan(proj))
    added, removed, changed = diff_snapshots(before, after)
    assert added == ["new.py"]
    assert removed == ["util.py"]
    assert changed == ["main.py"]


def test_watch_no_changes_exits_cleanly_on_ctrl_c(tmp_path, capsys):
    proj = make_project(tmp_path)
    summary = run_watch(proj, sleep=ScriptedSleep(ki_at=3), debounce=0)
    assert summary["events"] == 0
    assert summary["exports"] == 0
    assert summary["initial_files"] == 2
    out = capsys.readouterr().out
    assert "watching" in out
    assert "0 change event(s), 0 export(s)" in out


def test_watch_reports_modification_with_token_delta(tmp_path, capsys):
    proj = make_project(tmp_path)
    sleep = ScriptedSleep(
        actions={1: lambda: (proj / "main.py").write_text(MAIN_V2, encoding="utf-8")},
        ki_at=4)
    summary = run_watch(proj, sleep=sleep, debounce=0)
    assert summary["events"] == 1
    out = capsys.readouterr().out
    assert "change #1" in out
    assert "~ main.py" in out
    before = scan(proj)  # after-state for reference totals below
    assert "estimated tokens" in out


def test_watch_reports_added_and_removed(tmp_path, capsys):
    proj = make_project(tmp_path)

    def mutate():
        (proj / "util.py").unlink()
        (proj / "extra.py").write_text("Y = 2\n", encoding="utf-8")

    summary = run_watch(proj, sleep=ScriptedSleep(actions={1: mutate}, ki_at=4),
                        debounce=0)
    assert summary["events"] == 1
    out = capsys.readouterr().out
    assert "+ extra.py" in out
    assert "- util.py" in out


def test_watch_deleted_file_does_not_crash(tmp_path, capsys):
    proj = make_project(tmp_path)
    summary = run_watch(
        proj,
        sleep=ScriptedSleep(actions={1: lambda: (proj / "util.py").unlink()}, ki_at=3),
        debounce=0)
    assert summary["events"] == 1
    assert "- util.py" in capsys.readouterr().out


class FakeClock:
    """Deterministic monotonic clock, advanced by the fake sleep."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def test_watch_debounce_coalesces_a_burst_into_one_event(tmp_path, capsys):
    proj = make_project(tmp_path)
    versions = [
        "def main():\n    return 100\n",
        "def main():\n    return 1000  # more\n",
        "def main():\n    return 100000  # even more text here\n",
    ]
    actions = {i + 1: (lambda v=v: (proj / "main.py").write_text(v, encoding="utf-8"))
               for i, v in enumerate(versions)}
    clock = FakeClock()
    scripted = ScriptedSleep(actions=actions, ki_at=40)

    def sleep(seconds):
        clock.advance(seconds)
        scripted(seconds)

    # Fake time: writes land at t=1,2,3; the snapshot must then stay
    # quiet for 2.5 fake seconds, so the burst settles once, at t=6.
    summary = run_watch(proj, interval=1.0, debounce=2.5, sleep=sleep, clock=clock)
    assert summary["events"] == 1
    expected_final = scan(proj).total_tokens
    out = capsys.readouterr().out
    assert out.count("change #") == 1
    assert f"-> {expected_final:,}" in out  # settled totals reflect the LAST write


def test_watch_exports_never_ingest_the_previous_bundle(tmp_path):
    proj = make_project(tmp_path)
    out_dir = proj / "bundle-out"
    sleep = ScriptedSleep(
        actions={1: lambda: (proj / "main.py").write_text(MAIN_V2, encoding="utf-8"),
                 3: lambda: (proj / "util.py").write_text(
                     "def helper():\n    return 2222  # changed again\n", encoding="utf-8")},
        ki_at=6)
    summary = run_watch(proj, out=out_dir, export=True, sleep=sleep, debounce=0)
    assert summary["exports"] == 3  # initial + two settled changes
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    paths = [f["path"] for f in manifest["files"]]
    assert paths, "bundle should contain the project files"
    assert not any(p.startswith("bundle-out/") for p in paths)
    assert not (out_dir / "files" / "bundle-out").exists()


def test_watch_failed_export_is_reported_and_watching_continues(tmp_path, capsys):
    proj = make_project(tmp_path)
    blocker = proj / "blocker"
    blocker.write_text("not a directory\n", encoding="utf-8")
    out_dir = blocker / "bundle"  # mkdir under a file -> OSError
    sleep = ScriptedSleep(
        actions={1: lambda: (proj / "main.py").write_text(MAIN_V2, encoding="utf-8")},
        ki_at=4)
    summary = run_watch(proj, out=out_dir, export=True, sleep=sleep, debounce=0)
    assert summary["events"] == 1
    assert summary["exports"] == 0
    out = capsys.readouterr().out
    assert "export failed" in out
    assert "change #1" in out  # delta reporting kept working


def test_watch_warns_about_secret_in_a_changed_file(tmp_path, capsys):
    proj = make_project(tmp_path)
    # Assembled from fragments so this test file itself carries no
    # credential-shaped literal for the repo's own secret guard.
    fake_token = "gh" + "p_" + "Ab3" * 12

    def add_secret():
        (proj / "leak.py").write_text(f'TOKEN = "{fake_token}"\n', encoding="utf-8")

    summary = run_watch(proj, sleep=ScriptedSleep(actions={1: add_secret}, ki_at=4),
                        debounce=0)
    assert summary["events"] == 1
    err = capsys.readouterr().err
    assert "possible secrets in changed files" in err
    assert "leak.py" in err
    assert fake_token not in err  # values are never printed, only redacted previews


def test_watch_export_once_per_settled_change_and_ledger_matches(tmp_path):
    proj = make_project(tmp_path)
    out_dir = proj / "bundle-out"
    sleep = ScriptedSleep(
        actions={1: lambda: (proj / "main.py").write_text(MAIN_V2, encoding="utf-8")},
        ki_at=5)
    summary = run_watch(proj, out=out_dir, export=True, sleep=sleep, debounce=0)
    assert summary["events"] == 1
    # One initial export + one for the settled change. No more, even
    # though the bundle and the ledger live inside the project.
    assert summary["exports"] == 2
    assert validate_bundle(out_dir)["ok"]
    assert len(read_records(proj)) == summary["exports"]
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["total_sliced_tokens"] > 0


def test_watch_is_loop_proof_with_bundle_inside_project(tmp_path, capsys):
    proj = make_project(tmp_path)
    out_dir = proj / "mybundle"
    # No source changes at all: only the watcher's own export writes
    # (bundle files + ledger) happen. They must never become events.
    summary = run_watch(proj, out=out_dir, export=True,
                        sleep=ScriptedSleep(ki_at=10), debounce=0)
    assert summary["events"] == 0
    assert summary["exports"] == 1
    assert "change #" not in capsys.readouterr().out


def test_watch_once_detects_change_made_during_the_interval(tmp_path, capsys):
    proj = make_project(tmp_path)
    sleep = ScriptedSleep(
        actions={1: lambda: (proj / "main.py").write_text(MAIN_V2, encoding="utf-8")})
    summary = run_watch(proj, once=True, sleep=sleep)
    assert summary["events"] == 1
    assert sleep.calls == 1
    assert "~ main.py" in capsys.readouterr().out


def test_watch_once_no_change(tmp_path):
    proj = make_project(tmp_path)
    sleep = ScriptedSleep()
    summary = run_watch(proj, once=True, sleep=sleep)
    assert summary["events"] == 0
    assert sleep.calls == 1


def test_watch_max_events_stops_without_interrupt(tmp_path):
    proj = make_project(tmp_path)
    state = {"n": 0}

    def toggle():
        state["n"] += 1
        (proj / "main.py").write_text(
            f"def main():\n    return {state['n'] * 111}\n", encoding="utf-8")

    sleep = ScriptedSleep(actions={i: toggle for i in range(1, 50)})
    summary = run_watch(proj, max_events=2, sleep=sleep, debounce=0)
    assert summary["events"] == 2


def test_watch_revert_before_settle_still_counts_once_with_zero_delta(tmp_path, capsys):
    # Pinned semantics (audit #2, G4): the snapshot keys on mtime, so
    # editing a file and reverting its bytes before the debounce
    # elapses settles as exactly one "~" event with a +0 token delta.
    proj = make_project(tmp_path)
    original = (proj / "main.py").read_text(encoding="utf-8")
    clock = FakeClock()
    scripted = ScriptedSleep(
        actions={1: lambda: (proj / "main.py").write_text(MAIN_V2, encoding="utf-8"),
                 2: lambda: (proj / "main.py").write_text(original, encoding="utf-8")},
        ki_at=20)

    def sleep(seconds):
        clock.advance(seconds)
        scripted(seconds)

    summary = run_watch(proj, interval=1.0, debounce=2.5, sleep=sleep, clock=clock)
    assert summary["events"] == 1
    out = capsys.readouterr().out
    assert "~ main.py" in out
    assert "(+0)" in out


def test_run_watch_missing_root_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_watch(tmp_path / "nope", sleep=ScriptedSleep(ki_at=1))


def test_cli_watch_missing_project_exits_two(tmp_path, capsys):
    assert main(["watch", str(tmp_path / "nope"), "--once"]) == 2
    assert "no such project" in capsys.readouterr().err


def test_watch_empty_project(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    summary = run_watch(empty, sleep=ScriptedSleep(ki_at=2), debounce=0)
    assert summary["initial_files"] == 0
    assert summary["initial_tokens"] == 0
    assert summary["events"] == 0


def test_watch_survives_project_deleted_mid_watch(tmp_path, capsys):
    proj = make_project(tmp_path)
    sleep = ScriptedSleep(actions={1: lambda: shutil.rmtree(proj)}, ki_at=4)
    summary = run_watch(proj, sleep=sleep, debounce=0)
    assert summary["events"] == 0
    assert "scan failed" in capsys.readouterr().out


def test_watch_fit_is_passed_through_to_exports(tmp_path):
    proj = make_project(tmp_path)
    summary = run_watch(proj, export=True, fit=5,
                        sleep=ScriptedSleep(ki_at=3), debounce=0)
    assert summary["exports"] == 1
    manifest = json.loads(
        (proj / ".claude_context" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["fit"]["fit_tokens"] == 5


def test_scan_does_not_follow_directory_symlink_loops(tmp_path):
    proj = make_project(tmp_path)
    (proj / "loop").symlink_to(proj, target_is_directory=True)
    result = scan(proj)
    assert not any(f.path.startswith("loop/") for f in result.files)
    assert {f.path for f in result.files} == {"main.py", "util.py"}


def test_cli_watch_once_exits_zero(tmp_path, capsys):
    proj = make_project(tmp_path)
    assert main(["watch", str(proj), "--once", "--interval", "0.01"]) == 0
    out = capsys.readouterr().out
    assert "watching" in out
    assert "stopped" in out


def test_cli_watch_once_with_export_writes_default_bundle(tmp_path):
    proj = make_project(tmp_path)
    rc = main(["watch", str(proj), "--once", "--interval", "0.01", "--export"])
    assert rc == 0
    assert (proj / ".claude_context" / "manifest.json").is_file()


def test_cli_watch_rejects_bad_arguments(tmp_path, capsys):
    proj = make_project(tmp_path)
    assert main(["watch", str(proj), "--interval", "0"]) == 2
    assert main(["watch", str(proj), "--interval", "nan"]) == 2
    assert main(["watch", str(proj), "--debounce", "-1"]) == 2
    assert main(["watch", str(proj), "--max-events", "0"]) == 2
    assert main(["watch", str(proj), "--fit", "0"]) == 2
    assert main(["watch", str(proj), "-o", str(proj)]) == 2  # bundle == project root
