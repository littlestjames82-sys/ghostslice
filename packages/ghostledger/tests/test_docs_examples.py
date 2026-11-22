"""The examples/README demo, exercised end to end (core required).

Locks the claims the examples make: one import per source adds 2
entries each, the manual 3.6x entry warns, the summary then exits 1,
a report writes both files, and re-importing adds nothing.
"""
from __future__ import annotations

import pytest

from conftest import EXAMPLES, add_entry, load_jsonl, requires_core, run_cli

pytestmark = requires_core


def test_examples_demo_flow(ledger_path, tmp_path):
    inputs = EXAMPLES / "inputs"
    for flag, name in (("--slice-history", "slice-history.jsonl"),
                       ("--proxy-report", "proxy-report.json"),
                       ("--bench-report", "bench-report.json")):
        proc = run_cli(["--ledger", ledger_path, "import",
                        flag, inputs / name])
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "2 entries parsed, 2 added, 0 skipped" in proc.stdout
    add_entry(ledger_path, "--project", "demo-shop", "--model",
              "claude-sonnet", "--agent", "loopy-agent",
              "--input-tokens", "3400", "--output-tokens", "200",
              "--estimated-tokens", "1000",
              "--at", "2026-10-14T10:47:00+00:00")
    rows = load_jsonl(ledger_path)
    assert len(rows) == 7
    # POLISH (Oct 14, 2026, F2): Bench example tasks now book their
    # variants{}.sliced.tokens (1000 each) instead of full_tokens
    # (4200 each), so the demo total drops 85970 -> 79570. See
    # POLISH.md.
    assert sum(r["total_tokens"] for r in rows) == 79570
    bench_rows = [r for r in rows if r["source"] == "bench"]
    assert [r["total_tokens"] for r in bench_rows] == [1000, 1000]
    assert [r["estimated_tokens"] for r in bench_rows] == [4200, 4200]
    warned = [r for r in rows if r["loop_warning"]]
    assert len(warned) == 1 and warned[0]["ratio"] == 3.6
    proc = run_cli(["--ledger", ledger_path, "summary"])
    assert proc.returncode == 1 and "WARNING" in proc.stdout
    out = tmp_path / "report"
    proc = run_cli(["--ledger", ledger_path, "report", "--out-dir", out])
    assert proc.returncode == 1
    assert (out / "ledger-report.json").exists()
    assert (out / "LEDGER.md").exists()
    # Re-import never double-books.
    proc = run_cli(["--ledger", ledger_path, "import",
                    "--slice-history", inputs / "slice-history.jsonl"])
    assert "0 added" in proc.stdout
    assert len(load_jsonl(ledger_path)) == 7
