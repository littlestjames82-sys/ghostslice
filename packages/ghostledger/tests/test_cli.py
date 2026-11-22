"""Black-box CLI tests: add / import / report / summary.

Written against the core contract in PLAN.md as landed by Agent A
(command layout, entry shape, exit codes 0/1/2). All runs use a tmp
ledger; nothing touches a real project ledger, no network, no spend.
"""
from __future__ import annotations

import json

import pytest

from conftest import (CANARY, FIXTURES, PRICE_TABLE_AS_OF, add_entry,
                      hand_cost, load_json, load_jsonl, requires_core,
                      run_cli)

pytestmark = requires_core


def ledger_rows(path):
    return load_jsonl(path) if path.exists() else []


def summary_json(ledger, *extra, expect=(0, 1)):
    proc = run_cli(["--ledger", ledger, "summary", "--json", *extra])
    assert proc.returncode in expect, proc.stdout + proc.stderr
    return json.loads(proc.stdout), proc


# ---------------------------------------------------------------- add

def test_version_and_help():
    proc = run_cli(["--version"])
    assert proc.returncode == 0 and "0.1.0" in proc.stdout
    proc = run_cli(["--help"])
    assert proc.returncode == 0
    for cmd in ("add", "import", "report", "summary"):
        assert cmd in proc.stdout


def test_add_known_model_cost_hand_checks(ledger_path):
    add_entry(ledger_path, "--project", "ghostbus", "--model",
              "claude-sonnet", "--agent", "builder-a", "--task", "t",
              "--input-tokens", "10000", "--output-tokens", "2000",
              "--at", "2026-10-14T10:00:00+00:00")
    rows = ledger_rows(ledger_path)
    assert len(rows) == 1
    e = rows[0]
    assert e["source"] == "manual" and e["project"] == "ghostbus"
    assert e["total_tokens"] == 12000 and e["day"] == "2026-10-14"
    # $3/M input + $15/M output on 10k/2k = 0.03 + 0.03 (estimates).
    assert e["cost_estimate_usd"] == hand_cost("claude-sonnet", 10000, 2000) == 0.06
    assert e["price_table_as_of"] == PRICE_TABLE_AS_OF
    assert e["loop_warning"] is False


def test_add_total_tokens_alone_is_booked_as_input(ledger_path):
    add_entry(ledger_path, "--project", "p", "--total-tokens", "5000",
              "--at", "2026-10-14T10:00:00+00:00")
    e = ledger_rows(ledger_path)[0]
    assert e["input_tokens"] == 5000 and e["output_tokens"] == 0
    assert e["total_tokens"] == 5000


def test_add_unknown_model_cost_is_null_never_zero(ledger_path):
    proc = add_entry(ledger_path, "--project", "p", "--model",
                     "mystery-model", "--input-tokens", "1000",
                     "--at", "2026-10-14T10:00:00+00:00")
    e = ledger_rows(ledger_path)[0]
    assert e["cost_estimate_usd"] is None
    assert "not in price table" in proc.stdout
    data, _ = summary_json(ledger_path)
    assert data["unknown_models"] == ["mystery-model"]
    assert data["totals"]["entries_with_cost"] == 0


def test_add_same_entry_twice_is_not_double_booked(ledger_path):
    args = ("--project", "p", "--input-tokens", "100",
            "--at", "2026-10-14T10:00:00+00:00")
    add_entry(ledger_path, *args)
    proc = add_entry(ledger_path, *args)
    assert "not re-booked" in proc.stdout
    assert len(ledger_rows(ledger_path)) == 1


# ------------------------------------------------------- loop warning

def test_loop_warning_above_3x_flagged_at_2_9x_and_exactly_3x_not(ledger_path):
    add_entry(ledger_path, "--project", "over", "--input-tokens", "31000",
              "--estimated-tokens", "10000",
              "--at", "2026-10-14T10:00:00+00:00")
    add_entry(ledger_path, "--project", "under", "--input-tokens", "29000",
              "--estimated-tokens", "10000",
              "--at", "2026-10-14T10:01:00+00:00")
    add_entry(ledger_path, "--project", "edge", "--input-tokens", "30000",
              "--estimated-tokens", "10000",
              "--at", "2026-10-14T10:02:00+00:00")
    rows = {r["project"]: r for r in ledger_rows(ledger_path)}
    assert rows["over"]["loop_warning"] is True
    assert rows["over"]["ratio"] == 3.1
    # Core rule is strictly greater than 3x: 2.9x and exactly 3.0x pass.
    assert rows["under"]["loop_warning"] is False
    assert rows["edge"]["loop_warning"] is False


def test_summary_exit_1_and_warning_listed_when_loop_warning(ledger_path):
    add_entry(ledger_path, "--project", "over", "--input-tokens", "3600",
              "--estimated-tokens", "1000",
              "--at", "2026-10-14T10:00:00+00:00")
    data, proc = summary_json(ledger_path, expect=(1,))
    assert proc.returncode == 1  # 1 = loop warning present, not an error
    assert data["totals"]["loop_warnings"] == 1
    assert [w["project"] for w in data["loop_warnings"]] == ["over"]
    text = run_cli(["--ledger", ledger_path, "summary"])
    assert text.returncode == 1 and "WARNING" in text.stdout
    assert "exceeded 3x" in text.stdout


def test_summary_no_files_written_and_filters_apply(ledger_path, tmp_path):
    add_entry(ledger_path, "--project", "a", "--input-tokens", "100",
              "--at", "2026-10-13T10:00:00+00:00")
    add_entry(ledger_path, "--project", "b", "--input-tokens", "200",
              "--at", "2026-10-14T10:00:00+00:00")
    before = {p.name for p in tmp_path.rglob("*")}
    data, _ = summary_json(ledger_path, "--since", "2026-10-14",
                           expect=(0,))
    assert data["totals"]["entries"] == 1
    assert data["totals"]["total_tokens"] == 200
    data, _ = summary_json(ledger_path, "--project", "a", expect=(0,))
    assert data["totals"]["total_tokens"] == 100
    after = {p.name for p in tmp_path.rglob("*")}
    assert before == after  # summary writes nothing


# ---------------------------------------------------------------- import

def test_import_slice_history_counts_and_reimport_dedupe(ledger_path):
    src = FIXTURES / "slice-history.jsonl"
    proc = run_cli(["--ledger", ledger_path, "import",
                    "--slice-history", src])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # Fixture: 3 valid records, 1 malformed line, 1 record with no
    # after_tokens -> 3 parsed, 2 skipped, never fatal.
    assert "3 entries parsed, 3 added, 2 skipped" in proc.stdout
    rows = ledger_rows(ledger_path)
    assert len(rows) == 3
    assert all(r["source"] == "slice" for r in rows)
    # Booked actual = after_tokens (what was actually sent).
    assert sum(r["input_tokens"] for r in rows) == 9000
    assert sum(r["total_tokens"] for r in rows) == 9000
    proc = run_cli(["--ledger", ledger_path, "import",
                    "--slice-history", src])
    assert "0 added" in proc.stdout
    assert len(ledger_rows(ledger_path)) == 3


def test_import_proxy_report_drops_credential_canary(ledger_path):
    proc = run_cli(["--ledger", ledger_path, "import",
                    "--proxy-report", FIXTURES / "proxy-report.json"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "2 entries parsed, 2 added, 0 skipped" in proc.stdout
    rows = ledger_rows(ledger_path)
    assert len(rows) == 2
    assert all(r["source"] == "proxy" for r in rows)
    assert sum(r["total_tokens"] for r in rows) == (2000 + 500) + (1500 + 250)
    raw = ledger_path.read_text(encoding="utf-8")
    assert CANARY not in raw and "api_key" not in raw


def test_import_bench_report_books_each_task(ledger_path):
    proc = run_cli(["--ledger", ledger_path, "import",
                    "--bench-report", FIXTURES / "bench-report.json"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "2 entries parsed, 2 added, 0 skipped" in proc.stdout
    rows = ledger_rows(ledger_path)
    assert len(rows) == 2
    assert all(r["source"] == "bench" for r in rows)
    # POLISH (Oct 14, 2026, finding F2 - updated openly, see
    # POLISH.md): the importer now reads variants{}.sliced.tokens as
    # the actual and full_tokens as the estimate, as PLAN.md always
    # specified. This test previously pinned the v0.1 limit (actual =
    # full_tokens, sum 6800); it now pins the corrected behaviour:
    # 1000 sliced of 4200 full, and 2600 sliced of 2600 full.
    by_task = {r["task"]: r for r in rows}
    first = by_task["adv-001-fix-missing-route"]
    assert first["total_tokens"] == 1000 and first["estimated_tokens"] == 4200
    assert first["ratio"] == 0.2381
    second = by_task["adv-003-small-task"]
    assert second["total_tokens"] == 2600 and second["estimated_tokens"] == 2600
    assert sum(r["total_tokens"] for r in rows) == 3600
    assert sum(r["estimated_tokens"] for r in rows) == 6800
    assert all(r["loop_warning"] is False for r in rows)


def test_import_source_file_autodetects_slice_and_bench(ledger_path):
    proc = run_cli(["--ledger", ledger_path, "import",
                    "--source-file", FIXTURES / "slice-history.jsonl"])
    assert proc.returncode == 0 and "detected slice" in proc.stdout
    proc = run_cli(["--ledger", ledger_path, "import",
                    "--source-file", FIXTURES / "bench-report.json"])
    assert proc.returncode == 0 and "detected bench" in proc.stdout
    sources = {r["source"] for r in ledger_rows(ledger_path)}
    assert sources == {"slice", "bench"}


def test_import_with_nothing_to_import_is_an_error(ledger_path):
    proc = run_cli(["--ledger", ledger_path, "import"])
    assert proc.returncode == 2
    assert "nothing to import" in proc.stderr


# ---------------------------------------------------------------- report

def test_report_writes_json_and_markdown_with_all_groupings(ledger_path,
                                                            tmp_path):
    add_entry(ledger_path, "--project", "ghostbus", "--model",
              "claude-sonnet", "--agent", "builder-a",
              "--input-tokens", "10000", "--output-tokens", "2000",
              "--estimated-tokens", "12000",
              "--at", "2026-10-13T10:00:00+00:00")
    add_entry(ledger_path, "--project", "demo-shop", "--model",
              "claude-sonnet", "--agent", "loopy-agent",
              "--input-tokens", "3600", "--estimated-tokens", "1000",
              "--at", "2026-10-14T10:00:00+00:00")
    out = tmp_path / "report-out"
    proc = run_cli(["--ledger", ledger_path, "report",
                    "--out-dir", out])
    assert proc.returncode == 1  # loop warning present
    data = load_json(out / "ledger-report.json")
    assert data["totals"]["entries"] == 2
    assert data["totals"]["total_tokens"] == 12000 + 3600
    for dim in ("by_project", "by_model", "by_agent", "by_day"):
        assert dim in data and data[dim], dim
    assert set(data["by_project"]) == {"ghostbus", "demo-shop"}
    assert set(data["by_day"]) == {"2026-10-13", "2026-10-14"}
    assert data["price_table_as_of"] == PRICE_TABLE_AS_OF
    assert "ESTIMATES" in data["cost_note"]
    assert "never billed amounts" in data["cost_note"]
    assert len(data["loop_warnings"]) == 1
    md = (out / "LEDGER.md").read_text(encoding="utf-8")
    assert data["cost_note"] in md
    for heading in ("## By project", "## By model", "## By agent",
                    "## By day", "## Loop warnings"):
        assert heading in md
    assert "loopy-agent" in md


def test_report_json_mode_prints_without_writing_files(ledger_path,
                                                       tmp_path):
    add_entry(ledger_path, "--project", "p", "--input-tokens", "100",
              "--at", "2026-10-14T10:00:00+00:00")
    out = tmp_path / "should-not-appear"
    proc = run_cli(["--ledger", ledger_path, "report", "--by", "day",
                    "--json", "--out-dir", out])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data["totals"]["total_tokens"] == 100
    assert not out.exists()
