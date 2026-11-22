"""Expected-symbol coverage (deepen lane).

The corpus format has always carried `expected_symbols`, and the
loader has always parsed them, but Tier A never scored them: a slice
derived from a task's expected_files could silently omit the very
symbol the task is about and still pass. These tests pin the new
behaviour:

- score_expected_symbols is a lexical whole-word check against the
  expected files' text (dotted names match by full name or leaf);
- a missing symbol gates the task ONLY when the sliced arm is the
  derived expected-files arm (a provided bundle cannot be inspected,
  so it is reported, not gated);
- the patch added-lines symbol check is informational only.
"""

import json
import sys
from pathlib import Path

from conftest import EXAMPLES, FIXTURES, SRC, load_json, requires_core, run_cli, copy_corpus

sys.path.insert(0, str(SRC))
from ghostbench.scoring import patch_added_text, score_expected_symbols  # noqa: E402


# ---------------------------------------------------------------- unit

def test_found_missing_and_coverage():
    score = score_expected_symbols(
        ["mean", "add", "missing_fn"],
        {"stats.py": "def mean(values):\n    return add(1, 2)\n"})
    assert score["found_in_expected_files"] == ["mean", "add"]
    assert score["missing_from_expected_files"] == ["missing_fn"]
    assert score["coverage_pct"] == 66.7


def test_substring_does_not_count_as_present():
    score = score_expected_symbols(["mean"], {"a.py": "meaningful = True\n"})
    assert score["missing_from_expected_files"] == ["mean"]
    score = score_expected_symbols(["mean"], {"a.py": "x = mean(values)\n"})
    assert score["found_in_expected_files"] == ["mean"]


def test_dotted_symbol_matches_leaf_or_full_name():
    by_leaf = score_expected_symbols(["Pair.swap"], {"a.py": "def swap(self):\n"})
    assert by_leaf["found_in_expected_files"] == ["Pair.swap"]
    by_full = score_expected_symbols(["Pair.swap"], {"a.py": "Pair.swap(p)\n"})
    assert by_full["found_in_expected_files"] == ["Pair.swap"]
    neither = score_expected_symbols(["Pair.swap"], {"a.py": "def other():\n"})
    assert neither["missing_from_expected_files"] == ["Pair.swap"]


def test_patch_check_counts_added_lines_only_and_is_informational():
    patch = (
        "--- a/shop/helpers.py\n"
        "+++ b/shop/helpers.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def route(name):\n"
        "-    return old_dispatch(name)\n"
        "+    return dispatch(name)\n"
    )
    assert patch_added_text(patch).strip() == "return dispatch(name)"
    score = score_expected_symbols(
        ["dispatch", "route"], {"helpers.py": "def dispatch(n):\n"}, patch)
    # 'route' appears only in a context line, not an added line.
    assert score["in_patch_added_lines"] == ["dispatch"]
    assert score["missing_from_patch_added_lines"] == ["route"]
    assert score["patch_check_informational_only"] is True


def test_no_patch_and_no_symbols_are_explicit_nulls():
    score = score_expected_symbols([], {"a.py": "anything\n"}, None)
    assert score["coverage_pct"] is None
    assert score["in_patch_added_lines"] is None
    assert score["missing_from_patch_added_lines"] is None


# ------------------------------------------------------- integration

def _run(corpus_src_dir, tmp_path, *extra):
    corpus_dir = copy_corpus(corpus_src_dir, tmp_path / "corpus")
    out = tmp_path / "run"
    proc = run_cli(["run", corpus_dir / "corpus.json", "--out", out, *extra])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return load_json(out / "bench-report.json"), (out / "BENCH.md").read_text()


@requires_core
def test_mini_run_scores_symbols_at_full_coverage(tmp_path):
    report, bench_md = _run(FIXTURES / "mini", tmp_path)
    for row in report["tasks"]:
        assert row["symbols_score"]["coverage_pct"] == 100.0
        assert row["symbols_score"]["missing_from_expected_files"] == []
        assert row["symbols_score"]["applies_to_sliced"] is True
    assert report["totals"]["expected_symbols"] == 4
    assert report["totals"]["symbols_found"] == 4
    assert report["totals"]["symbol_coverage_pct"] == 100.0
    assert report["totals"]["tasks_with_missing_symbols"] == 0
    assert "Expected symbols found in expected files: 4/4" in bench_md


def _write_gap_corpus(tmp_path, variants=None):
    """Project where the needed symbol lives OUTSIDE expected_files:
    the recorded patch is otherwise good (touches the expected file),
    so only the symbol check can catch the slice gap."""
    root = tmp_path / "gapcorpus"
    proj = root / "project"
    proj.mkdir(parents=True)
    (proj / "a.py").write_text("def used_fn():\n    return 1\n")
    (proj / "b.py").write_text("def needed_fn():\n    return 2\n")
    (root / "fix.diff").write_text(
        "--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n"
        " def used_fn():\n-    return 1\n+    return used_fn() + 0\n")
    task = {
        "id": "gap-001", "prompt": "Use needed_fn from a.py",
        "expected_files": ["a.py"], "expected_symbols": ["needed_fn"],
        "recorded_patch": "fix.diff", "test_command": None,
    }
    if variants:
        task["variants"] = variants
    (root / "corpus.json").write_text(json.dumps({
        "name": "gap", "version": "1",
        "projects": [{"id": "gap", "path": "project", "tasks": [task]}]}))
    return root


def _run_dir(root, tmp_path):
    out = tmp_path / "out"
    proc = run_cli(["run", root / "corpus.json", "--out", out])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return load_json(out / "bench-report.json")


@requires_core
def test_symbol_missing_from_derived_slice_fails_visibly(tmp_path):
    report = _run_dir(_write_gap_corpus(tmp_path / "c"), tmp_path)
    row = report["tasks"][0]
    assert row["symbols_score"]["missing_from_expected_files"] == ["needed_fn"]
    assert row["status"] == "fail"
    assert any("needed_fn" in f and "sliced context" in f
               for f in row["failures"])
    assert report["totals"]["tasks_with_missing_symbols"] == 1
    assert report["totals"]["symbol_coverage_pct"] == 0.0
    assert report["failures_visible"], "the slice gap must be visible"


@requires_core
def test_provided_bundle_is_reported_not_gated_on_symbols(tmp_path):
    root = _write_gap_corpus(tmp_path / "c", variants={"sliced": {"tokens": 10}})
    report = _run_dir(root, tmp_path)
    row = report["tasks"][0]
    assert row["symbols_score"]["applies_to_sliced"] is False
    assert row["symbols_score"]["missing_from_expected_files"] == ["needed_fn"]
    assert row["status"] == "pass", (
        "a provided bundle cannot be inspected: Bench reports the "
        "expected-files gap descriptively and must not gate on it")
    assert not any("sliced context" in f for f in row["failures"])


@requires_core
def test_adversarial_symbol_scores_do_not_change_known_outcomes(tmp_path):
    report, _md = _run(EXAMPLES / "corpora" / "adversarial", tmp_path)
    rows = {r["task"]: r for r in report["tasks"]}
    adv1 = rows["adv-001-fix-missing-route"]
    assert adv1["symbols_score"]["found_in_expected_files"] == ["dispatch"]
    assert adv1["status"] == "pass"
    assert rows["adv-002-broken-patch-missing-symbol"]["status"] == "fail"
    # adv-004 expects price_order, which pricing.py defines.
    assert rows["adv-004-dedupe-pricing"]["symbols_score"][
        "found_in_expected_files"] == ["price_order"]
