"""Polling watch: bounded runs, return codes, settled verdict changes."""
from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

from conftest import (WATCH_SRC, assert_no_traceback, base_env, combined,
                      watch)


def test_watch_bounded_fresh_exits_zero(snapshotted_project):
    proc = watch(snapshotted_project, "--interval", "0.05", "--max-polls", "3")
    assert proc.returncode == 0, combined(proc)
    out = combined(proc)
    assert "watching" in out and "stopped" in out
    assert "stale seen: False" in out
    assert_no_traceback(proc)


def test_watch_bounded_stale_exits_one(snapshotted_project):
    p = snapshotted_project / "src/app.py"
    p.write_text(p.read_text() + "\n# drift\n")
    proc = watch(snapshotted_project, "--interval", "0.05", "--max-polls", "3")
    assert proc.returncode == 1, combined(proc)
    out = combined(proc)
    assert "verdict: stale" in out  # printed once the verdict settles (2 polls)
    assert "stale seen: True" in out


def test_watch_missing_project_is_clean_error(tmp_path):
    proc = watch(tmp_path / "nope", "--interval", "0.05", "--max-polls", "1")
    assert proc.returncode == 2
    assert_no_traceback(proc)


def test_watch_reports_verdict_change_then_ctrl_c(snapshotted_project, tmp_path):
    """Live loop: start fresh, edit a bundled file, the settled stale
    verdict is printed; SIGINT (Ctrl-C) exits cleanly with code 1."""
    outfile = tmp_path / "watch-out.txt"
    env = base_env()
    with outfile.open("w") as fh:
        proc = subprocess.Popen(
            [sys.executable, "-m", "ghostwatch", "watch",
             str(snapshotted_project), "--interval", "0.1"],
            stdout=fh, stderr=subprocess.STDOUT, env=env)
        try:
            time.sleep(0.6)  # let the fresh verdict settle/print
            p = snapshotted_project / "src/app.py"
            p.write_text(p.read_text() + "\n# live drift\n")
            # NOTE: the CLI's prints are block-buffered when stdout is
            # a file, so the output only becomes readable on exit.
            # Give the loop ample polls to settle the stale verdict,
            # then Ctrl-C and read the flushed output.
            time.sleep(2.0)
            proc.send_signal(signal.SIGINT)
            rc = proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
    assert rc == 1, outfile.read_text()
    assert "verdict: stale" in outfile.read_text()
    assert "stopped" in outfile.read_text()
    assert "Traceback" not in outfile.read_text()
