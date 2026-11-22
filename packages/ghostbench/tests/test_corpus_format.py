"""Corpus and report format tests, aligned to the core's documented
formats (src/ghostbench/corpus.py and report.py). The fixture-side
tests run with or without the core, so a broken fixture can never
hide behind a missing package.
"""

import re

from conftest import EXAMPLES, FIXTURES, load_json

CORPORA = [
    FIXTURES / "mini" / "corpus.json",
    EXAMPLES / "corpora" / "adversarial" / "corpus.json",
    EXAMPLES / "corpora" / "ghostbus" / "corpus.json",
    EXAMPLES / "corpus-template" / "corpus.json",
]

REQUIRED_TASK_FIELDS = {"id", "prompt", "expected_files", "expected_symbols",
                        "recorded_patch", "test_command"}


def _projects(data):
    assert isinstance(data.get("projects"), list) and data["projects"]
    return data["projects"]


def test_corpus_files_match_the_core_loader_shape():
    for path in CORPORA:
        data = load_json(path)
        assert isinstance(data.get("name"), str) and data["name"], path
        assert data.get("version") is not None, path
        seen = set()
        for project in _projects(data):
            assert project.get("id") and project.get("path"), path
            assert project["id"] not in seen, f"duplicate project id in {path}"
            seen.add(project["id"])
            task_ids = [t["id"] for t in project["tasks"]]
            assert len(task_ids) == len(set(task_ids)), f"duplicate task ids in {path}"


def test_every_task_carries_the_documented_fields():
    for path in CORPORA:
        data = load_json(path)
        for project in _projects(data):
            for task in project["tasks"]:
                missing = REQUIRED_TASK_FIELDS - set(task)
                assert not missing, f"{path} task {task.get('id')} missing {missing}"


def test_bundled_fixture_projects_and_expected_files_exist():
    for path in (FIXTURES / "mini" / "corpus.json",
                 EXAMPLES / "corpora" / "adversarial" / "corpus.json"):
        data = load_json(path)
        for project in _projects(data):
            project_dir = path.parent / project["path"]
            assert project_dir.is_dir(), f"{path}: project dir missing"
            for task in project["tasks"]:
                for rel in task["expected_files"]:
                    assert (project_dir / rel).exists(), f"{path}: {rel} missing"
                if task["recorded_patch"]:
                    assert (path.parent / task["recorded_patch"]).exists(), (
                        f"{path}: recorded patch {task['recorded_patch']} missing")
                if task.get("verify_report"):
                    assert (path.parent / task["verify_report"]).exists()


def test_ghostbus_corpus_points_at_the_real_tree_and_copies_nothing():
    path = EXAMPLES / "corpora" / "ghostbus" / "corpus.json"
    data = load_json(path)
    project = data["projects"][0]
    resolved = (path.parent / project["path"]).resolve()
    if not resolved.is_dir():
        # The corpus deliberately points at the real GhostBus tree
        # outside this repo (../../../../ghostbus). A standalone
        # checkout does not have it; CI's integration job provides
        # the sibling. Skip, never fake the tree.
        import pytest
        pytest.skip("GhostBus sibling tree not present "
                    "(integration-only assertion)")
    assert resolved.is_dir(), "GhostBus corpus path does not resolve to a real tree"
    assert (resolved / "src" / "tools.mjs").exists()
    # Reference GhostSlice totals for the tree live in the description,
    # recorded as estimates with their source.
    assert "129555" in data["description"] and "45770" in data["description"]
    for task in project["tasks"]:
        assert task["test_command"] == "node test.mjs"
        for rel in task["expected_files"]:
            assert (resolved / rel).exists(), f"ghostbus task expects missing {rel}"


def test_sample_reports_follow_the_core_report_format():
    for run in ("sample-tier-a-run-a", "sample-tier-a-run-b"):
        report = load_json(EXAMPLES / "runs" / run / "bench-report.json")
        assert report["tool"] == "ghostbench" and report["tier"] == "A"
        assert report["run_id"] and report["corpus"]["name"] == "adversarial"
        for stamp in ("tool_version", "slice_version", "estimator_version",
                      "price_table_date"):
            assert stamp in report, f"{run} missing stamp {stamp}"
        assert report["tasks"], f"{run} has no per-task rows"
        for row in report["tasks"]:
            assert row["full_tokens"] >= row["variants"]["sliced"]["tokens"] >= 0
            assert re.fullmatch(r"sha256:[0-9a-f]{64}",
                                row["variants"]["sliced"]["manifest_sha256"])
        assert report["sample"] is True
        bench_md = (EXAMPLES / "runs" / run / "BENCH.md").read_text()
        assert "SAMPLE" in bench_md and "Honest scope" in bench_md


def test_sample_bench_md_is_traceable_to_report_rows():
    for run in ("sample-tier-a-run-a", "sample-tier-a-run-b"):
        report = load_json(EXAMPLES / "runs" / run / "bench-report.json")
        bench_md = (EXAMPLES / "runs" / run / "BENCH.md").read_text()
        for row in report["tasks"]:
            assert row["task"] in bench_md
            assert row["variants"]["sliced"]["manifest_sha256"] in bench_md
            assert str(row["variants"]["sliced"]["tokens"]) in bench_md


def test_sample_runs_totals_match_their_rows():
    for run in ("sample-tier-a-run-a", "sample-tier-a-run-b"):
        report = load_json(EXAMPLES / "runs" / run / "bench-report.json")
        rows = report["tasks"]
        totals = report["totals"]
        assert totals["full_tokens"] == sum(r["full_tokens"] for r in rows)
        assert totals["variants"]["sliced"]["tokens"] == sum(
            r["variants"]["sliced"]["tokens"] for r in rows)
        assert totals["pass"] == sum(1 for r in rows if r["status"] == "pass")
        assert totals["fail"] == sum(1 for r in rows if r["status"] == "fail")
        assert totals["hard_gaps_predicted"] == sum(
            r["hard_gaps_predicted"] for r in rows)
