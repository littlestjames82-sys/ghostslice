"""Tier B live-agent tests (live-agent build, Oct 18, 2026).

Every agent here is a FAKE: a small script the test writes into a
temp dir. No vendor agent, no network, no model. What is pinned:

1. with no agent configured (GHOSTBENCH_AGENT_CMD unset/empty),
   a live run refuses before anything runs;
2. a fake agent that makes the fixing change scores pass, with
   verification_level "live-agent" on the report and every row;
3. a fake agent that does nothing scores fail (no changes) - the
   level still says live-agent, because the level states what ran,
   not whether it worked;
4. a fake agent that crashes records its exit code and fails;
5. a fake agent that overruns --agent-timeout is recorded as
   timed out and fails;
6. secret hygiene: the full agent command line (which may carry a
   key in its arguments) never reaches the report - only the first
   token is recorded - and a secret planted in the parent
   environment never reaches the agent's environment;
7. a project symlink escaping the project is skipped and recorded
   on the live path, exactly as on Tier A.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from conftest import requires_core, run_cli  # noqa: E402
from ghostbench.corpus import load_corpus  # noqa: E402
from ghostbench.report import render_bench_md  # noqa: E402
from ghostbench.tierb import (AGENT_CMD_ENV, TierBRefusal,  # noqa: E402
                              run_live_corpus)

PY = sys.executable
SECRET = "probe-secret-value-99887"
OUTSIDE_MARKER = "PROBE-OUTSIDE-CONTENT-6789"

BUGGY_CALC = "def add(a, b):\n    return a - b  # the bug\n"
FIXED_CALC = "def add(a, b):\n    return a + b\n"
CHECK = ("from calc import add\n"
         "assert add(2, 3) == 5, 'add is broken'\n"
         "print('checks pass')\n")

FIXER = (
    "import os, sys\n"
    "task_dir = os.environ['GHOSTBENCH_TASK_DIR']\n"
    "assert sys.argv[-1] == task_dir, 'task dir must be the final argument'\n"
    "assert os.environ['GHOSTBENCH_TASK_ID'] == 'fix-add'\n"
    "assert 'add' in os.environ['GHOSTBENCH_TASK_PROMPT']\n"
    "with open(os.path.join(task_dir, 'calc.py'), 'w') as fh:\n"
    "    fh.write('def add(a, b):\\n    return a + b\\n')\n"
    "print('fixed add')\n"
)

NOOP = "print('agent did nothing')\n"

CRASHER = "import sys\nprint('about to crash')\nsys.exit(3)\n"

SLEEPER = "import time\ntime.sleep(60)\n"


def _write_corpus(tmp_path, calc_text=BUGGY_CALC):
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "calc.py").write_text(calc_text)
    (proj / "check.py").write_text(CHECK)
    corpus = {
        "name": "live-probe", "version": "1",
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
    return load_corpus(path), proj


def _write_agent(tmp_path, name, body):
    script = tmp_path / name
    script.write_text(body)
    return f"{PY} {script}"


# --- 1. Unconfigured: refuse before anything runs ---------------------

@requires_core
def test_live_refuses_when_no_agent_is_configured(tmp_path, monkeypatch):
    monkeypatch.delenv(AGENT_CMD_ENV, raising=False)
    corpus, _proj = _write_corpus(tmp_path)
    with pytest.raises(TierBRefusal, match="GHOSTBENCH_AGENT_CMD"):
        run_live_corpus(corpus)
    with pytest.raises(TierBRefusal):
        run_live_corpus(corpus, agent_cmd="")
    with pytest.raises(TierBRefusal):
        run_live_corpus(corpus, agent_cmd="   ")


# --- 2. A fixing fake agent passes, at live-agent level ----------------

@requires_core
def test_fixing_agent_passes_with_live_agent_level(tmp_path):
    corpus, proj = _write_corpus(tmp_path)
    agent_cmd = _write_agent(tmp_path, "fixer.py", FIXER)
    report = run_live_corpus(corpus, agent_cmd=agent_cmd)

    assert report["tier"] == "B"
    assert report["verification_level"] == "live-agent"
    assert report["totals"]["pass"] == 1
    assert report["totals"]["fail"] == 0

    row = report["tasks"][0]
    assert row["status"] == "pass"
    assert row["verification_level"] == "live-agent"
    assert row["agent_name"] == PY  # first token of the command only
    assert row["agent_exit_code"] == 0
    assert row["agent_timed_out"] is False
    assert row["files_changed"] >= 1
    assert "calc.py" in row["files_changed_paths"]
    assert "calc.py" in row["files_modified"]
    assert row["test"]["ran"] is True
    assert row["test"]["status"] == "pass"
    assert "fixed add" in row["agent_output_tail"]
    # The agent worked in a copy: the real project still has the bug.
    assert (proj / "calc.py").read_text() == BUGGY_CALC


@requires_core
def test_live_report_renders_in_bench_md(tmp_path):
    corpus, _proj = _write_corpus(tmp_path)
    agent_cmd = _write_agent(tmp_path, "fixer.py", FIXER)
    report = run_live_corpus(corpus, agent_cmd=agent_cmd)
    md = render_bench_md(report)
    first_screen = "\n".join(md.splitlines()[:14])
    assert "Tier: B" in first_screen
    assert "Verification level: live-agent" in first_screen
    assert "a real agent attempted the tasks" in first_screen
    # The containment honesty is on the page, not only in the JSON.
    assert "NOT prevented" in md
    assert "network access is NOT blocked" in md


# --- 3. A do-nothing agent fails; the level still says what ran --------

@requires_core
def test_noop_agent_fails_even_when_tests_would_pass(tmp_path):
    # The project starts CORRECT here: tests pass on the pristine
    # tree, so the only possible verdict driver is the no-change
    # rule itself.
    corpus, _proj = _write_corpus(tmp_path, calc_text=FIXED_CALC)
    agent_cmd = _write_agent(tmp_path, "noop.py", NOOP)
    report = run_live_corpus(corpus, agent_cmd=agent_cmd)
    row = report["tasks"][0]
    assert row["test"]["status"] == "pass"
    assert row["files_changed"] == 0
    assert row["status"] == "fail"
    assert any("no changes" in f for f in row["failures"])
    assert row["verification_level"] == "live-agent"
    assert report["verification_level"] == "live-agent"
    assert report["totals"]["fail"] == 1


# --- 4. A crashing agent fails with its exit code recorded -------------

@requires_core
def test_crashing_agent_fails_with_exit_code_recorded(tmp_path):
    corpus, _proj = _write_corpus(tmp_path)
    agent_cmd = _write_agent(tmp_path, "crasher.py", CRASHER)
    report = run_live_corpus(corpus, agent_cmd=agent_cmd)
    row = report["tasks"][0]
    assert row["status"] == "fail"
    assert row["agent_exit_code"] == 3
    assert row["agent_timed_out"] is False
    assert any("code 3" in f for f in row["failures"])
    assert row["verification_level"] == "live-agent"


@requires_core
def test_agent_that_changes_files_but_exits_nonzero_can_still_pass(tmp_path):
    """The design's pass rule is 'the agent exited 0 (or produced
    changes) AND the contained tests pass': a nonzero exit is
    rescued by a real, test-passing change - and the exit code is
    still recorded on the row, never hidden."""
    body = FIXER + "import sys\nsys.exit(3)\n"
    corpus, _proj = _write_corpus(tmp_path)
    agent_cmd = _write_agent(tmp_path, "fixer_crash.py", body)
    report = run_live_corpus(corpus, agent_cmd=agent_cmd)
    row = report["tasks"][0]
    assert row["files_changed"] >= 1
    assert row["test"]["status"] == "pass"
    assert row["agent_exit_code"] == 3
    assert row["status"] == "pass"


# --- 5. A slow agent is timed out and fails ------------------------------

@requires_core
def test_agent_timeout_is_recorded_and_fails(tmp_path):
    corpus, _proj = _write_corpus(tmp_path)
    agent_cmd = _write_agent(tmp_path, "sleeper.py", SLEEPER)
    report = run_live_corpus(corpus, agent_cmd=agent_cmd,
                             agent_timeout=1)
    row = report["tasks"][0]
    assert row["agent_timed_out"] is True
    assert row["agent_exit_code"] is None
    assert row["status"] == "fail"
    assert any("timed out" in f for f in row["failures"])
    assert row["agent_timeout_seconds"] == 1


# --- 6. Secret hygiene ----------------------------------------------------

@requires_core
def test_agent_command_line_never_reaches_the_report(tmp_path):
    corpus, _proj = _write_corpus(tmp_path)
    # A configured command whose arguments carry a secret, pointing
    # at a binary that does not exist: the run records the attempt,
    # but the secret and the arguments must appear NOWHERE.
    report = run_live_corpus(
        corpus, agent_cmd=f"fakeagent --key {SECRET}")
    dumped = json.dumps(report)
    assert SECRET not in dumped
    assert "--key" not in dumped
    assert report["agent"]["name"] == "fakeagent"
    row = report["tasks"][0]
    assert row["agent_name"] == "fakeagent"
    assert row["agent_error"]  # missing binary recorded, not a crash
    assert row["status"] == "fail"


@requires_core
def test_parent_secret_never_reaches_the_agent_environment(
        tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBENCH_PROBE_SECRET", SECRET)
    dump = tmp_path / "agent-env.txt"
    body = (
        "import os\n"
        f"with open({str(dump)!r}, 'w') as fh:\n"
        "    for key in sorted(os.environ):\n"
        "        fh.write(key + '=' + os.environ[key] + '\\n')\n"
    )
    corpus, _proj = _write_corpus(tmp_path)
    agent_cmd = _write_agent(tmp_path, "envdump.py", body)
    run_live_corpus(corpus, agent_cmd=agent_cmd)
    text = dump.read_text()
    assert SECRET not in text
    assert "GHOSTBENCH_PROBE_SECRET" not in text
    # The task variables DO reach the agent, and HOME is contained.
    assert "GHOSTBENCH_TASK_ID=fix-add" in text
    assert "GHOSTBENCH_TASK_DIR=" in text
    assert "GHOSTBENCH_TASK_PROMPT=Fix the add function" in text
    home_line = next(l for l in text.splitlines() if l.startswith("HOME="))
    assert "ghostbench-live-" in home_line
    assert home_line != "HOME=" + os.path.expanduser("~")


# --- 7. Symlink escapes are skipped + recorded on the live path ---------

@requires_core
def test_symlink_escape_is_skipped_and_recorded_live(tmp_path):
    corpus, proj = _write_corpus(tmp_path)
    outside = tmp_path / "outside_secret.txt"
    outside.write_text(OUTSIDE_MARKER + "\n")
    os.symlink(outside, proj / "link.txt")
    body = (
        "import os, sys\n"
        "task_dir = os.environ['GHOSTBENCH_TASK_DIR']\n"
        "print('LINK:', 'PRESENT' if os.path.exists(\n"
        "    os.path.join(task_dir, 'link.txt')) else 'NO-LINK-FILE')\n"
        "with open(os.path.join(task_dir, 'calc.py'), 'w') as fh:\n"
        "    fh.write('def add(a, b):\\n    return a + b\\n')\n"
    )
    agent_cmd = _write_agent(tmp_path, "fixer_link.py", body)
    report = run_live_corpus(corpus, agent_cmd=agent_cmd)
    row = report["tasks"][0]
    assert row["status"] == "pass"
    assert "NO-LINK-FILE" in row["agent_output_tail"]
    assert OUTSIDE_MARKER not in row["agent_output_tail"]
    assert row["sandbox"]["skipped_symlinks"] == ["link.txt"]
    assert row["test"]["sandbox"]["skipped_symlinks"] == ["link.txt"]
    assert report["sandbox"]["skipped_symlinks"] == ["link.txt"]


# --- CLI end-to-end with a stand-in agent ---------------------------------

@requires_core
def test_live_cli_end_to_end_with_stand_in_agent(tmp_path):
    _corpus, _proj = _write_corpus(tmp_path)
    agent_cmd = _write_agent(tmp_path, "fixer.py", FIXER)
    out = tmp_path / "out"
    proc = run_cli(
        ["live", tmp_path / "corpus.json", "--out", out, "--no-ledger"],
        env_extra={AGENT_CMD_ENV: agent_cmd})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads((out / "bench-report.json").read_text())
    assert report["tier"] == "B"
    assert report["verification_level"] == "live-agent"
    assert report["agent"]["name"] == PY
    assert report["tasks"][0]["status"] == "pass"
    assert (out / "BENCH.md").is_file()
