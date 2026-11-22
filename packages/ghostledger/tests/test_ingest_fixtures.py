"""Fixture-shape tests for the three ingest sources (no core needed).

Each fixture mirrors the REAL producer's shape, checked against the
producers in this workspace: GhostSlice's `.ghostslice-history.jsonl`
(at/kind/before_tokens/after_tokens/saved_tokens/estimator),
GhostProxy's report (entries[] with tokens_in/tokens_out plus a
top-level requests COUNT, which an importer must not mistake for a
record list), and GhostBench's bench-report.json (tasks[] with
full_tokens and a variants block). If a producer's shape drifts,
these tests are where the drift shows up first.
"""
from __future__ import annotations

import json

from conftest import CANARY, EXAMPLES, FIXTURES, load_json, load_jsonl


def _lines(path):
    return [ln for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def test_slice_fixture_matches_real_history_shape():
    rows, bad = [], 0
    for line in _lines(FIXTURES / "slice-history.jsonl"):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    # Planted by design: 1 malformed line, 1 record with no
    # after_tokens (nothing bookable). 3 valid records remain.
    assert bad == 1
    valid = [r for r in rows if isinstance(r, dict) and "after_tokens" in r]
    unbookable = [r for r in rows
                   if isinstance(r, dict) and "after_tokens" not in r]
    assert len(valid) == 3 and len(unbookable) == 1
    for r in valid:
        assert r["saved_tokens"] == r["before_tokens"] - r["after_tokens"]
        assert r["kind"] and r["at"][:10] and r["estimator"]
    assert sum(r["after_tokens"] for r in valid) == 9000


def test_examples_slice_input_matches_real_history_shape():
    for r in load_jsonl(EXAMPLES / "inputs" / "slice-history.jsonl"):
        assert r["saved_tokens"] == r["before_tokens"] - r["after_tokens"]
        assert {"at", "kind", "estimator"} <= set(r)


def test_proxy_fixture_matches_real_proxy_report_shape():
    data = load_json(FIXTURES / "proxy-report.json")
    assert data["tool"] == "ghostproxy"
    # Top-level `requests` is a COUNT in the real report, not a list.
    assert isinstance(data["requests"], int)
    assert data["requests"] == len(data["entries"]) == 2
    total_in = sum(e["tokens_in"] for e in data["entries"])
    total_out = sum(e["tokens_out"] for e in data["entries"])
    assert (total_in, total_out) == (data["tokens_in"], data["tokens_out"])
    for e in data["entries"]:
        assert {"project", "tokens_in", "tokens_out", "ts"} <= set(e)


def test_proxy_fixture_plants_the_credential_canary():
    # The canary exists so the CLI import test can prove the core
    # drops credential-named fields. It is a labelled fake, and it
    # must live in exactly this one input fixture.
    data = load_json(FIXTURES / "proxy-report.json")
    assert data["entries"][0]["api_key"] == CANARY


def test_bench_fixture_matches_real_bench_report_shape():
    data = load_json(FIXTURES / "bench-report.json")
    assert data["tool"] == "ghostbench"
    assert len(data["tasks"]) == 2
    full = sum(t["full_tokens"] for t in data["tasks"])
    assert full == data["totals"]["full_tokens"] == 6800
    for t in data["tasks"]:
        assert t["variants"]["full"]["tokens"] == t["full_tokens"]
        assert t["variants"]["sliced"]["tokens"] <= t["full_tokens"]
        assert t["project"] and t["task"]


def test_examples_inputs_are_internally_consistent():
    proxy = load_json(EXAMPLES / "inputs" / "proxy-report.json")
    assert proxy["requests"] == len(proxy["entries"]) == 2
    assert sum(e["tokens_in"] for e in proxy["entries"]) == proxy["tokens_in"]
    bench = load_json(EXAMPLES / "inputs" / "bench-report.json")
    assert sum(t["full_tokens"] for t in bench["tasks"]) == \
        bench["totals"]["full_tokens"]
