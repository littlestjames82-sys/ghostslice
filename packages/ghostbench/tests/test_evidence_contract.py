"""Evidence contract tests (Oct 18, 2026): contained test execution
+ verification_level.

These pin the known-answer probes from the evidence build:

1. a normal passing test command in the temp copy scores pass;
2. a failing test command scores fail;
3. a secret planted in the parent environment (GHOSTBENCH_PROBE_SECRET)
   reached the test process before the fix; it must NOT now;
4. a patch touching ../outside or an absolute path is refused by
   Bench's own validation BEFORE git apply;
5. a project symlink to a file outside the project is not followed
   into the test copy; it is skipped and recorded.

Plus the contract field itself: verification_level on every task row
and at report level (strongest row wins), BENCH.md's first screen
stating the level in plain words, and the SAMPLE banner.
No live (Tier B) runs, no network, no spend.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from conftest import requires_core  # noqa: E402
from ghostbench.corpus import Corpus, Project, Task  # noqa: E402
from ghostbench.report import render_bench_md  # noqa: E402
from ghostbench.runner import (  # noqa: E402
    _run_test_in_temp, _scrubbed_env, _validate_patch_paths,
    run_corpus, run_task, strongest_verification_level)

SECRET = "probe-secret-value-12345"
OUTSIDE_MARKER = "PROBE-OUTSIDE-CONTENT-6789"


def _project(tmp_path, files, name="proj"):
    pdir = tmp_path / name
    pdir.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        full = pdir / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    return Project(id=name, path=str(pdir))


def _corpus(project, tasks):
    return Corpus(name="t", version="1", path="/nonexistent/corpus.json",
                  base_dir=str(Path(project.path).parent),
                  projects=[Project(id=project.id, path=project.path,
                                    tasks=tasks)])


PY = sys.executable


# --- Probes 1 + 2: known-answer pass/fail in the contained runner ---

@requires_core
def test_probe_passing_command_scores_pass(tmp_path):
    proj = _project(tmp_path, {"check.py": "print('all good')\n"})
    result = _run_test_in_temp(
        proj, Task(id="t", test_command=[PY, "check.py"]), None)
    assert result["ran"] is True and result["status"] == "pass"
    assert "all good" in result["output_tail"]


@requires_core
def test_probe_failing_command_scores_fail(tmp_path):
    proj = _project(tmp_path, {"check.py": "import sys; sys.exit(3)\n"})
    result = _run_test_in_temp(
        proj, Task(id="t", test_command=[PY, "check.py"]), None)
    assert result["ran"] is True and result["status"] == "fail"
    assert result["exit_code"] == 3


# --- Probe 3: the environment is scrubbed -----------------------------

@requires_core
def test_probe_parent_env_secret_never_reaches_test_process(
        tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBENCH_PROBE_SECRET", SECRET)
    proj = _project(tmp_path, {"check.py":
        "import os\n"
        "print('SECRET_IS:', os.environ.get('GHOSTBENCH_PROBE_SECRET', 'ABSENT'))\n"
        "print('HOME_IS:', os.environ.get('HOME'))\n"
        "print('PATH_OK:', bool(os.environ.get('PATH')))\n"})
    result = _run_test_in_temp(
        proj, Task(id="t", test_command=[PY, "check.py"]), None)
    assert result["status"] == "pass"
    assert SECRET not in result["output_tail"]
    assert "SECRET_IS: ABSENT" in result["output_tail"]
    # HOME is contained too, not the user's real home.
    assert f"HOME_IS: {os.path.expanduser('~')}" not in result["output_tail"]
    assert "ghostbench-test-" in result["output_tail"]
    assert "PATH_OK: True" in result["output_tail"]


@requires_core
def test_scrubbed_env_is_an_allowlist(tmp_path):
    env = _scrubbed_env(str(tmp_path), str(tmp_path / "project"))
    assert "GHOSTBENCH_PROBE_SECRET" not in env
    assert env["HOME"] == str(tmp_path / "project")
    assert env["TMPDIR"] == str(tmp_path)
    for key in os.environ:
        if key.startswith(("AWS_", "GH_TOKEN", "OPENAI", "ANTHROPIC")):
            assert key not in env


@requires_core
def test_result_carries_the_honest_sandbox_block(tmp_path):
    proj = _project(tmp_path, {"check.py": "print('ok')\n"})
    result = _run_test_in_temp(
        proj, Task(id="t", test_command=[PY, "check.py"]), None)
    sandbox = result["sandbox"]
    assert any("environment scrubbed" in s for s in sandbox["enforced"])
    assert any("network" in s for s in sandbox["not_enforced"])
    assert any("NOT prevented" in s for s in sandbox["not_enforced"])
    assert sandbox["skipped_symlinks"] == []


@requires_core
def test_output_tail_is_capped(tmp_path):
    proj = _project(tmp_path, {"check.py": "print('x' * 5000)\n"})
    result = _run_test_in_temp(
        proj, Task(id="t", test_command=[PY, "check.py"]), None)
    assert len(result["output_tail"]) <= 1000


@pytest.mark.skipif(os.name != "posix", reason="POSIX rlimits only")
@requires_core
def test_resource_limits_reach_the_test_process(tmp_path):
    proj = _project(tmp_path, {"check.py":
        "import resource\n"
        "print('CPU_LIMIT:', resource.getrlimit(resource.RLIMIT_CPU)[0])\n"
        "print('CORE_LIMIT:', resource.getrlimit(resource.RLIMIT_CORE)[0])\n"})
    result = _run_test_in_temp(
        proj, Task(id="t", test_command=[PY, "check.py"]), None)
    assert result["status"] == "pass", result
    assert "CPU_LIMIT: 110" in result["output_tail"]
    assert "CORE_LIMIT: 0" in result["output_tail"]


# --- Probe 4: patch containment, refused before git apply -------------

ESCAPE_PATCH = (
    "diff --git a/../../gb-evidence-escape.txt "
    "b/../../gb-evidence-escape.txt\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/../../gb-evidence-escape.txt\n"
    "@@ -0,0 +1 @@\n"
    "+escaped\n"
)


@requires_core
def test_probe_patch_dotdot_refused_before_application(tmp_path):
    target = Path(tempfile.gettempdir()) / "gb-evidence-escape.txt"
    if target.exists():
        target.unlink()
    proj = _project(tmp_path, {"check.py": "print('ok')\n"})
    result = _run_test_in_temp(
        proj, Task(id="t", test_command=[PY, "check.py"]), ESCAPE_PATCH)
    assert result["ran"] is False
    assert result["status"] == "patch-apply-failed"
    assert "containment" in result["detail"]
    assert "escapes the temporary copy" in result["detail"]
    assert not target.exists(), "patch escaped the temp copy onto disk"


@requires_core
def test_patch_absolute_path_refused(tmp_path):
    patch = ("--- /dev/null\n"
             "+++ /tmp/gb-evidence-abs.txt\n"
             "@@ -0,0 +1 @@\n"
             "+abs\n")
    problems = _validate_patch_paths(patch, str(tmp_path))
    assert any("absolute" in p for p in problems)


@requires_core
def test_patch_through_patch_created_symlink_refused(tmp_path):
    patch = (
        "diff --git a/linkdir b/linkdir\n"
        "new file mode 120000\n"
        "--- /dev/null\n"
        "+++ b/linkdir\n"
        "@@ -0,0 +1 @@\n"
        "+/tmp\n"
        "diff --git a/linkdir/evil.txt b/linkdir/evil.txt\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/linkdir/evil.txt\n"
        "@@ -0,0 +1 @@\n"
        "+through\n")
    problems = _validate_patch_paths(patch, str(tmp_path))
    assert any("symlink" in p for p in problems)


@requires_core
def test_legit_patch_still_applies_and_is_what_the_test_runs(tmp_path):
    proj = _project(tmp_path, {"check.py": "print('before')\n"})
    patch = ("diff --git a/check.py b/check.py\n"
             "--- a/check.py\n"
             "+++ b/check.py\n"
             "@@ -1 +1 @@\n"
             "-print('before')\n"
             "+print('after')\n")
    assert _validate_patch_paths(patch, proj.path) == []
    result = _run_test_in_temp(
        proj, Task(id="t", test_command=[PY, "check.py"]), patch)
    assert result["status"] == "pass"
    assert "after" in result["output_tail"]
    # The original project tree was never touched.
    assert (Path(proj.path) / "check.py").read_text() == "print('before')\n"


# --- Probe 5: copied-tree symlinks ------------------------------------

@requires_core
def test_probe_symlink_outside_project_is_skipped_and_recorded(tmp_path):
    outside = tmp_path / "outside_secret.txt"
    outside.write_text(OUTSIDE_MARKER + "\n")
    proj = _project(tmp_path, {"check.py":
        "import os\n"
        "print('LINK:', open('link.txt').read().strip() "
        "if os.path.exists('link.txt') else 'NO-LINK-FILE')\n"},
        name="projlink")
    os.symlink(outside, Path(proj.path) / "link.txt")
    result = _run_test_in_temp(
        proj, Task(id="t", test_command=[PY, "check.py"]), None)
    assert result["status"] == "pass"
    assert OUTSIDE_MARKER not in result["output_tail"]
    assert "NO-LINK-FILE" in result["output_tail"]
    assert result["skipped_symlinks"] == ["link.txt"]
    assert result["sandbox"]["skipped_symlinks"] == ["link.txt"]


@requires_core
def test_symlink_inside_project_is_still_copied(tmp_path):
    proj = _project(tmp_path, {
        "real.txt": "inside-content\n",
        "check.py": "print('INNER:', open('alias.txt').read().strip())\n"})
    os.symlink(Path(proj.path) / "real.txt", Path(proj.path) / "alias.txt")
    result = _run_test_in_temp(
        proj, Task(id="t", test_command=[PY, "check.py"]), None)
    assert result["status"] == "pass"
    assert "INNER: inside-content" in result["output_tail"]
    assert result["skipped_symlinks"] == []


@requires_core
def test_dangling_symlink_is_skipped_not_a_crash(tmp_path):
    proj = _project(tmp_path, {"check.py": "print('ok')\n"})
    os.symlink(Path(proj.path) / "does-not-exist.txt",
               Path(proj.path) / "dangling.txt")
    result = _run_test_in_temp(
        proj, Task(id="t", test_command=[PY, "check.py"]), None)
    assert result["status"] == "pass"
    assert result["skipped_symlinks"] == ["dangling.txt"]


# --- verification_level ------------------------------------------------

@requires_core
def test_level_ordering_and_strongest():
    assert strongest_verification_level([]) == "none"
    assert strongest_verification_level(["static-analysis"]) == "static-analysis"
    assert strongest_verification_level(
        ["static-analysis", "tests-executed"]) == "tests-executed"
    assert strongest_verification_level(
        ["tests-executed", "live-agent"]) == "live-agent"
    assert strongest_verification_level(["bogus"]) == "none"


@requires_core
def test_row_level_static_when_scored_from_patch_only(tmp_path):
    proj = _project(tmp_path, {"a.py": "x = 1\n"})
    task = Task(id="t", expected_files=["a.py"],
                patch_text=("diff --git a/a.py b/a.py\n"
                            "--- a/a.py\n+++ b/a.py\n"
                            "@@ -1 +1 @@\n-x = 1\n+x = 2\n"))
    row = run_task(_corpus(proj, [task]), proj, task)
    assert row["status"] == "pass"
    assert row["verification_level"] == "static-analysis"


@requires_core
def test_row_level_tests_executed_when_tests_ran(tmp_path):
    proj = _project(tmp_path, {"check.py": "print('ok')\n"})
    task = Task(id="t", test_command=[PY, "check.py"])
    row = run_task(_corpus(proj, [task]), proj, task, run_tests=True)
    assert row["test"]["ran"] is True
    assert row["verification_level"] == "tests-executed"
    assert row["test"]["sandbox"]["not_enforced"]


@requires_core
def test_row_level_none_when_nothing_measurable(tmp_path):
    proj = _project(tmp_path, {}, name="empty")
    task = Task(id="t")
    row = run_task(_corpus(proj, [task]), proj, task)
    assert row["status"] == "unknown"
    assert row["verification_level"] == "none"


@requires_core
def test_report_level_is_strongest_row_and_provenance_is_live(tmp_path):
    proj = _project(tmp_path, {"check.py": "print('ok')\n", "a.py": "x = 1\n"})
    tasks = [Task(id="runs", test_command=[PY, "check.py"]),
             Task(id="static-only")]
    corpus = _corpus(proj, tasks)
    report = run_corpus(corpus, run_tests=True)
    levels = {r["task"]: r["verification_level"] for r in report["tasks"]}
    assert levels["runs"] == "tests-executed"
    assert report["verification_level"] == "tests-executed"
    assert report["provenance"] == "live"
    assert report["sandbox"] is not None
    assert report["honest_scope"]["tier"].startswith("A (tests executed")

    static_report = run_corpus(corpus, run_tests=False)
    assert static_report["verification_level"] == "static-analysis"
    assert all(r["verification_level"] == "static-analysis"
               for r in static_report["tasks"])
    assert static_report["sandbox"] is None


# --- BENCH.md first screen ----------------------------------------------

def _report_dict(**overrides):
    report = {
        "tool": "ghostbench", "tool_version": "0.1.0", "tier": "A",
        "suite": "slice", "run_id": "test-run",
        "verification_level": "static-analysis",
        "corpus": {"name": "mini", "version": "0.1.0"},
        "subset": {"labelled": False, "task_ids": None},
        "slice_version": None, "estimator_version": "v-test",
        "estimator_source": "test", "price_table_date": None,
        "run_tests": False,
        "honest_scope": {"tier": "A (static, no model, no spend)",
                         "tasks_measured": 1,
                         "what_was_not_measured": ["live agent runs"]},
        "totals": {"full_tokens": 10, "variants": {}, "tasks": 1,
                   "pass": 1, "fail": 0, "unknown": 0,
                   "hard_gaps_predicted": 0},
        "tasks": [{"project": "p", "task": "t1", "status": "pass",
                   "verification_level": "static-analysis",
                   "full_tokens": 10, "hard_gaps_predicted": 0,
                   "variants": {"sliced": {"tokens": 5,
                                           "saving_pct_vs_full": 50.0,
                                           "manifest_sha256": None}},
                   "patch": None, "symbols_score": {}}],
        "failures_visible": [],
    }
    report.update(overrides)
    return report


@requires_core
def test_bench_md_first_screen_states_level_in_plain_words():
    md = render_bench_md(_report_dict())
    first_screen = "\n".join(md.splitlines()[:12])
    assert "Verification level: static-analysis" in first_screen
    assert "no tests executed" in first_screen


@requires_core
def test_bench_md_first_screen_tests_executed_wording():
    md = render_bench_md(_report_dict(
        verification_level="tests-executed", run_tests=True,
        sandbox={"enforced": ["environment scrubbed"],
                 "not_enforced": ["network access is NOT blocked"]}))
    first_screen = "\n".join(md.splitlines()[:12])
    assert "Verification level: tests-executed" in first_screen
    assert "## Test execution containment" in md
    assert "Not enforced: network access is NOT blocked" in md


@requires_core
def test_bench_md_sample_banner_is_the_first_line():
    md = render_bench_md(_report_dict(
        sample=True, sample_note="illustrative only"))
    assert md.splitlines()[0].startswith("# *** SAMPLE REPORT")
    assert "illustrative only" in "\n".join(md.splitlines()[:8])


@requires_core
def test_bench_md_per_task_table_shows_row_level():
    md = render_bench_md(_report_dict())
    assert "| p | t1 | pass | static-analysis |" in md


def test_user_site_packages_stay_importable(tmp_path, monkeypatch):
    """Regression (Oct 18, 2026 dogfood): with HOME redirected into the
    temp area, Python loses the user site-packages and a real test
    command fails with 'No module named pytest' for an environment
    reason. PYTHONUSERBASE must flow through the scrubbed env."""
    import site

    base = tmp_path / "userbase"
    pkg_dir = (base / "lib" /
               f"python{sys.version_info.major}.{sys.version_info.minor}" /
               "site-packages" / "ghostprobe")
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("VALUE = 'probe-ok'\n")
    monkeypatch.setattr(site, "getuserbase", lambda: str(base))

    env = _scrubbed_env(str(tmp_path), str(tmp_path))
    assert env.get("PYTHONUSERBASE") == str(base)

    project = _project(tmp_path, {"a.py": "x = 1\n"})
    result = _run_test_in_temp(
        project, Task(id="t", test_command=(
            "python3 -c \"import ghostprobe; "
            "print(ghostprobe.VALUE)\"")), None)
    assert result["status"] == "pass"
    assert "probe-ok" in result["output_tail"]
