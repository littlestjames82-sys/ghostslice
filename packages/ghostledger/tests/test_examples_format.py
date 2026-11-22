"""Format tests for the shipped examples (run with or without core).

The sample history is a ledger in the PLAN.md entry shape, and the
sample report must be exactly reproducible from it: every total and
every grouped bucket in sample-report.json / sample-report.md is
recomputed here from sample-history.jsonl alone. A sample whose
numbers do not tie out is worse than no sample.
"""
from __future__ import annotations

import re

from conftest import EXAMPLES, PRICE_TABLE_AS_OF, hand_cost, load_json, load_jsonl

REQUIRED_ENTRY_FIELDS = {
    "id", "at", "day", "project", "model", "agent", "source", "kind",
    "task", "input_tokens", "output_tokens", "total_tokens",
    "estimated_tokens", "ratio", "loop_warning", "cost_estimate_usd",
    "price_table_as_of", "note",
}
SECRET_KEY = re.compile(
    r"(api[_-]?key|authorization|secret|password|passwd|credential|"
    r"bearer|session|cookie|private[_-]?key)", re.IGNORECASE)


def history():
    return load_jsonl(EXAMPLES / "sample-history.jsonl")


def agg(rows):
    out = {
        "entries": len(rows),
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "output_tokens": sum(r["output_tokens"] for r in rows),
        "total_tokens": sum(r["total_tokens"] for r in rows),
        "estimated_tokens": sum(r["estimated_tokens"] or 0 for r in rows),
        "entries_with_estimate": sum(
            1 for r in rows if r["estimated_tokens"] is not None),
        # POLISH (Oct 14, 2026): ratio/delta compare only the entries
        # that carry an estimate; see POLISH.md. Every sample entry
        # carries one, so this equals total_tokens for the samples.
        "actual_tokens_with_estimate": sum(
            r["total_tokens"] for r in rows
            if r["estimated_tokens"] is not None),
        "cost_estimate_usd": round(sum(
            r["cost_estimate_usd"] for r in rows
            if r["cost_estimate_usd"] is not None), 6),
        "entries_with_cost": sum(
            1 for r in rows if r["cost_estimate_usd"] is not None),
        "loop_warnings": sum(1 for r in rows if r["loop_warning"]),
    }
    out["estimate_vs_actual_ratio"] = (
        round(out["actual_tokens_with_estimate"] / out["estimated_tokens"], 4)
        if out["estimated_tokens"] else None)
    out["estimate_delta_tokens"] = (
        out["actual_tokens_with_estimate"] - out["estimated_tokens"]
        if out["entries_with_estimate"] else None)
    return out


def by(rows, key):
    groups = {}
    for r in rows:
        groups.setdefault(str(r[key]), []).append(r)
    return {k: agg(v) for k, v in sorted(groups.items())}


def test_sample_history_entries_carry_the_plan_entry_shape():
    rows = history()
    assert len(rows) == 8
    ids = [r["id"] for r in rows]
    assert len(set(ids)) == len(ids)
    for r in rows:
        missing = REQUIRED_ENTRY_FIELDS - set(r)
        assert not missing, f"{r['id']} missing {missing}"
        assert r["source"] in ("manual", "slice", "proxy", "bench")
        assert isinstance(r["input_tokens"], int)
        assert isinstance(r["output_tokens"], int)
        assert r["total_tokens"] == r["input_tokens"] + r["output_tokens"]
        assert r["day"] == r["at"][:10]
        assert r["price_table_as_of"] == PRICE_TABLE_AS_OF


def test_sample_history_covers_all_sources_and_dimensions():
    rows = history()
    assert {r["source"] for r in rows} == {"manual", "slice", "proxy", "bench"}
    assert len({r["project"] for r in rows}) >= 2
    assert len({r["model"] for r in rows}) >= 3
    assert len({r["agent"] for r in rows}) >= 3
    assert len({r["day"] for r in rows}) == 2


def test_sample_history_ratio_and_loop_warning_math():
    for r in history():
        est = r["estimated_tokens"]
        if est:
            assert abs(r["ratio"] - round(r["total_tokens"] / est, 4)) < 1e-9
            # Core rule: strictly greater than 3x, estimated > 0.
            assert r["loop_warning"] == (r["total_tokens"] > 3 * est)
        else:
            assert r["ratio"] is None and r["loop_warning"] is False


def test_sample_history_loop_warning_is_exactly_the_planted_one():
    warned = [r for r in history() if r["loop_warning"]]
    assert [r["id"] for r in warned] == ["led-007"]
    assert warned[0]["ratio"] == 3.6
    # The boundary case sits in the same file, deliberately unwarned.
    boundary = next(r for r in history() if r["id"] == "led-008")
    assert boundary["ratio"] == 2.9 and boundary["loop_warning"] is False


def test_sample_history_costs_hand_check_against_the_dated_table():
    for r in history():
        expected = hand_cost(r["model"], r["input_tokens"], r["output_tokens"])
        assert r["cost_estimate_usd"] == expected, r["id"]
    # Unknown model: cost is null (stated), never 0-as-fact.
    unknown = next(r for r in history() if r["model"] == "mystery-model")
    assert unknown["cost_estimate_usd"] is None
    # A zero-rate local model is genuinely 0.0, which is different.
    local = next(r for r in history() if r["model"] == "local")
    assert local["cost_estimate_usd"] == 0.0


def test_sample_report_totals_match_the_history():
    rows = history()
    report = load_json(EXAMPLES / "sample-report.json")
    assert report["sample"] is True
    assert report["totals"] == agg(rows)
    assert report["by_project"] == by(rows, "project")
    assert report["by_model"] == by(rows, "model")
    assert report["by_agent"] == by(rows, "agent")
    assert report["by_day"] == by(rows, "day")
    assert report["unknown_models"] == ["mystery-model"]
    assert [w["id"] for w in report["loop_warnings"]] == ["led-007"]


def test_sample_report_labels_costs_as_estimates_with_the_date():
    report = load_json(EXAMPLES / "sample-report.json")
    assert report["price_table_as_of"] == PRICE_TABLE_AS_OF
    assert "ESTIMATES" in report["cost_note"]
    assert "never billed amounts" in report["cost_note"]
    assert PRICE_TABLE_AS_OF in report["cost_note"]
    md = (EXAMPLES / "sample-report.md").read_text(encoding="utf-8")
    assert "SAMPLE" in md
    assert report["cost_note"] in md
    for key, total in report["totals"].items():
        if isinstance(total, int) and total > 100:
            assert f"{total}" in md or f"{total:,}" in md, key


def test_no_credential_fields_anywhere_in_the_examples():
    def walk(obj, where):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert not SECRET_KEY.search(str(k)), f"{where}: key {k!r}"
                walk(v, where)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, where)

    for path in (EXAMPLES / "sample-history.jsonl",
                 EXAMPLES / "inputs" / "slice-history.jsonl"):
        for row in load_jsonl(path):
            walk(row, str(path))
    for name in ("sample-report.json", "inputs/proxy-report.json",
                 "inputs/bench-report.json"):
        walk(load_json(EXAMPLES / name), name)
