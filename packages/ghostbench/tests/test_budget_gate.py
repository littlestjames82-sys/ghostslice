"""Tier B live gate tests. PLAN.md hard rule: Bench never spends
silently - and, since the live-agent build (Oct 18, 2026), never
runs an agent it was not configured to run.

The v0.1 gate model this file used to pin (a positive --budget cap,
--confirm after a printed preflight, GHOSTBENCH_ENABLE_LIVE=1, one
hardcoded --agent, and no executor wired at all) was REPLACED by
the live-agent design: the agent command comes only from
GHOSTBENCH_AGENT_CMD, Bench hardcodes no vendor and has no default
agent, and the configuration gate is a single refusal - with no
agent configured, `ghostbench live` exits 2 before anything runs
and writes nothing.

On top of that gate, the budget cap came back (Oct 18, 2026, at
Ryan's direction) as a second, independent gate: `live --budget
TOKENS` checks the run's ESTIMATED context tokens (the sum of the
per-task full-context estimates, decided by tierb.check_budget)
before any agent runs; over the cap it refuses and writes nothing
unless --confirm is given, and the report records cap, estimate,
and confirmation. The cap meters Bench's estimate in tokens only -
the configured agent's real charges happen inside the user's own
program and are never metered. These tests pin both refusals at
the CLI level and the estimate math at the unit level. The
behaviour of a configured run (with fake agents only) is pinned in
tests/test_live_agent.py.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from conftest import FIXTURES, requires_core, run_cli, copy_corpus

from ghostbench.corpus import load_corpus  # noqa: E402
from ghostbench.tierb import (TierBRefusal, budget_gate,  # noqa: E402
                              check_budget,
                              estimate_live_run_tokens)

MINI = "corpus.json"
PY = sys.executable

FIXER = (
    "import os\n"
    "task_dir = os.environ['GHOSTBENCH_TASK_DIR']\n"
    "with open(os.path.join(task_dir, 'calc.py'), 'w') as fh:\n"
    "    fh.write('def add(a, b):\\n    return a + b\\n')\n"
)


def _write_probe(tmp_path):
    """A one-task corpus whose project the FIXER agent can fix,
    plus the agent command that fixes it. Returns (corpus_path,
    agent_cmd, estimate)."""
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "calc.py").write_text(
        "def add(a, b):\n    return a - b  # the bug\n")
    (proj / "check.py").write_text(
        "from calc import add\nassert add(2, 3) == 5\n")
    agent = tmp_path / "fixer.py"
    agent.write_text(FIXER)
    corpus = {
        "name": "budget-probe", "version": "1",
        "projects": [{"id": "probe", "path": "proj", "tasks": [{
            "id": "fix-add",
            "prompt": "Fix the add function in calc.py",
            "expected_files": ["calc.py"],
            "expected_symbols": ["add"],
            "test_command": [PY, "check.py"],
        }]}],
    }
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(corpus))
    estimate = estimate_live_run_tokens(load_corpus(path))
    assert estimate > 1, "probe corpus must have a usable estimate"
    return path, f"{PY} {agent}", estimate


@requires_core
def test_live_refuses_without_an_agent_command(tmp_path):
    corpus_dir = copy_corpus(FIXTURES / "mini", tmp_path / "mini")
    proc = run_cli(["live", corpus_dir / MINI], stdin="",
                   env_remove=("GHOSTBENCH_AGENT_CMD",))
    combined = (proc.stdout + proc.stderr).lower()
    assert proc.returncode == 2, "live did not refuse with no agent configured"
    assert "no agent is configured" in combined
    assert "ghostbench_agent_cmd" in combined
    # The refusal happens before anything runs: no run folder, no
    # report, no ledger record was written anywhere.
    assert not (corpus_dir / "runs").exists()
    assert not (corpus_dir / ".ghostbench-history.jsonl").exists()


@requires_core
def test_live_refuses_with_an_empty_agent_command(tmp_path):
    corpus_dir = copy_corpus(FIXTURES / "mini", tmp_path / "mini")
    proc = run_cli(["live", corpus_dir / MINI], stdin="",
                   env_extra={"GHOSTBENCH_AGENT_CMD": "   "})
    combined = (proc.stdout + proc.stderr).lower()
    assert proc.returncode == 2
    assert "no agent is configured" in combined
    assert not (corpus_dir / "runs").exists()


@requires_core
def test_live_help_documents_the_agent_contract(tmp_path):
    """--help is where the configuration contract lives: the env
    var, the three task variables, the timeout flag, and the
    first-token-only recording rule."""
    proc = run_cli(["live", "--help"])
    assert proc.returncode == 0
    text = " ".join(proc.stdout.split())  # unwrap argparse's lines
    for needle in ("GHOSTBENCH_AGENT_CMD", "GHOSTBENCH_TASK_DIR",
                   "GHOSTBENCH_TASK_ID", "GHOSTBENCH_TASK_PROMPT",
                   "--agent-timeout", "first token"):
        assert needle in text, f"live --help does not document {needle}"


# --- The restored budget cap (second gate) -------------------------

@requires_core
def test_estimate_math_pinned_against_check_budget(tmp_path):
    """The gate's estimate is check_budget's native unit (tokens):
    a cap at exactly the estimate passes check_budget, one token
    under it does not, and the estimate equals the full_tokens
    total a real run later reports."""
    corpus_path, agent_cmd, estimate = _write_probe(tmp_path)
    assert check_budget({"budget_tokens": estimate}, estimate) is True
    assert check_budget({"budget_tokens": estimate - 1},
                        estimate) is False
    from ghostbench.tierb import run_live_corpus
    report = run_live_corpus(load_corpus(corpus_path),
                             agent_cmd=agent_cmd)
    assert report["totals"]["full_tokens"] == estimate


@requires_core
def test_budget_gate_unit_behaviour(tmp_path):
    corpus_path, _agent, estimate = _write_probe(tmp_path)
    corpus = load_corpus(corpus_path)
    # No cap: the unset record, and confirmed defaults to False.
    assert budget_gate(corpus) == {
        "budget_cap": None, "budget_estimate": None,
        "budget_confirmed": False, "exceeded": False}
    # Under the cap (estimate <= cap is within budget): proceeds.
    rec = budget_gate(corpus, budget_cap=estimate)
    assert rec["budget_estimate"] == estimate
    assert rec["exceeded"] is False
    # Over the cap without confirm: refusal naming both numbers.
    with pytest.raises(TierBRefusal) as excinfo:
        budget_gate(corpus, budget_cap=estimate - 1)
    assert str(estimate) in str(excinfo.value)
    assert str(estimate - 1) in str(excinfo.value)
    assert "--confirm" in str(excinfo.value)
    # Over the cap with confirm: proceeds, marked as exceeded.
    rec = budget_gate(corpus, budget_cap=estimate - 1, confirmed=True)
    assert rec["exceeded"] is True and rec["budget_confirmed"] is True
    # A non-positive cap is a refusal, not a silent pass.
    with pytest.raises(TierBRefusal):
        budget_gate(corpus, budget_cap=0)


@requires_core
def test_live_over_budget_refuses_and_writes_nothing(tmp_path):
    corpus_path, agent_cmd, estimate = _write_probe(tmp_path)
    out = tmp_path / "out"
    proc = run_cli(
        ["live", corpus_path, "--out", out,
         "--budget", str(estimate - 1)],
        env_extra={"GHOSTBENCH_AGENT_CMD": agent_cmd})
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 2, "over-budget live run did not refuse"
    assert "budget cap exceeded" in combined
    assert str(estimate) in combined
    assert str(estimate - 1) in combined
    assert "--budget" in combined and "--confirm" in combined
    # Same discipline as the configuration refusal: nothing written.
    assert not out.exists()
    assert not (tmp_path / ".ghostbench-history.jsonl").exists()
    # And the agent never ran: the project still has the bug.
    assert "a - b" in (tmp_path / "proj" / "calc.py").read_text()


@requires_core
def test_live_over_budget_with_confirm_runs_and_records(tmp_path):
    corpus_path, agent_cmd, estimate = _write_probe(tmp_path)
    out = tmp_path / "out"
    proc = run_cli(
        ["live", corpus_path, "--out", out,
         "--budget", str(estimate - 1), "--confirm"],
        env_extra={"GHOSTBENCH_AGENT_CMD": agent_cmd})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads((out / "bench-report.json").read_text())
    assert report["budget_cap"] == estimate - 1
    assert report["budget_estimate"] == estimate
    assert report["budget_confirmed"] is True
    assert report["totals"]["pass"] == 1
    bench_md = (out / "BENCH.md").read_text()
    assert "Budget cap" in bench_md and "--confirm" in bench_md


@requires_core
def test_live_under_budget_runs_without_confirm(tmp_path):
    corpus_path, agent_cmd, estimate = _write_probe(tmp_path)
    out = tmp_path / "out"
    proc = run_cli(
        ["live", corpus_path, "--out", out, "--budget", str(estimate)],
        env_extra={"GHOSTBENCH_AGENT_CMD": agent_cmd})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads((out / "bench-report.json").read_text())
    assert report["budget_cap"] == estimate
    assert report["budget_estimate"] == estimate
    assert report["budget_confirmed"] is False


@requires_core
def test_live_without_budget_records_cap_unset(tmp_path):
    corpus_path, agent_cmd, _estimate = _write_probe(tmp_path)
    out = tmp_path / "out"
    proc = run_cli(["live", corpus_path, "--out", out],
                   env_extra={"GHOSTBENCH_AGENT_CMD": agent_cmd})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads((out / "bench-report.json").read_text())
    assert report["budget_cap"] is None
    assert report["budget_estimate"] is None
    assert report["budget_confirmed"] is False
    assert "Budget cap: none set" in (out / "BENCH.md").read_text()


@requires_core
def test_live_help_documents_the_budget_cap(tmp_path):
    proc = run_cli(["live", "--help"])
    assert proc.returncode == 0
    text = " ".join(proc.stdout.split())
    for needle in ("--budget", "--confirm", "estimate"):
        assert needle in text, f"live --help does not document {needle}"
