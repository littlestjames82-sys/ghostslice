"""Tests for `ghostledger verify` (DEEPEN improvement, Oct 18, 2026).

Verify audits a booked ledger against its own rules: content-hash
ids, day/total/ratio/loop re-derivation, cost re-derivation under
the entry's own price-table date, duplicate ids, malformed lines,
and credential-named fields. It is read-only: these tests prove the
ledger bytes never change. Entries booked by the CLI itself must
verify clean; every tamper below must be caught by name.
"""
from __future__ import annotations

import json

import pytest

from conftest import PRICE_TABLE_AS_OF, add_entry, load_jsonl, requires_core, run_cli

pytestmark = requires_core


def verify(ledger, *extra, expect=(0, 1)):
    proc = run_cli(["--ledger", ledger, "verify", *extra])
    assert proc.returncode in expect, proc.stdout + proc.stderr
    return proc


def verify_json(ledger, expect=(0, 1)):
    proc = verify(ledger, "--json", expect=expect)
    return json.loads(proc.stdout), proc


def checks(data):
    return {p["check"] for p in data["problems"]}


def rewrite(ledger, rows):
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("".join(json.dumps(r) + "\n" for r in rows),
                      encoding="utf-8")


def book_two(ledger):
    add_entry(ledger, "--project", "ghostbus", "--model", "claude-sonnet",
              "--agent", "builder-a", "--task", "review",
              "--input-tokens", "10000", "--output-tokens", "2000",
              "--estimated-tokens", "12000",
              "--at", "2026-10-14T10:00:00+00:00")
    add_entry(ledger, "--project", "demo", "--model", "mystery-model",
              "--input-tokens", "500", "--at", "2026-10-14T11:00:00+00:00")
    return load_jsonl(ledger)


def test_verify_clean_ledger_exits_0_and_rechecks_costs(ledger_path):
    book_two(ledger_path)
    before = ledger_path.read_bytes()
    data, proc = verify_json(ledger_path, expect=(0,))
    assert proc.returncode == 0 and data["ok"] is True
    assert data["entries"] == 2 and data["lines"] == 2
    assert data["problem_count"] == 0 and data["problems"] == []
    # The known-model entry's cost re-derives under its own price
    # date; the unknown-model entry also re-derives (expected null).
    assert data["cost_checked"] == 2 and data["cost_unchecked"] == 0
    assert data["price_table_as_of"] == PRICE_TABLE_AS_OF
    text = verify(ledger_path, expect=(0,))
    assert "verify OK" in text.stdout
    assert ledger_path.read_bytes() == before  # read-only


def test_verify_loop_warning_entry_is_consistent_not_a_problem(ledger_path):
    # A 3.6x entry makes summary exit 1, but it is booked consistently,
    # so verify exits 0: verify checks the books, not the warning.
    add_entry(ledger_path, "--project", "over", "--input-tokens", "3600",
              "--estimated-tokens", "1000", "--at", "2026-10-14T10:00:00+00:00")
    data, proc = verify_json(ledger_path, expect=(0,))
    assert proc.returncode == 0 and data["ok"] is True


def test_verify_missing_ledger_file_is_an_error(tmp_path):
    proc = run_cli(["--ledger", tmp_path / "nope.jsonl", "verify"])
    assert proc.returncode == 2 and "not found" in proc.stderr


def test_verify_detects_tampered_cost_by_name(ledger_path):
    rows = book_two(ledger_path)
    rows[0]["cost_estimate_usd"] = 9.99
    rewrite(ledger_path, rows)
    before = ledger_path.read_bytes()
    data, proc = verify_json(ledger_path, expect=(1,))
    assert proc.returncode == 1 and data["ok"] is False
    assert checks(data) == {"cost_mismatch"}
    assert data["problems"][0]["id"] == rows[0]["id"]
    assert "FAILED" in verify(ledger_path, expect=(1,)).stdout
    assert ledger_path.read_bytes() == before  # still read-only


def test_verify_detects_tampered_total_via_id_and_sum(ledger_path):
    add_entry(ledger_path, "--project", "p", "--input-tokens", "100",
              "--output-tokens", "50", "--at", "2026-10-14T10:00:00+00:00")
    rows = load_jsonl(ledger_path)
    rows[0]["total_tokens"] = 999
    rewrite(ledger_path, rows)
    data, _ = verify_json(ledger_path, expect=(1,))
    assert checks(data) == {"id_mismatch", "total_mismatch"}


def test_verify_detects_flipped_ratio_and_loop_warning(ledger_path):
    add_entry(ledger_path, "--project", "p", "--input-tokens", "1000",
              "--estimated-tokens", "1000", "--at", "2026-10-14T10:00:00+00:00")
    rows = load_jsonl(ledger_path)
    rows[0]["ratio"] = 9.9
    rows[0]["loop_warning"] = True
    rewrite(ledger_path, rows)
    data, _ = verify_json(ledger_path, expect=(1,))
    assert checks(data) == {"ratio_mismatch", "loop_warning_mismatch"}


def test_verify_detects_day_mismatch_and_missing_field(ledger_path):
    rows = book_two(ledger_path)
    rows[0]["day"] = "2026-10-01"
    del rows[1]["note"]
    rewrite(ledger_path, rows)
    data, _ = verify_json(ledger_path, expect=(1,))
    assert checks(data) == {"day_mismatch", "missing_field"}


def test_verify_detects_duplicate_id_and_malformed_line(ledger_path):
    book_two(ledger_path)
    raw = ledger_path.read_text(encoding="utf-8")
    first_line = raw.splitlines()[0]
    with open(ledger_path, "a", encoding="utf-8") as fh:
        fh.write(first_line + "\n")
        fh.write("{not json\n")
    data, _ = verify_json(ledger_path, expect=(1,))
    assert checks(data) == {"duplicate_id", "malformed_line"}
    assert data["lines"] == 4 and data["entries"] == 3


def test_verify_flags_credential_field_without_showing_its_value(ledger_path):
    rows = book_two(ledger_path)
    rows[0]["api_key"] = "FAKE-VERIFY-CANARY-not-a-real-key"
    rewrite(ledger_path, rows)
    proc = verify(ledger_path, expect=(1,))
    assert "secret_field" in proc.stdout and "api_key" in proc.stdout
    # The discipline is naming the key only, never echoing the value.
    assert "FAKE-VERIFY-CANARY-not-a-real-key" not in proc.stdout
    data, _ = verify_json(ledger_path, expect=(1,))
    assert checks(data) == {"secret_field"}


def test_verify_flags_negative_token_count(ledger_path):
    rows = book_two(ledger_path)
    rows[0]["input_tokens"] = -5
    rewrite(ledger_path, rows)
    data, _ = verify_json(ledger_path, expect=(1,))
    assert "bad_token_count" in checks(data)


def test_verify_states_costs_booked_under_another_price_date(ledger_path):
    # An entry booked under a different dated table is NOT repriced
    # and NOT silently passed: it is counted as not re-checked.
    rows = book_two(ledger_path)
    rows[0]["price_table_as_of"] = "1999-01-01"
    rows[0]["cost_estimate_usd"] = 123.45
    rewrite(ledger_path, rows)
    data, proc = verify_json(ledger_path, expect=(0,))
    assert proc.returncode == 0 and data["ok"] is True
    assert data["cost_unchecked"] == 1 and data["cost_checked"] == 1
    text = verify(ledger_path, expect=(0,))
    assert "not re-checked" in text.stdout


def test_verify_is_listed_in_help():
    proc = run_cli(["--help"])
    assert proc.returncode == 0 and "verify" in proc.stdout
