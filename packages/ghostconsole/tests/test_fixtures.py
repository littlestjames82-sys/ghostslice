"""Fixture-validity tests: the report trees the CLI tests rely on are
well-formed and carry the fields the plan's adapters read. These run
with no CLI present."""
from __future__ import annotations

import json

from conftest import (APPROVE_PENDING, APPROVE_REQUESTS, BENCH_TASKS_FAILED,
                      BENCH_TASKS_TOTAL, SLICE_AFTER, SLICE_BEFORE,
                      VERIFY_HARD_GAPS, attention_project, empty_project,
                      healthy_project, stale_project)


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path):
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_healthy_fixture_shapes(tmp_path):
    p = healthy_project(tmp_path)
    hist = _jsonl(p / ".ghostslice-history.jsonl")
    assert hist[-1]["before_tokens"] == SLICE_BEFORE
    assert hist[-1]["after_tokens"] == SLICE_AFTER
    man = _json(p / "bundle" / "manifest.json")
    assert man["total_original_tokens"] == SLICE_BEFORE
    assert man["total_sliced_tokens"] == SLICE_AFTER
    vhist = _jsonl(p / ".ghostverify-history.jsonl")
    assert vhist[-1]["verdict"] == "sufficient"
    vrep = _json(p / "bundle" / "verify-report.json")
    assert vrep["verdict"] == "sufficient" and vrep["gaps"] == []
    brep = _json(p / "runs" / "bench-report.json")
    assert len(brep["tasks"]) == BENCH_TASKS_TOTAL
    led = _json(p / "ledger-report.json")
    assert led["loop_warnings"] == []
    watch = _json(p / "watch" / "watch-report.json")
    assert watch["verdict"] == "fresh"


def test_attention_fixture_shapes(tmp_path):
    p = attention_project(tmp_path)
    vhist = _jsonl(p / ".ghostverify-history.jsonl")
    assert vhist[-1]["verdict"] == "gaps_found"
    assert vhist[-1]["hard_gaps"] == VERIFY_HARD_GAPS
    reqs = sorted((p / ".ghostapprove" / "requests").glob("*.json"))
    assert len(reqs) == APPROVE_REQUESTS
    decided = _jsonl(p / ".ghostapprove" / "ledger.jsonl")
    assert APPROVE_REQUESTS - len(decided) == APPROVE_PENDING == 2


def test_stale_and_empty_fixture_shapes(tmp_path):
    s = stale_project(tmp_path)
    assert _json(s / "watch" / "watch-report.json")["verdict"] == "stale"
    e = empty_project(tmp_path)
    assert not list(e.rglob("*.jsonl"))
    assert not list(e.rglob("verify-report.json"))
    assert not list(e.rglob("manifest.json"))
