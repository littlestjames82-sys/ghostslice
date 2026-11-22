"""Tier B live bench: a configured agent attempts the real tasks.

Design (live-agent build, Oct 18, 2026). This module replaces the
v0.1 gate-only stub, whose model was a single hardcoded vendor agent
(--agent claude-code) behind a budget cap, a --confirm flag, and the
GHOSTBENCH_ENABLE_LIVE switch, with no executor wired at all. That
model is gone; what replaced it:

- The agent is a command line the USER configures in the
  environment variable ``GHOSTBENCH_AGENT_CMD``. Bench hardcodes no
  vendor, has no default agent, and makes no network calls itself.
  Whatever the configured agent does or spends is the user's own
  program, run at their direction.
- If ``GHOSTBENCH_AGENT_CMD`` is unset, empty, or unparseable, a
  live run refuses BEFORE anything runs: no task is attempted and
  no report is written. Bench never runs an agent it was not
  configured to run.
- On top of that configuration gate, ``ghostbench live --budget
  TOKENS`` restores the v0.1 budget cap as a second, independent
  gate (Ryan's direction, Oct 18, 2026): after the agent check and
  before any agent runs, the run's context size is estimated (the
  sum of the per-task full-context token estimates, from Bench's
  own estimator - the same numbers a run later reports as
  ``full_tokens``) and checked with :func:`check_budget`. Over the
  cap without ``--confirm``, the run refuses and writes nothing;
  with ``--confirm`` it proceeds and the report records the cap,
  the estimate, and that confirmation overrode the cap. The cap is
  in TOKENS and meters Bench's estimate only: the configured
  agent's real charges happen inside the user's own program and
  are never metered by Bench.
- Per task, the agent runs inside a contained copy of the project,
  reusing the Tier A containment machinery (safe copy with
  escaping symlinks skipped and recorded, scrubbed allowlist
  environment, POSIX rlimits, wall-clock timeout). The command is
  split shell-style (shlex) and executed directly - there is no
  shell, so pipes and redirection in the command do not work. The
  agent receives the task copy path in ``GHOSTBENCH_TASK_DIR`` and
  as the final command argument, the task id in
  ``GHOSTBENCH_TASK_ID``, and the task prompt in
  ``GHOSTBENCH_TASK_PROMPT``; its working directory is the copy.
- After the agent exits, Bench measures what it changed (a
  file-level diff against a pristine copy of the same tree) and
  runs the task's own test command in the agent's copy, contained
  exactly like Tier A. A task passes only when the agent exited 0
  or produced changes AND the tests pass. A crash, a timeout, or
  no changes is a failed row with the reason shown, never a silent
  pass. A task with no test command scores ``unknown``: the agent
  ran, but nothing verified its work.
- Only the first token of the agent command is ever recorded
  (``agent_name``): a command line can carry keys in its arguments,
  so the full line is never written to a report.
- The verification level is ``live-agent`` on the report and on
  every row, pass or fail: the level states what ran, not whether
  it worked.

What is NOT contained is stated in every row's ``sandbox`` block
and at report level: the agent runs with the user's permissions
outside an OS sandbox - Bench directs its work at the task copy by
making that copy its working directory, but host writes elsewhere
are not prevented, and network access is not blocked.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

try:
    import resource  # POSIX only; limits are best-effort elsewhere
except ImportError:  # pragma: no cover - non-POSIX platforms
    resource = None

from . import __version__
from .corpus import (Corpus, Project, Task, list_project_files,
                     read_verify_report)
from .prices import estimate_input_cost_usd, load_price_table, price_table_date
from .runner import (OUTPUT_TAIL_CHARS, _apply_resource_limits,
                     _copy_project_safely, _file_tokens, _inside_project,
                     _live_sandbox_block, _preexec_agent_limits,
                     _read_text, _sandbox_block, _scrubbed_env,
                     _variant_from_spec)
from .scoring import (normalise_verify_report, parse_patch, saving_pct,
                      score_expected_symbols, score_files_touched)
from .tokens import ESTIMATOR_SOURCE, ESTIMATOR_VERSION, slice_version

#: The one place a live agent command may come from. Bench reads
#: no other configuration for it and has no default.
AGENT_CMD_ENV = "GHOSTBENCH_AGENT_CMD"

#: Default wall-clock budget for one agent attempt, in seconds.
DEFAULT_AGENT_TIMEOUT = 300

#: Wall-clock timeout for the task test process on the live path -
#: the same 120s the Tier A contained runner uses.
LIVE_TEST_TIMEOUT_SECONDS = 120

#: A file larger than this on either side of the agent diff is
#: recorded as a change without a textual diff (the report carries
#: file-level facts and a diff hash, not the diff itself).
_DIFF_TEXT_LIMIT_BYTES = 1_000_000

_SNAPSHOT_SKIP_DIRS = {".git", "__pycache__", "node_modules"}

NO_AGENT_MESSAGE = (
    "no agent is configured for a Tier B live run: "
    "GHOSTBENCH_AGENT_CMD is not set (or is empty). Set it to the "
    "command Bench should run for each task, for example:\n"
    "  GHOSTBENCH_AGENT_CMD='my-agent --non-interactive' "
    "ghostbench live corpus.json\n"
    "The command is split shell-style and executed directly (no "
    "shell). It runs with the task copy as its working directory "
    "and receives the copy path in GHOSTBENCH_TASK_DIR and as its "
    "final argument, the task id in GHOSTBENCH_TASK_ID, and the "
    "prompt in GHOSTBENCH_TASK_PROMPT. Nothing was run and nothing "
    "was spent.")


class TierBRefusal(RuntimeError):
    """Raised whenever a Tier B live run refuses. Message is user-facing."""


def parse_agent_command(cmd) -> list[str]:
    """Split a configured agent command line into argv.

    Raises :class:`TierBRefusal` when the command is unset, empty,
    or unparseable - the refusal happens before anything runs.
    """
    if cmd is None or not str(cmd).strip():
        raise TierBRefusal(NO_AGENT_MESSAGE)
    try:
        argv = shlex.split(str(cmd))
    except ValueError as exc:
        raise TierBRefusal(
            f"GHOSTBENCH_AGENT_CMD could not be parsed ({exc}); "
            "check its quoting. Nothing was run and nothing was "
            "spent.") from exc
    if not argv:
        raise TierBRefusal(NO_AGENT_MESSAGE)
    return argv


def agent_argv_from_env() -> list[str]:
    """The agent argv from ``GHOSTBENCH_AGENT_CMD`` - the only
    source a live run may take an agent command from."""
    return parse_agent_command(os.environ.get(AGENT_CMD_ENV))


def agent_name_of(argv) -> str:
    """The recordable agent name: the command's first token ONLY.

    The full command line is never recorded anywhere: it may carry
    keys or tokens in its arguments.
    """
    return argv[0] if argv else ""


# ------------------------------------------------------------------
# Contained execution on the live path
# ------------------------------------------------------------------

def _snapshot_tree(root: str) -> dict:
    """Map every file under ``root`` to a content digest.

    Symlinks are digested by their target text, never followed, so
    an agent-created link pointing outside the copy cannot leak
    outside content into the measurement. Directories Bench's copy
    discipline excludes (.git, __pycache__, node_modules) are not
    walked.
    """
    snap: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in _SNAPSHOT_SKIP_DIRS)
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            if os.path.islink(full):
                snap[rel] = "symlink:" + os.readlink(full)
                continue
            try:
                digest = hashlib.sha256()
                with open(full, "rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        digest.update(chunk)
                snap[rel] = "sha256:" + digest.hexdigest()
            except OSError:
                snap[rel] = "unreadable"
    return snap


def _diff_snapshots(before: dict, after: dict):
    """(changed, added, deleted) project-relative paths between two
    tree snapshots."""
    changed = sorted(r for r in before
                     if r in after and before[r] != after[r])
    added = sorted(r for r in after if r not in before)
    deleted = sorted(r for r in before if r not in after)
    return changed, added, deleted


def _read_for_diff(path: str) -> str | None:
    """A file's text for diffing, or None when it is binary, huge,
    or unreadable (the change is still recorded, header-only)."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(_DIFF_TEXT_LIMIT_BYTES + 1)
    except OSError:
        return None
    if len(data) > _DIFF_TEXT_LIMIT_BYTES or b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _build_patch_text(pristine: str, dest: str, changed, added,
                      deleted) -> str:
    """A unified diff of the agent's edits, for the same static
    patch facts Tier A records (files touched, line counts, sha).

    The patch text itself is never stored in a report - only
    :func:`ghostbench.scoring.parse_patch` facts are - so this is a
    measurement instrument, not an artifact. Files with no textual
    side (binary, oversized) contribute headers only, which is all
    parse_patch needs to count them as touched.
    """
    parts: list[str] = []
    for rel in sorted(set(changed) | set(added) | set(deleted)):
        old = (None if rel in added
               else _read_for_diff(os.path.join(pristine, rel)))
        new = (None if rel in deleted
               else _read_for_diff(os.path.join(dest, rel)))
        fromfile = "/dev/null" if rel in added else f"a/{rel}"
        tofile = "/dev/null" if rel in deleted else f"b/{rel}"
        if (rel in added or old is not None) \
                and (rel in deleted or new is not None):
            parts.extend(difflib.unified_diff(
                (old or "").splitlines(), (new or "").splitlines(),
                fromfile=fromfile, tofile=tofile, lineterm=""))
        else:
            parts.append(f"--- {fromfile}")
            parts.append(f"+++ {tofile}")
    return "\n".join(parts) + ("\n" if parts else "")


def _expired_output(exc: subprocess.TimeoutExpired) -> str:
    """Combined output tail from a timed-out process, normalised to
    text (TimeoutExpired may carry bytes even in text mode)."""
    chunks = []
    for part in (exc.output, exc.stderr):
        if not part:
            continue
        if isinstance(part, bytes):
            part = part.decode("utf-8", errors="replace")
        chunks.append(part)
    return "".join(chunks)[-OUTPUT_TAIL_CHARS:]


def _run_agent_process(agent_argv, dest: str, tmp: str, task: Task,
                       timeout: int) -> dict:
    """Run the configured agent once, inside the task copy.

    The environment is the contained runner's scrubbed allowlist
    plus the three GHOSTBENCH_TASK_* variables; the copy path is
    appended as the final argument. Output is capped like the test
    runner's. A missing/unexecutable binary is a recorded outcome
    (``error``), not a crash of the whole run.
    """
    env = _scrubbed_env(tmp, dest)
    env["GHOSTBENCH_TASK_DIR"] = dest
    env["GHOSTBENCH_TASK_ID"] = task.id
    env["GHOSTBENCH_TASK_PROMPT"] = task.prompt or ""
    argv = list(agent_argv) + [dest]
    try:
        proc = subprocess.run(
            argv, cwd=dest, capture_output=True, text=True,
            timeout=timeout, env=env,
            preexec_fn=_preexec_agent_limits(timeout + 30))
        return {"exit_code": proc.returncode, "timed_out": False,
                "error": None,
                "output_tail": (proc.stdout + proc.stderr)[-OUTPUT_TAIL_CHARS:]}
    except subprocess.TimeoutExpired as exc:
        return {"exit_code": None, "timed_out": True, "error": None,
                "output_tail": _expired_output(exc)}
    except OSError as exc:
        return {"exit_code": None, "timed_out": False,
                "error": str(exc), "output_tail": ""}


def _run_tests_in_copy(task: Task, dest: str, tmp: str,
                       skipped_symlinks) -> dict:
    """Run the task's test command in the agent's copy, contained
    exactly as Tier A's ``_run_test_in_temp`` runs it (same scrubbed
    environment, rlimits, 120s timeout, output cap, sandbox block) -
    minus the fresh copy and patch application, which the live path
    replaces with the agent's own edits already in ``dest``.
    """
    cmd = task.test_command
    try:
        argv = shlex.split(cmd) if isinstance(cmd, str) else list(cmd or [])
    except ValueError as exc:  # e.g. unbalanced quote in the command
        return {"ran": False, "status": "bad-test-command",
                "detail": str(exc)}
    if not all(isinstance(part, str) for part in argv):
        return {"ran": False, "status": "bad-test-command",
                "detail": "test_command entries must be strings"}
    if not argv:
        return {"ran": False, "status": "no-test-command"}
    sandbox = _sandbox_block(skipped_symlinks)
    try:
        proc = subprocess.run(
            argv, cwd=dest, capture_output=True, text=True,
            timeout=LIVE_TEST_TIMEOUT_SECONDS,
            env=_scrubbed_env(tmp, dest),
            preexec_fn=(_apply_resource_limits
                        if resource is not None else None))
        return {"ran": True,
                "status": "pass" if proc.returncode == 0 else "fail",
                "exit_code": proc.returncode,
                "output_tail": (proc.stdout + proc.stderr)[-OUTPUT_TAIL_CHARS:],
                "sandbox": sandbox,
                "skipped_symlinks": skipped_symlinks}
    except subprocess.TimeoutExpired:
        return {"ran": True, "status": "timeout", "exit_code": None,
                "sandbox": sandbox,
                "skipped_symlinks": skipped_symlinks}
    except OSError as exc:
        return {"ran": True, "status": "error", "exit_code": None,
                "detail": str(exc), "sandbox": sandbox,
                "skipped_symlinks": skipped_symlinks}


# ------------------------------------------------------------------
# Live task + corpus runs
# ------------------------------------------------------------------

def run_live_task(corpus: Corpus, project: Project, task: Task, *,
                  agent_argv, agent_timeout: int = DEFAULT_AGENT_TIMEOUT,
                  table: dict | None = None) -> dict:
    """Run one task live and return its report row.

    The row carries the same static measurements as a Tier A row
    (full/sliced token estimates, Verify verdict, expected-symbol
    coverage judged against the post-agent files), plus the live
    facts: ``agent_name`` (first token only), ``agent_exit_code``,
    ``agent_timed_out``, the file-level change measurement, and the
    contained test outcome against the agent's edits. Its
    ``verification_level`` is ``live-agent`` whatever the outcome.
    """
    failures: list[str] = []
    files = list_project_files(project.path)
    full_tokens = sum(_file_tokens(project, rel) for rel in files)
    variants: dict[str, dict] = {}

    full_spec = (task.variants or {}).get("full")
    if full_spec:
        full_v = _variant_from_spec(corpus, full_spec)
        if full_v["tokens"] is not None:
            full_tokens = full_v["tokens"]
            variants["full"] = {**full_v, "fit_success": None}
    if "full" not in variants:
        variants["full"] = {"tokens": full_tokens,
                            "manifest_sha256": None,
                            "source": "project-scan", "fit_success": None}

    sliced_spec = (task.variants or {}).get("sliced")
    if sliced_spec:
        sliced = _variant_from_spec(corpus, sliced_spec)
        if sliced["tokens"] is None:
            failures.append("sliced variant supplied but its token "
                            "total could not be determined from the manifest")
    else:
        sliced_tokens = 0
        for rel in task.expected_files:
            full = _inside_project(project, rel)
            if full is not None and os.path.isfile(full):
                sliced_tokens += _file_tokens(project, rel)
        sliced = {"tokens": sliced_tokens, "manifest_sha256": None,
                  "source": "derived:expected-files"}
    variants["sliced"] = sliced

    budget = task.budget_tokens
    for name, var in variants.items():
        var["saving_pct_vs_full"] = saving_pct(full_tokens, var["tokens"])
        var["fit_success"] = (
            None if budget is None or var["tokens"] is None
            else var["tokens"] <= budget)
        var["estimated_input_cost_usd"] = estimate_input_cost_usd(
            var["tokens"] or 0, None, table) if var["tokens"] is not None else None
    if budget is not None and variants["sliced"]["fit_success"] is False:
        failures.append(
            f"sliced variant ({variants['sliced']['tokens']} tokens) "
            f"exceeds task budget ({budget} tokens)")

    vdata, vhash = read_verify_report(corpus, project, task)
    verify = normalise_verify_report(vdata)
    verify["report_sha256"] = ("sha256:" + vhash) if vhash else None
    hard_gaps = verify["hard_gaps"]
    if hard_gaps:
        failures.append(f"verify predicted {len(hard_gaps)} hard gap(s)")

    # --- the live attempt -------------------------------------------
    tmp = tempfile.mkdtemp(prefix="ghostbench-live-")
    try:
        dest = os.path.join(tmp, "project")
        pristine = os.path.join(tmp, "pristine")
        skipped_symlinks = _copy_project_safely(project.path, dest)
        _copy_project_safely(project.path, pristine)
        before = _snapshot_tree(dest)

        agent = _run_agent_process(agent_argv, dest, tmp, task,
                                   agent_timeout)

        after = _snapshot_tree(dest)
        changed, added, deleted = _diff_snapshots(before, after)
        changed_paths = sorted(set(changed) | set(added) | set(deleted))
        patch_text = _build_patch_text(pristine, dest, changed,
                                       added, deleted)
        patch = parse_patch(patch_text)
        files_score = score_files_touched(patch, task.expected_files)

        # Expected symbols are judged against the files as the agent
        # left them: coverage of the pre-agent tree would grade the
        # starting state, not the attempt.
        file_texts = {}
        dest_root = os.path.abspath(dest)
        for rel in task.expected_files:
            full = os.path.abspath(os.path.join(dest_root, rel))
            if os.path.commonpath([dest_root, full]) == dest_root \
                    and os.path.isfile(full):
                text = _read_text(full)
                if text is not None:
                    file_texts[rel] = text
        symbols_score = score_expected_symbols(
            task.expected_symbols, file_texts, patch_text)
        symbols_score["checked_against"] = "expected-files-after-agent"

        test_result = _run_tests_in_copy(task, dest, tmp,
                                         skipped_symlinks)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- verdict ------------------------------------------------------
    files_changed = len(changed_paths)
    if agent["timed_out"]:
        failures.append(
            f"agent timed out after {agent_timeout}s "
            "and was stopped")
    elif agent["error"] is not None:
        failures.append(
            f"agent could not be started: {agent['error']}")
    elif agent["exit_code"] not in (0, None) and files_changed == 0:
        failures.append(
            f"agent exited with code {agent['exit_code']} "
            "and changed no files")
    elif files_changed == 0:
        failures.append("agent made no changes to the task copy")

    # Pass requires produced changes AND passing tests (with no
    # timeout and no spawn error): a no-change attempt fails even
    # when the agent exited 0, and a nonzero exit is rescued only
    # by changes that pass the tests - the design's "(or produced
    # changes)" clause. The exit code itself is always recorded on
    # the row either way.
    agent_ok = (not agent["timed_out"] and agent["error"] is None
                and files_changed > 0)
    test_status = test_result.get("status")
    if test_status == "no-test-command":
        failures.append(
            "task has no test command: the agent's changes could "
            "not be verified by tests")
    elif test_status != "pass":
        failures.append(f"test command: {test_status}")

    if not agent_ok:
        status = "fail"
    elif test_status == "pass":
        status = "pass"
    elif test_status == "no-test-command":
        status = "unknown"
    else:
        status = "fail"

    return {
        "project": project.id, "task": task.id, "prompt": task.prompt,
        "project_commit": project.commit,
        "project_tree_hash": project.tree_hash,
        "full_tokens": full_tokens,
        "variants": variants,
        "budget_tokens": budget,
        "verify": verify,
        "hard_gaps_predicted": len(hard_gaps),
        "soft_gaps_predicted": len(verify["soft_gaps"]),
        "patch": patch,
        "files_touched_score": files_score,
        "symbols_score": symbols_score,
        "test": test_result,
        "agent_name": agent_name_of(agent_argv),
        "agent_exit_code": agent["exit_code"],
        "agent_timed_out": agent["timed_out"],
        "agent_error": agent["error"],
        "agent_output_tail": agent["output_tail"],
        "agent_timeout_seconds": agent_timeout,
        "files_changed": files_changed,
        "files_changed_paths": changed_paths,
        "files_added": added,
        "files_deleted": deleted,
        "files_modified": changed,
        "sandbox": _live_sandbox_block(skipped_symlinks),
        "status": status,
        "verification_level": "live-agent",
        "failures": failures,
        "flaky": False,
    }


def estimate_task_context_tokens(corpus: Corpus, project: Project,
                                 task: Task) -> int:
    """The full-context token estimate for one task - the same
    number :func:`run_live_task` later reports as the row's
    ``full_tokens``: the project scan total from Bench's estimator,
    overridden by the task's ``full`` variant spec when one is
    supplied and yields a token count."""
    full_tokens = sum(_file_tokens(project, rel)
                      for rel in list_project_files(project.path))
    full_spec = (task.variants or {}).get("full")
    if full_spec:
        full_v = _variant_from_spec(corpus, full_spec)
        if full_v["tokens"] is not None:
            full_tokens = full_v["tokens"]
    return full_tokens


def estimate_live_run_tokens(corpus: Corpus,
                             task_filter: set | None = None) -> int:
    """Estimated context tokens for a live run over the selected
    tasks: the sum of the per-task full-context estimates.

    This is an ESTIMATE, in tokens, from Bench's token estimator -
    the size of the context the tasks represent, not a measurement
    of anything the configured agent will consume or be billed.
    The agent is the user's own program; what it reads, uses, or
    charges is outside Bench and is not estimated here.
    """
    return sum(
        estimate_task_context_tokens(corpus, project, task)
        for project, task in corpus.all_tasks()
        if not task_filter or task.id in task_filter)


def budget_gate(corpus: Corpus, *, budget_cap=None, confirmed=False,
                task_filter: set | None = None) -> dict:
    """The ``--budget`` gate for a live run, decided by
    :func:`check_budget` against the run's estimated context
    tokens.

    With no cap, returns the unset record (``budget_cap`` and
    ``budget_estimate`` None, ``budget_confirmed`` False) and no
    estimate is computed - behaviour is exactly the ungated run.
    With a cap, the estimate is computed; when it exceeds the cap
    and ``confirmed`` is false, raises :class:`TierBRefusal`
    before anything runs. When it exceeds the cap and ``confirmed``
    is true, the returned record carries ``exceeded: True`` so the
    caller can say the cap was overridden. The returned dict's
    ``budget_cap`` / ``budget_estimate`` / ``budget_confirmed``
    fields are what the report records.
    """
    if budget_cap is None:
        return {"budget_cap": None, "budget_estimate": None,
                "budget_confirmed": False, "exceeded": False}
    if isinstance(budget_cap, bool) \
            or not isinstance(budget_cap, (int, float)) \
            or budget_cap <= 0:
        raise TierBRefusal(
            "the budget cap must be a positive number of tokens "
            f"(got {budget_cap!r}). Nothing was run.")
    estimate = estimate_live_run_tokens(corpus, task_filter)
    within = check_budget({"budget_tokens": budget_cap}, estimate)
    if not within and not confirmed:
        raise TierBRefusal(
            f"budget cap exceeded: this live run is estimated at "
            f"{estimate} context tokens, over the --budget cap of "
            f"{budget_cap} tokens. The estimate is the sum of the "
            "per-task full-context token estimates from Bench's "
            "own estimator - it caps Bench's estimate only. The "
            "configured agent's real cost is whatever the agent "
            "itself charges, inside your own program; Bench does "
            "not meter it and this cap does not bound it. Nothing "
            "was run and nothing was spent. To run anyway, add "
            "--confirm to the same command.")
    return {"budget_cap": budget_cap, "budget_estimate": estimate,
            "budget_confirmed": bool(confirmed),
            "exceeded": not within}


def run_live_corpus(corpus: Corpus, *, agent_cmd=None, agent_argv=None,
                    agent_timeout: int = DEFAULT_AGENT_TIMEOUT,
                    task_filter: set | None = None,
                    budget: dict | None = None) -> dict:
    """Run Tier B live over a corpus and return the report dict.

    The agent command comes from ``agent_argv`` if given, else from
    ``agent_cmd`` (a command-line string), else - the only source
    the CLI uses - from ``GHOSTBENCH_AGENT_CMD`` in the environment.
    A missing, empty, or unparseable command raises
    :class:`TierBRefusal` before any task runs. The report dict has
    the same shape as a Tier A report (see ``runner.run_corpus``),
    with ``tier`` ``"B"`` and ``verification_level`` ``"live-agent"``
    on the report and every row. ``budget`` is the record returned
    by :func:`budget_gate` (the CLI's ``--budget`` gate runs before
    this function is called); its cap/estimate/confirmed fields are
    recorded on the report, all unset when no budget was given.
    """
    if agent_argv is None:
        agent_argv = (parse_agent_command(agent_cmd)
                      if agent_cmd is not None else agent_argv_from_env())
    if isinstance(agent_timeout, bool) \
            or not isinstance(agent_timeout, (int, float)) \
            or agent_timeout <= 0:
        raise TierBRefusal(
            "the agent timeout must be a positive number of seconds.")
    agent_timeout = int(agent_timeout)

    table = load_price_table()
    rows = []
    for project, task in corpus.all_tasks():
        if task_filter and task.id not in task_filter:
            continue
        rows.append(run_live_task(corpus, project, task,
                                  agent_argv=agent_argv,
                                  agent_timeout=agent_timeout,
                                  table=table))
    totals: dict = {"full_tokens": sum(r["full_tokens"] for r in rows),
                    "tasks": len(rows),
                    "pass": sum(1 for r in rows if r["status"] == "pass"),
                    "fail": sum(1 for r in rows if r["status"] == "fail"),
                    "unknown": sum(1 for r in rows if r["status"] == "unknown"),
                    "hard_gaps_predicted": sum(
                        r["hard_gaps_predicted"] for r in rows),
                    "expected_symbols": sum(
                        len(r["symbols_score"]["expected_symbols"])
                        for r in rows),
                    "symbols_found": sum(
                        len(r["symbols_score"]["found_in_expected_files"])
                        for r in rows),
                    "tasks_with_missing_symbols": sum(
                        1 for r in rows
                        if r["symbols_score"]["missing_from_expected_files"]),
                    "variants": {}}
    totals["symbol_coverage_pct"] = (
        round(totals["symbols_found"] * 100.0 / totals["expected_symbols"], 1)
        if totals["expected_symbols"] else None)
    variant_names = sorted({n for r in rows for n in r["variants"]})
    for name in variant_names:
        toks = [r["variants"][name]["tokens"] for r in rows
                if r["variants"].get(name, {}).get("tokens") is not None]
        fits = [r["variants"][name]["fit_success"] for r in rows
                if r["variants"].get(name, {}).get("fit_success") is not None]
        if toks:
            total_toks = sum(toks)
            partial = len(toks) < len(rows)
            totals["variants"][name] = {
                "tokens": total_toks,
                "tasks_with_tokens": len(toks),
                "partial": partial,
                "saving_pct_vs_full": (
                    None if partial else
                    saving_pct(totals["full_tokens"], total_toks)),
                "fit_success_rate": (
                    round(sum(1 for f in fits if f) * 100.0 / len(fits), 1)
                    if fits else None),
            }
    skipped_all = sorted({rel for r in rows
                          for rel in r["sandbox"]["skipped_symlinks"]})
    now = datetime.now(timezone.utc)
    fingerprint = hashlib.sha256(json.dumps(
        {"corpus": corpus.name, "version": corpus.version, "rows": rows},
        sort_keys=True, default=str).encode()).hexdigest()[:12]
    subset = (sorted(task_filter) if task_filter else None)
    return {
        "tool": "ghostbench", "tool_version": __version__,
        "tier": "B", "suite": "live",
        "verification_level": "live-agent",
        "provenance": "live",
        "sandbox": _live_sandbox_block(skipped_all),
        "run_id": f"{now.strftime('%Y%m%dT%H%M%SZ')}-{fingerprint}",
        "created_utc": now.isoformat(),
        "corpus": {"name": corpus.name, "version": corpus.version,
                   "file": corpus.path},
        "subset": ({"labelled": True, "task_ids": subset}
                   if subset else {"labelled": False, "task_ids": None}),
        "slice_version": slice_version(),
        "estimator_version": ESTIMATOR_VERSION,
        "estimator_source": ESTIMATOR_SOURCE,
        "price_table_date": price_table_date(table),
        "price_table_source": table.get("_source"),
        "model_for_cost_estimates": None,
        "cost_note": ("Costs are ESTIMATES from a local dated price "
                      "table, never billed amounts. A live run's "
                      "agent is the user's own configured command; "
                      "Bench records no agent token usage and "
                      "estimates none."),
        "run_tests": True,
        "budget_cap": (budget or {}).get("budget_cap"),
        "budget_estimate": (budget or {}).get("budget_estimate"),
        "budget_confirmed": bool((budget or {}).get(
            "budget_confirmed", False)),
        "agent": {
            "name": agent_name_of(agent_argv),
            "command_source": AGENT_CMD_ENV,
            "timeout_seconds": agent_timeout,
            "note": ("Only the command's first token is recorded. "
                     "The full command line is never written to a "
                     "report: it may carry keys in its arguments."),
        },
        "honest_scope": {
            "tier": ("B (live agent run: a user-configured agent "
                     "command attempted each task in a contained "
                     "copy, and the task's tests then ran in the "
                     "same copy; Bench itself made no network calls "
                     "and hardcodes no vendor)"),
            "tasks_measured": len(rows),
            "what_was_not_measured": [
                "answer quality (no LLM judge in v0.1)",
                "agent token usage or cost (the configured agent "
                "reports none to Bench; nothing is estimated or "
                "blended in)",
                "the agent's behaviour outside the task copy "
                "(not observable by Bench; the containment block "
                "states what is not enforced)",
            ],
        },
        "totals": totals,
        "tasks": rows,
        "failures_visible": [
            {"project": r["project"], "task": r["task"],
             "failures": r["failures"]}
            for r in rows if r["failures"]],
    }


def check_budget(pre: dict, tokens_used: int) -> bool:
    """True while usage is within the cap in ``pre``.

    The cap is ``pre[\"budget_tokens\"]``, in TOKENS; usage is a
    token count. This is the v0.1 gate model's surviving utility,
    and since the budget-cap restoration (Oct 18, 2026) it is the
    decision function behind the live CLI's ``--budget`` gate:
    :func:`budget_gate` checks the run's ESTIMATED context tokens
    against the cap with it. It prices nothing in currency - the
    price table plays no part here - and it meters nothing the
    configured agent actually consumes; callers also use it to
    wrap a live run with their own budget accounting.
    """
    cap = pre.get("budget_tokens")
    if cap is None or isinstance(cap, bool) \
            or not isinstance(cap, (int, float)):
        return False
    if isinstance(tokens_used, bool) \
            or not isinstance(tokens_used, (int, float)) \
            or tokens_used < 0:
        return False
    return tokens_used <= cap


def mark_flaky(task_rows: list[dict]) -> list[dict]:
    """Given repeated rows for the same task, flag tasks whose arms
    disagree across re-runs. Flakiness is reported, not hidden."""
    by_task: dict[str, list[dict]] = {}
    for row in task_rows:
        by_task.setdefault(row.get("task", ""), []).append(row)
    for task_id, rows in by_task.items():
        statuses = {r.get("status") for r in rows}
        flaky = len(rows) > 1 and len(statuses) > 1
        for row in rows:
            row["flaky"] = flaky
    return task_rows
