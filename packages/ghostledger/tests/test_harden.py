"""Harden-round regression tests (Oct 18, 2026).

Every test pins a bug found by probing the shipped code, then fixed
minimally in the HARDEN lane:

- Bench tasks with no full count fabricated their own estimate.
- A non-dict Bench ``corpus`` crashed the import (AttributeError).
- Non-finite token counts (JSON Infinity) crashed imports
  (OverflowError from ``int(inf)``), as did numeric timestamps
  (TypeError in day derivation) and non-dict / negative / NaN price
  rates (AttributeError / silently booked negative or NaN costs).
- An explicitly named --prices file that was missing or malformed
  silently fell back to the bundled snapshot.
- Singular ``*_token`` credential keys survived secret stripping.
- ``--source-file`` detection was case-sensitive (``.JSONL`` failed).
- Garbage / impossible --at and --since/--until values booked or
  filtered silently; unwritable ledger / report paths and corrupt
  ledger rows crashed with tracebacks instead of exit 2 / tolerance.
- Project labels with newlines or pipes injected structure into
  LEDGER.md.
"""
from __future__ import annotations

import json
import re
import sys

import pytest

from conftest import SRC, add_entry, load_jsonl, requires_core, run_cli

pytestmark = requires_core


def ledger_rows(path):
    return load_jsonl(path) if path.exists() else []


def write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------- bench importer

def test_bench_task_without_full_count_books_no_estimate(ledger_path, tmp_path):
    src = write_json(tmp_path / "bench.json", {
        "tasks": [{"task": "t-nofull", "project": "p", "sliced_tokens": 100}],
    })
    proc = run_cli(["--ledger", ledger_path, "import", "--bench-report", src])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (e,) = ledger_rows(ledger_path)
    assert e["total_tokens"] == 100
    # Pre-fix the actual was copied into estimated_tokens, fabricating
    # a perfect 1.0 ratio: an estimate and an actual blended silently.
    assert e["estimated_tokens"] is None and e["ratio"] is None
    data = json.loads(run_cli(["--ledger", ledger_path, "summary",
                               "--json"]).stdout)
    assert data["totals"]["entries_with_estimate"] == 0
    assert data["totals"]["estimate_vs_actual_ratio"] is None


def test_bench_non_dict_corpus_does_not_crash_import(ledger_path, tmp_path):
    src = write_json(tmp_path / "bench.json", {
        "corpus": "not-a-dict",
        "tasks": [{"task": "t", "sliced_tokens": 10}],
    })
    proc = run_cli(["--ledger", ledger_path, "import", "--bench-report", src])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (e,) = ledger_rows(ledger_path)
    assert e["project"] == "unknown" and e["total_tokens"] == 10


# ------------------------------------------------------- tolerant _int

def test_proxy_infinite_token_count_is_skipped_not_a_crash(ledger_path, tmp_path):
    src = tmp_path / "proxy.json"
    # json.dumps cannot emit Infinity tokens_in alongside valid data
    # through the helper for just one field, so write it raw: the
    # Python JSON parser accepts the Infinity literal.
    src.write_text('{"entries": ['
                   '{"project": "p", "tokens_in": Infinity},'
                   '{"project": "p", "tokens_in": 5, "tokens_out": 1}'
                   "]}", encoding="utf-8")
    proc = run_cli(["--ledger", ledger_path, "import", "--proxy-report", src])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr
    assert "1 entries parsed, 1 added, 1 skipped" in proc.stdout
    (e,) = ledger_rows(ledger_path)
    assert e["total_tokens"] == 6


def test_slice_numeric_timestamp_is_booked_not_a_crash(ledger_path, tmp_path):
    src = tmp_path / "hist.jsonl"
    src.write_text(json.dumps({"at": 1720000000, "after_tokens": 10}) + "\n",
                   encoding="utf-8")
    proc = run_cli(["--ledger", ledger_path, "import", "--slice-history", src])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (e,) = ledger_rows(ledger_path)
    assert e["total_tokens"] == 10
    # The epoch number is not interpreted (seconds? milliseconds?):
    # the entry falls back to a real ISO day instead of "1720000000".
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["day"])


def test_source_file_detects_uppercase_jsonl(ledger_path, tmp_path):
    src = tmp_path / "HISTORY.JSONL"
    src.write_text(json.dumps({"at": "2026-10-13T09:15:00+00:00",
                               "after_tokens": 42}) + "\n", encoding="utf-8")
    proc = run_cli(["--ledger", ledger_path, "import", "--source-file", src])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "detected slice" in proc.stdout
    assert ledger_rows(ledger_path)[0]["total_tokens"] == 42


# ------------------------------------------------------------- price table

def test_explicit_prices_missing_or_malformed_is_an_error(ledger_path, tmp_path):
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json", encoding="utf-8")
    bad_shape = write_json(tmp_path / "shape.json", {"models": "nope"})
    for prices in (tmp_path / "missing.json", bad_json, bad_shape):
        proc = run_cli(["--ledger", ledger_path, "--prices", prices,
                        "add", "--project", "p", "--input-tokens", "10",
                        "--at", "2026-10-14T10:00:00+00:00"])
        assert proc.returncode == 2, (prices, proc.stdout, proc.stderr)
        assert "could not load price table" in proc.stderr
    assert ledger_rows(ledger_path) == []  # nothing booked at wrong rates


def test_price_table_with_junk_model_entries_books_unknown_not_crash(
        ledger_path, tmp_path):
    prices = write_json(tmp_path / "prices.json", {
        "as_of": "2026-10-12",
        "models": ["not-a-dict",
                   {"id": "neg-model", "input_per_mtok_usd": -3.0,
                    "output_per_mtok_usd": 1.0},
                   {"id": "nan-model", "input_per_mtok_usd": float("nan"),
                    "output_per_mtok_usd": 1.0}],
    })
    for model in ("neg-model", "nan-model"):
        proc = run_cli(["--ledger", ledger_path, "--prices", prices,
                        "add", "--project", "p", "--model", model,
                        "--input-tokens", "1000",
                        "--at", "2026-10-14T10:00:00+00:00"])
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "Traceback" not in proc.stderr
    rows = ledger_rows(ledger_path)
    # Negative / NaN rates are not usable estimates: cost is unknown
    # (null), never a negative or NaN dollar figure.
    assert [r["cost_estimate_usd"] for r in rows] == [None, None]


# ---------------------------------------------------------- secret stripping

def test_strip_secrets_drops_singular_token_credentials():
    """Unit test (labelled): strip_secrets is the documented barrier."""
    sys.path.insert(0, str(SRC))
    from ghostledger.ledger import strip_secrets

    cleaned = strip_secrets({
        "access_token": "X", "refresh_token": "Y", "csrf_token": "Z",
        "nested": {"token": "W"},
        "tokens_in": 5, "context_tokens_out": 7, "token_count": 3,
        "input_tokens": 9, "after_tokens": 4,
    })
    flat = json.dumps(cleaned)
    for leaked in ("X", "Y", "Z", "W", "access_token", "refresh_token"):
        assert leaked not in flat
    # Counts survive: they are numbers, not credentials.
    assert cleaned["tokens_in"] == 5 and cleaned["context_tokens_out"] == 7
    assert cleaned["token_count"] == 3 and cleaned["input_tokens"] == 9


# ------------------------------------------------------------ CLI validation

def test_add_rejects_garbage_and_impossible_at(ledger_path):
    for at in ("garbage-date-xyz", "2026-02-30T10:00:00", "2026-13-01"):
        proc = run_cli(["--ledger", ledger_path, "add", "--project", "p",
                        "--input-tokens", "100", "--at", at])
        assert proc.returncode == 2, (at, proc.stdout, proc.stderr)
        assert "--at must be an ISO" in proc.stderr
    assert ledger_rows(ledger_path) == []


def test_summary_rejects_invalid_since_until(ledger_path):
    add_entry(ledger_path, "--project", "p", "--input-tokens", "100",
              "--at", "2026-10-14T10:00:00+00:00")
    for flag in ("--since", "--until"):
        proc = run_cli(["--ledger", ledger_path, "summary", flag, "not-a-date"])
        assert proc.returncode == 2, (flag, proc.stdout, proc.stderr)
        assert "must be a YYYY-MM-DD date" in proc.stderr
        assert "Traceback" not in proc.stderr


# --------------------------------------------------------- I/O error handling

def test_add_to_a_directory_ledger_path_is_exit_2_not_traceback(tmp_path):
    proc = run_cli(["--ledger", tmp_path, "add", "--project", "p",
                    "--input-tokens", "10",
                    "--at", "2026-10-14T10:00:00+00:00"])
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "error:" in proc.stderr and "Traceback" not in proc.stderr


def test_summary_on_a_directory_ledger_path_is_exit_2(tmp_path):
    proc = run_cli(["--ledger", tmp_path, "summary"])
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "not a file" in proc.stderr and "Traceback" not in proc.stderr


def test_report_with_out_dir_that_is_a_file_is_exit_2(ledger_path, tmp_path):
    add_entry(ledger_path, "--project", "p", "--input-tokens", "100",
              "--at", "2026-10-14T10:00:00+00:00")
    blocker = tmp_path / "a-file"
    blocker.write_text("x", encoding="utf-8")
    proc = run_cli(["--ledger", ledger_path, "report", "--out-dir", blocker])
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "error:" in proc.stderr and "Traceback" not in proc.stderr


def test_summary_tolerates_corrupt_numeric_fields_in_ledger(tmp_path):
    ledger = tmp_path / "books.jsonl"
    ledger.write_text(
        json.dumps({"id": "x", "project": "p", "input_tokens": "abc",
                    "output_tokens": None, "total_tokens": "NaN-ish",
                    "cost_estimate_usd": "not-a-number"}) + "\n"
        + json.dumps({"id": "y", "project": "p", "input_tokens": 100,
                      "output_tokens": 0, "total_tokens": 100,
                      "cost_estimate_usd": None}) + "\n",
        encoding="utf-8")
    proc = run_cli(["--ledger", ledger, "summary", "--json"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr
    totals = json.loads(proc.stdout)["totals"]
    assert totals["entries"] == 2 and totals["total_tokens"] == 100


# ------------------------------------------------------------ markdown safety

def test_markdown_report_escapes_label_newlines_and_pipes(ledger_path, tmp_path):
    add_entry(ledger_path, "--project", "evil|proj\n## INJECTED",
              "--input-tokens", "10", "--at", "2026-10-14T10:00:00+00:00")
    out = tmp_path / "out"
    proc = run_cli(["--ledger", ledger_path, "report", "--out-dir", out])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    md = (out / "LEDGER.md").read_text(encoding="utf-8")
    assert "\n## INJECTED" not in md
    assert "evil\\|proj ## INJECTED" in md
