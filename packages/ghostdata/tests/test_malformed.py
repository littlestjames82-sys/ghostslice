"""Malformed rows are counted and reported by line number, never
silently skipped (PLAN.md verification bar)."""
from __future__ import annotations

from conftest import requires_core, run_pack, run_schema


def _malformed_lines(counts):
    return sorted(ex["line"] for ex in counts["malformed_examples"])


@requires_core
def test_orders_csv_malformed_counted_by_line(orders_csv):
    out = run_schema(orders_csv)
    counts = out["counts"]
    assert counts["rows_total"] == 5
    assert counts["rows_parsed"] == 3
    assert counts["rows_malformed"] == 2
    # the ragged rows are file lines 3 and 4 (header is line 1)
    assert _malformed_lines(counts) == [3, 4]
    # parsed rows still carry correct stats: order ids 1, 4, 5
    from conftest import column
    col = column(out, "order_id")
    assert col["distinct_count"] == 3
    assert col["min"] == 1 and col["max"] == 5


@requires_core
def test_orders_csv_pack_still_packs_the_rest(orders_csv, tmp_path):
    proc, manifest = run_pack(orders_csv, tmp_path / "pack")
    assert manifest["counts"]["rows_malformed"] == 2
    assert manifest["counts"]["rows_parsed"] == 3
    assert _malformed_lines(manifest["counts"]) == [3, 4]
    assert manifest["sample"]["rows"] == 3


@requires_core
def test_events_jsonl_bad_line_counted(events_jsonl):
    out = run_schema(events_jsonl)
    counts = out["counts"]
    assert counts["rows_total"] == 4
    assert counts["rows_parsed"] == 3
    assert counts["rows_malformed"] == 1
    assert _malformed_lines(counts) == [3]


@requires_core
def test_people_csv_reports_zero_malformed(people_csv):
    out = run_schema(people_csv)
    assert out["counts"]["rows_malformed"] == 0
    assert out["counts"]["malformed_examples"] == []
