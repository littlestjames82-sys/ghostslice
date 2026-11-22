"""Tier A runner tests: black-box CLI tests against the core contract
(`ghostbench run <corpus.json> [--suite ...] [--out DIR]`). No test in
this file performs a live (Tier B) run.
"""

import json

from conftest import EXAMPLES, FIXTURES, load_json, requires_core, run_cli, copy_corpus

MINI = FIXTURES / "mini" / "corpus.json"
ADV = EXAMPLES / "corpora" / "adversarial" / "corpus.json"


def _run(corpus_src_dir, corpus_file_name, tmp_path, *extra):
    corpus_dir = copy_corpus(corpus_src_dir, tmp_path / "corpus")
    out = tmp_path / "run"
    proc = run_cli(["run", corpus_dir / corpus_file_name, "--out", out, *extra])
    return proc, corpus_dir, out


@requires_core
def test_tier_a_run_on_mini_produces_a_traceable_report(tmp_path):
    proc, _cdir, out = _run(FIXTURES / "mini", "corpus.json", tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = load_json(out / "bench-report.json")
    assert (out / "BENCH.md").exists()
    assert report["tier"] == "A" and report["corpus"]["name"] == "mini"
    for stamp in ("tool_version", "estimator_version", "price_table_date"):
        assert report[stamp] or stamp == "price_table_date", f"report missing {stamp}"
    assert "slice_version" in report and "estimator_source" in report
    rows = {row["task"]: row for row in report["tasks"]}
    assert set(rows) == {"mini-001-fix-mean", "mini-002-summarise-report"}
    for row in rows.values():
        assert row["full_tokens"] > 0
        sliced = row["variants"]["sliced"]
        assert 0 <= sliced["tokens"] <= row["full_tokens"]
        assert sliced["source"] == "derived:expected-files"
        assert row["project_tree_hash"].startswith("sha256:")
    assert any(r["variants"]["sliced"]["tokens"] < r["full_tokens"]
               for r in rows.values()), "sliced arm never smaller on the mini corpus"


@requires_core
def test_tier_a_run_is_deterministic_on_tokens(tmp_path):
    reports = []
    for i in (1, 2):
        proc, _cdir, out = _run(FIXTURES / "mini", "corpus.json", tmp_path / f"case{i}")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        reports.append(load_json(out / "bench-report.json"))
    tokens = [
        {r["task"]: (r["full_tokens"], r["variants"]["sliced"]["tokens"])
         for r in rep["tasks"]}
        for rep in reports
    ]
    assert tokens[0] == tokens[1], "same corpus + versions must give same token numbers"


@requires_core
def test_tier_a_adversarial_run_surfaces_at_least_one_failure(tmp_path):
    """PLAN honesty bar: a correct run of the adversarial corpus cannot
    be all-green. adv-002's Verify report predicts a hard gap and its
    recorded patch references a missing symbol."""
    proc, _cdir, out = _run(EXAMPLES / "corpora" / "adversarial", "corpus.json", tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = load_json(out / "bench-report.json")
    rows = {row["task"]: row for row in report["tasks"]}
    assert rows["adv-001-fix-missing-route"]["status"] == "pass"
    broken = rows["adv-002-broken-patch-missing-symbol"]
    assert broken["status"] == "fail"
    assert broken["hard_gaps_predicted"] >= 1
    assert report["totals"]["fail"] >= 1
    assert report["failures_visible"], "failures must be visible in the report"


@requires_core
def test_tier_a_bench_md_has_per_task_rows_and_honest_scope(tmp_path):
    proc, _cdir, out = _run(FIXTURES / "mini", "corpus.json", tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    bench_md = (out / "BENCH.md").read_text()
    assert "mini-001-fix-mean" in bench_md and "mini-002-summarise-report" in bench_md
    assert "## Honest scope" in bench_md
    assert "## Failures (all shown)" in bench_md


@requires_core
def test_run_rejects_a_bogus_corpus(tmp_path):
    proc = run_cli(["run", tmp_path / "no-such-corpus.json", "--out", tmp_path / "out"])
    assert proc.returncode == 2
    assert "corpus" in (proc.stdout + proc.stderr).lower()


@requires_core
def test_ledger_records_the_run_with_version_stamps(tmp_path):
    proc, corpus_dir, _out = _run(FIXTURES / "mini", "corpus.json", tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    ledger = corpus_dir / ".ghostbench-history.jsonl"
    assert ledger.exists(), "ledger not written next to the corpus file"
    records = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
    assert records and records[-1]["corpus"] == "mini"
    assert records[-1]["estimator_version"] and records[-1]["run_id"]
    assert records[-1]["totals"]["full_tokens"] > 0
