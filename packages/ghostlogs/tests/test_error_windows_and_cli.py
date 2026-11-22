"""Error windows: the pack carries the first ERROR with its context
(the lines around it), not just the error line alone. Plus basic CLI
contract: missing input fails cleanly, an empty log does not crash
with a traceback."""
from conftest import build_pack, pack_text, run_ghostlogs


def test_error_window_includes_context(log_copy, tmp_path):
    proc, out = build_pack(log_copy, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    text = pack_text(out)
    assert "db connection failed" in text
    # context lines from the fixture window around the first ERROR
    assert "request received" in text, "error window lost its pre-context"
    assert "Traceback" in text, "error window lost its stack lines"


def test_missing_input_fails_cleanly(tmp_path):
    proc = run_ghostlogs(["pack", tmp_path / "does-not-exist.log", "-o", tmp_path / "p"])
    assert proc.returncode != 0
    assert "Traceback" not in proc.stderr


def test_empty_log_does_not_traceback(tmp_path):
    empty = tmp_path / "empty.log"
    empty.write_text("")
    proc, out = build_pack(empty, tmp_path / "pack")
    assert "Traceback" not in proc.stderr
    if proc.returncode == 0:
        # a successful empty pack must still account: zero lines in
        from conftest import find_accounting, load_manifest

        lines_in, kept, collapsed, dropped = find_accounting(load_manifest(out))
        assert lines_in == 0 and kept == 0 and collapsed == 0 and dropped == 0


def test_help_runs():
    proc = run_ghostlogs(["--help"])
    assert proc.returncode == 0
    assert "pack" in (proc.stdout + proc.stderr).lower()
