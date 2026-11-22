"""Polish-round regression tests (Oct 14, 2026). See POLISH.md.

Every test here pins a demonstrate-then-fix audit finding:
- F2: Bench variants{} sliced/proxied tokens are the booked actual.
- Negative token counts are invalid evidence, never booked.
- append_entries dedupes identical ids within one batch.
- Model labels match the price table case-insensitively and are
  stored stripped, so an unknown-model booking is genuinely unknown.
- Report estimate-vs-actual compares only entries with an estimate.

Black-box CLI style like test_cli.py, plus one labelled unit test
for the append_entries batch guard (no CLI path can hand it a batch
with duplicate ids, because importers stamp a per-record source_ref).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from conftest import (SRC, add_entry, hand_cost, load_jsonl, requires_core,
                      run_cli)

pytestmark = requires_core


def ledger_rows(path):
    return load_jsonl(path) if path.exists() else []


def write_bench(tmp_path, tasks, name="bench.json"):
    path = tmp_path / name
    path.write_text(json.dumps({
        "tool": "ghostbench", "run_id": "polish-run",
        "created_utc": "2026-10-14T09:00:00+00:00", "tasks": tasks,
    }), encoding="utf-8")
    return path


def import_bench(ledger, path):
    proc = run_cli(["--ledger", ledger, "import", "--bench-report", path])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


# ------------------------------------------------------------- F2 variants

def test_bench_proxied_variant_used_when_no_sliced(ledger_path, tmp_path):
    src = write_bench(tmp_path, [{
        "task": "t-proxied", "project": "p", "full_tokens": 5000,
        "variants": {"proxied": {"tokens": 1200}},
    }])
    import_bench(ledger_path, src)
    (e,) = ledger_rows(ledger_path)
    assert e["total_tokens"] == 1200 and e["estimated_tokens"] == 5000
    assert "bench_variant=proxied" in e["note"]


def test_bench_variant_null_and_negative_fall_back_never_booked(ledger_path,
                                                               tmp_path):
    src = write_bench(tmp_path, [
        {"task": "t-null", "project": "p", "full_tokens": 5000,
         "variants": {"sliced": {"tokens": None}}},
        {"task": "t-negative", "project": "p", "full_tokens": 5000,
         "variants": {"sliced": {"tokens": -50}}},
    ])
    import_bench(ledger_path, src)
    rows = {r["task"]: r for r in ledger_rows(ledger_path)}
    # Invalid variant evidence is treated as absent: the full count
    # is the fallback actual, exactly as for a missing variant.
    assert rows["t-null"]["total_tokens"] == 5000
    assert rows["t-negative"]["total_tokens"] == 5000
    assert all(r["total_tokens"] >= 0 for r in rows.values())


def test_bench_variant_string_tokens_and_full_from_variants(ledger_path,
                                                            tmp_path):
    src = write_bench(tmp_path, [{
        "task": "t-string", "project": "p",
        "variants": {"full": {"tokens": 4000}, "sliced": {"tokens": "1500"}},
    }])
    import_bench(ledger_path, src)
    (e,) = ledger_rows(ledger_path)
    assert e["total_tokens"] == 1500 and e["estimated_tokens"] == 4000


def test_bench_sliced_zero_is_booked_as_zero(ledger_path, tmp_path):
    src = write_bench(tmp_path, [{
        "task": "t-zero", "project": "p", "full_tokens": 5000,
        "variants": {"sliced": {"tokens": 0}},
    }])
    import_bench(ledger_path, src)
    (e,) = ledger_rows(ledger_path)
    assert e["total_tokens"] == 0 and e["estimated_tokens"] == 5000
    assert e["ratio"] == 0.0 and e["loop_warning"] is False


def test_bench_variant_over_estimate_trips_loop_warning(ledger_path, tmp_path):
    # A "sliced" actual larger than full is exactly the divergence
    # Ledger exists to flag: estimated = full, actual = variant.
    src = write_bench(tmp_path, [{
        "task": "t-bloated", "project": "p", "full_tokens": 2000,
        "variants": {"sliced": {"tokens": 10000}},
    }])
    import_bench(ledger_path, src)
    (e,) = ledger_rows(ledger_path)
    assert e["ratio"] == 5.0 and e["loop_warning"] is True
    proc = run_cli(["--ledger", ledger_path, "summary"])
    assert proc.returncode == 1 and "WARNING" in proc.stdout


def test_bench_reimport_after_variants_fix_still_dedupes(ledger_path,
                                                          tmp_path):
    src = write_bench(tmp_path, [{
        "task": "t-once", "project": "p", "full_tokens": 4200,
        "variants": {"sliced": {"tokens": 1000}},
    }])
    import_bench(ledger_path, src)
    proc = import_bench(ledger_path, src)
    assert "0 added" in proc.stdout
    assert len(ledger_rows(ledger_path)) == 1


# ------------------------------------------------------- negative counts

def test_add_negative_tokens_is_an_error_and_books_nothing(ledger_path):
    for flag in ("--input-tokens", "--output-tokens", "--total-tokens",
                 "--estimated-tokens"):
        proc = run_cli(["--ledger", ledger_path, "add", "--project", "p",
                        flag, "-100", "--at", "2026-10-14T10:00:00+00:00"])
        assert proc.returncode == 2, (flag, proc.stdout, proc.stderr)
        assert "must not be negative" in proc.stderr
    assert ledger_rows(ledger_path) == []


def test_import_slice_history_skips_negative_after_tokens(ledger_path,
                                                          tmp_path):
    src = tmp_path / "hist.jsonl"
    good = {"at": "2026-10-13T09:15:00+00:00", "kind": "export",
            "before_tokens": 100, "after_tokens": 50, "saved_tokens": 50,
            "estimator": "v2"}
    bad = dict(good, at="2026-10-13T10:00:00+00:00", after_tokens=-50)
    src.write_text(json.dumps(good) + "\n" + json.dumps(bad) + "\n",
                   encoding="utf-8")
    proc = run_cli(["--ledger", ledger_path, "import",
                    "--slice-history", src])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 entries parsed, 1 added, 1 skipped" in proc.stdout
    assert [r["total_tokens"] for r in ledger_rows(ledger_path)] == [50]


# ------------------------------------------------------------- dedupe unit

def test_append_entries_dedupes_within_one_batch(tmp_path):
    """Unit test (labelled): the batch guard in append_entries.

    No CLI path can produce a batch whose ids repeat, because every
    importer stamps a per-record source_ref into the id. The guard is
    defence in depth for direct callers, so it is tested directly.
    """
    sys.path.insert(0, str(SRC))
    from ghostledger.ledger import append_entries, load_entries, make_entry

    entry = make_entry(project="p", input_tokens=100,
                       at="2026-10-14T10:00:00+00:00")
    ledger = tmp_path / "books.jsonl"
    assert append_entries(ledger, [entry, dict(entry)]) == 1
    assert len(load_entries(ledger)) == 1
    assert append_entries(ledger, [entry]) == 0


# ------------------------------------------------------- model matching

def test_add_model_case_variant_books_known_cost(ledger_path):
    proc = add_entry(ledger_path, "--project", "p", "--model",
                     "Claude-Sonnet", "--input-tokens", "10000",
                     "--output-tokens", "2000",
                     "--at", "2026-10-14T10:00:00+00:00")
    (e,) = ledger_rows(ledger_path)
    assert e["cost_estimate_usd"] == hand_cost("claude-sonnet", 10000, 2000)
    assert "not in price table" not in proc.stdout


def test_add_model_with_whitespace_is_stripped_and_costed(ledger_path):
    add_entry(ledger_path, "--project", "p", "--model", " claude-sonnet ",
              "--input-tokens", "1000",
              "--at", "2026-10-14T10:00:00+00:00")
    (e,) = ledger_rows(ledger_path)
    assert e["model"] == "claude-sonnet"
    assert e["cost_estimate_usd"] == hand_cost("claude-sonnet", 1000, 0)


def test_add_genuinely_unknown_model_still_books_null(ledger_path):
    add_entry(ledger_path, "--project", "p", "--model", "Mystery-Model",
              "--input-tokens", "1000",
              "--at", "2026-10-14T10:00:00+00:00")
    (e,) = ledger_rows(ledger_path)
    assert e["cost_estimate_usd"] is None


# ------------------------------------------------------- report accuracy

def test_report_ratio_uses_only_entries_with_an_estimate(ledger_path):
    add_entry(ledger_path, "--project", "p", "--input-tokens", "1000",
              "--estimated-tokens", "1000",
              "--at", "2026-10-14T10:00:00+00:00")
    add_entry(ledger_path, "--project", "p", "--input-tokens", "9000",
              "--at", "2026-10-14T11:00:00+00:00")
    proc = run_cli(["--ledger", ledger_path, "summary", "--json"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    totals = json.loads(proc.stdout)["totals"]
    assert totals["total_tokens"] == 10000
    assert totals["estimated_tokens"] == 1000
    assert totals["entries_with_estimate"] == 1
    assert totals["actual_tokens_with_estimate"] == 1000
    # The estimated entry matched exactly: ratio 1.0, delta 0. The
    # pre-polish formula divided the grand total (10000/1000 = 10.0).
    assert totals["estimate_vs_actual_ratio"] == 1.0
    assert totals["estimate_delta_tokens"] == 0


def test_report_by_model_ratio_with_partial_coverage(ledger_path):
    add_entry(ledger_path, "--project", "p", "--model", "claude-sonnet",
              "--input-tokens", "2000", "--estimated-tokens", "1000",
              "--at", "2026-10-14T10:00:00+00:00")
    add_entry(ledger_path, "--project", "p", "--model", "claude-sonnet",
              "--input-tokens", "500",
              "--at", "2026-10-14T11:00:00+00:00")
    proc = run_cli(["--ledger", ledger_path, "summary", "--json"])
    bucket = json.loads(proc.stdout)["by_model"]["claude-sonnet"]
    assert bucket["total_tokens"] == 2500
    assert bucket["actual_tokens_with_estimate"] == 2000
    assert bucket["estimate_vs_actual_ratio"] == 2.0
    assert bucket["estimate_delta_tokens"] == 1000
