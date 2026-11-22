"""Hardening regression tests (improve lane, 2026-10-18).

Each test pins a real bug found by probing the core: a Tier B gate
bypass, silently mangled corpus fields, crashes (tracebacks) on
malformed user input instead of clean errors, token counts that
could go negative or escape the project tree, and a patch parser
that dropped file deletions. No live runs, no network, no spend.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from conftest import FIXTURES, copy_corpus, requires_core, run_cli  # noqa: E402
from ghostbench.corpus import CorpusError, load_corpus  # noqa: E402
from ghostbench.prices import estimate_input_cost_usd, load_price_table  # noqa: E402
from ghostbench.runner import _run_test_in_temp, read_ledger, run_task  # noqa: E402
from ghostbench.scoring import (manifest_tokens, normalise_verify_report,  # noqa: E402
                                parse_patch, saving_pct)
from ghostbench.tierb import TierBRefusal, check_budget, run_live_corpus  # noqa: E402


def _write_corpus(tmp_path, task_overrides=None, tasks_marker=None):
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    (proj / "a.py").write_text("x = 1\n")
    task = {"id": "t1", "prompt": "do it"}
    if task_overrides:
        task.update(task_overrides)
    data = {"name": "t", "version": "1",
            "projects": [{"id": "p", "path": "proj",
                          "tasks": tasks_marker if tasks_marker is not None
                          else [task]}]}
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(data))
    return path


# --- Tier B gates -------------------------------------------------

@requires_core
def test_live_run_refuses_without_a_configured_agent(tmp_path, monkeypatch):
    """The v0.1 bypass this section used to pin - an injected executor
    running while GHOSTBENCH_ENABLE_LIVE was off - has no analogue in
    the live-agent design: there is no executor injection and no
    enable switch. The agent command comes only from an explicit
    caller argument or GHOSTBENCH_AGENT_CMD; with neither present,
    run_live_corpus refuses before any task runs."""
    monkeypatch.delenv("GHOSTBENCH_AGENT_CMD", raising=False)
    corpus_dir = copy_corpus(FIXTURES / "mini", tmp_path / "mini")
    corpus = load_corpus(corpus_dir / "corpus.json")
    with pytest.raises(TierBRefusal, match="GHOSTBENCH_AGENT_CMD"):
        run_live_corpus(corpus)
    with pytest.raises(TierBRefusal):
        run_live_corpus(corpus, agent_cmd="   ")


@requires_core
def test_live_run_uses_the_configured_env_command(tmp_path, monkeypatch):
    """With GHOSTBENCH_AGENT_CMD set to a harmless stand-in, the run
    proceeds at live-agent level and records only the command's
    first token - never the full line, which may carry secrets in
    its arguments."""
    corpus_dir = copy_corpus(FIXTURES / "mini", tmp_path / "mini")
    corpus = load_corpus(corpus_dir / "corpus.json")
    monkeypatch.setenv("GHOSTBENCH_AGENT_CMD",
                       f"{sys.executable} -c pass --key NOT-RECORDED")
    report = run_live_corpus(corpus)
    assert report["tier"] == "B"
    assert report["verification_level"] == "live-agent"
    assert report["agent"]["name"] == sys.executable
    assert "NOT-RECORDED" not in json.dumps(report)
    assert all(r["verification_level"] == "live-agent"
               for r in report["tasks"])


def test_check_budget_rejects_bool_cap_and_negative_use():
    # bool is an int subclass: True used to pass as a cap of 1.
    assert check_budget({"budget_tokens": True}, 0) is False
    assert check_budget({"budget_tokens": 10}, -1) is False
    assert check_budget({"budget_tokens": 10}, 10) is True


# --- Scoring -------------------------------------------------------

def test_parse_patch_counts_deletions_and_creations_in_mixed_patch():
    patch = (
        "--- a/src/old.py\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-x\n"
        "--- a/src/mod.py\n+++ b/src/mod.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
        "--- /dev/null\n+++ b/src/new.py\n@@ -0,0 +1,1 @@\n+z\n"
    )
    info = parse_patch(patch)
    # The deleted file used to vanish whenever any other file was
    # also modified (old-name headers were a fallback only).
    assert info["files_touched"] == ["src/old.py", "src/mod.py", "src/new.py"]


def test_manifest_tokens_rejects_negative_bool_and_non_object(tmp_path):
    def write(payload):
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps(payload))
        return str(p)

    assert manifest_tokens(write({"totals": {"sliced_tokens": -500}})) is None
    assert manifest_tokens(write({"totals": {}, "files": [
        {"sliced_tokens": True}]})) is None
    assert manifest_tokens(write({"totals": {}, "files": [
        {"sliced_tokens": -3}, {"sliced_tokens": 10}]})) == 10
    assert manifest_tokens(write([1, 2, 3])) is None  # used to AttributeError
    assert manifest_tokens(write({"totals": [1]})) is None
    assert manifest_tokens(write({"totals": {"sliced_tokens": 42}})) == 42


def test_normalise_verify_report_never_splits_a_string_gap():
    out = normalise_verify_report({"hard_gaps": "oops"})
    assert out["hard_gaps"] == ["oops"]  # was ['o', 'o', 'p', 's']
    # A non-object report is 'not present', not an AttributeError.
    assert normalise_verify_report([1, 2])["present"] is False


def test_saving_pct_refuses_negative_counts():
    assert saving_pct(100, -50) is None  # was 150.0%


# --- Corpus loader validation --------------------------------------

@pytest.mark.parametrize("overrides", [
    {"budget_tokens": True},          # bool passed isinstance(int)
    {"budget_tokens": 0},
    {"expected_files": "a.py"},       # was split into ['a', '.', 'p', 'y']
    {"expected_symbols": "mean"},
    {"variants": [1, 2]},             # was a raw TypeError, not CorpusError
    {"variants": {"sliced": 42}},
    {"test_command": 123},            # crashed later in _run_test_in_temp
    {"prompt": 5},
    {"recorded_patch": 5},
])
def test_loader_rejects_mistyped_task_fields(tmp_path, overrides):
    path = _write_corpus(tmp_path, overrides)
    with pytest.raises(CorpusError):
        load_corpus(path)


def test_loader_rejects_non_list_tasks(tmp_path):
    path = _write_corpus(tmp_path, tasks_marker="oops")
    with pytest.raises(CorpusError, match="'tasks' must be a list"):
        load_corpus(path)


def test_verify_report_bad_json_or_non_object_is_corpus_error(tmp_path):
    for content in ("{not json", "[1, 2]"):
        path = _write_corpus(tmp_path, {"verify_report": "v.json"})
        (tmp_path / "v.json").write_text(content)
        corpus = load_corpus(path)
        project, task = next(corpus.all_tasks())
        with pytest.raises(CorpusError, match="verify_report"):
            run_task(corpus, project, task)


# --- Runner robustness ----------------------------------------------

def test_test_command_missing_binary_is_scored_not_a_crash(tmp_path):
    path = _write_corpus(
        tmp_path, {"test_command": "definitely-not-a-real-binary-xyz --x"})
    corpus = load_corpus(path)
    project, task = next(corpus.all_tasks())
    result = _run_test_in_temp(project, task, None)  # was FileNotFoundError
    assert result["status"] == "error"
    row = run_task(corpus, project, task, run_tests=True)
    assert row["status"] == "fail"


def test_test_command_unbalanced_quote_is_scored_not_a_crash(tmp_path):
    path = _write_corpus(tmp_path, {"test_command": 'python3 -c "unbalanced'})
    corpus = load_corpus(path)
    project, task = next(corpus.all_tasks())
    assert _run_test_in_temp(project, task, None)["status"] == "bad-test-command"


def test_suite_gates_extra_variants_and_slice_measures_none(tmp_path):
    path = _write_corpus(tmp_path, {
        "expected_files": ["a.py"],
        "variants": {"recalled": {"tokens": 42}, "verified": {"tokens": 43}}})
    corpus = load_corpus(path)
    project, task = next(corpus.all_tasks())
    # suite=slice used to include EVERY extra variant (the empty
    # wanted list was treated as 'no filter').
    assert sorted(run_task(corpus, project, task, suite="slice")["variants"]) \
        == ["full", "sliced"]
    assert "verified" in run_task(corpus, project, task, suite="verify")["variants"]
    assert "recalled" in run_task(corpus, project, task, suite="recall")["variants"]
    with pytest.raises(ValueError, match="unknown suite"):
        run_task(corpus, project, task, suite="bogus")  # was a bare KeyError


def test_expected_files_cannot_escape_the_project_tree(tmp_path):
    (tmp_path / "outside.py").write_text("y = 2 # " + "z " * 100 + "\n")
    path = _write_corpus(tmp_path, {
        "expected_files": ["../outside.py", "/etc/hostname", "a.py"]})
    corpus = load_corpus(path)
    project, task = next(corpus.all_tasks())
    row = run_task(corpus, project, task)
    # Only a.py (inside the project) may be counted; the escaping
    # entries used to be read and produced a -2866% 'saving'.
    assert row["variants"]["sliced"]["tokens"] == row["full_tokens"]


def test_negative_provided_variant_tokens_are_undetermined(tmp_path):
    path = _write_corpus(tmp_path, {"variants": {"sliced": {"tokens": -5}}})
    corpus = load_corpus(path)
    project, task = next(corpus.all_tasks())
    row = run_task(corpus, project, task)
    assert row["variants"]["sliced"]["tokens"] is None
    assert any("could not be determined" in f for f in row["failures"])


def test_read_ledger_survives_a_torn_line(tmp_path):
    ledger = tmp_path / "history.jsonl"
    ledger.write_text('{"a": 1}\nnot json\n[1, 2]\n{"b": 2}\n')
    assert read_ledger(str(ledger)) == [{"a": 1}, {"b": 2}]


# --- Prices ----------------------------------------------------------

def test_price_table_with_wrong_shape_json_falls_back(tmp_path, monkeypatch):
    bad = tmp_path / "prices.json"
    bad.write_text("[1, 2]")  # valid JSON, not a table: was a TypeError
    monkeypatch.setenv("GHOSTBENCH_PRICES", str(bad))
    table = load_price_table()
    assert isinstance(table, dict)


def test_estimate_cost_survives_malformed_model_entries():
    table = {"models": ["oops", {"id": "m", "input_per_mtok_usd": "abc"}]}
    assert estimate_input_cost_usd(1000, "m", table) is None
    table = {"models": ["oops", {"id": "m", "input_per_mtok_usd": 3.0}]}
    assert estimate_input_cost_usd(1_000_000, "m", table) == 3.0
    assert estimate_input_cost_usd(-5, "m", table) is None


# --- CLI: clean errors, no tracebacks, no partial artifacts ----------

@requires_core
def test_cli_run_with_unknown_task_filter_writes_nothing(tmp_path):
    corpus_dir = copy_corpus(FIXTURES / "mini", tmp_path / "mini")
    out = tmp_path / "out"
    proc = run_cli(["run", corpus_dir / "corpus.json", "--task", "no-such",
                    "--out", out, "--no-ledger"])
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr
    assert "no tasks" in proc.stderr
    assert not out.exists(), "partial report artifacts were left behind"


@requires_core
@pytest.mark.parametrize("args_builder", [
    lambda tmp: ["compare", tmp / "missing-a.json", tmp / "missing-b.json"],
    lambda tmp: ["compare", tmp / "bad.json", tmp / "bad.json"],
    lambda tmp: ["compare", tmp / "notreport.json", tmp / "notreport.json"],
    lambda tmp: ["add", tmp / "corrupt.json", "--project", ".", "--id", "x"],
    lambda tmp: ["add", tmp / "list.json", "--project", ".", "--id", "x"],
])
def test_cli_bad_inputs_exit_2_without_traceback(tmp_path, args_builder):
    (tmp_path / "bad.json").write_text("{oops")
    (tmp_path / "notreport.json").write_text('{"hello": 1}')
    (tmp_path / "corrupt.json").write_text("not json")
    (tmp_path / "list.json").write_text("[1, 2]")
    proc = run_cli(args_builder(tmp_path))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr
    assert "error:" in proc.stderr
