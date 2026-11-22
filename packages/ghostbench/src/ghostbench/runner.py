"""Tier A static runner (default, free, deterministic) + ledger.

Tier A builds, per task:
- a "full" variant: every scannable file in the project, or the
  task's provided full bundle manifest when one is supplied;
- a "sliced" variant: the task's provided sliced bundle manifest
  when supplied, otherwise the task's expected_files only (a
  task-selection derivation, labelled as such in every row -
  Bench does not pretend this is a GhostSlice-produced bundle);
- any further variants (verified / recalled / proxied / custom)
  strictly from provided bundle manifests or explicit token totals.

Recorded patches get a static pass (files touched, Verify hard
gaps). Tests are NOT run unless the caller explicitly passes
run_tests=True, in which case they run in a temporary copy under
the contained test runner below: scrubbed environment, patch-path
containment validated before ``git apply``, escaping symlinks in
the copied tree skipped and recorded, POSIX resource limits where
the OS allows. What that runner does NOT enforce (host filesystem
writes by the test process, network access) is stated in every
test result's ``sandbox`` block - it is a contained working copy,
not an OS sandbox, and Bench says so rather than claiming more.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
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
                     read_task_patch, read_verify_report)
from .prices import estimate_input_cost_usd, load_price_table, price_table_date
from .scoring import (manifest_hash_for_bundle, manifest_tokens,
                      normalise_verify_report, parse_patch, saving_pct,
                      score_expected_symbols, score_files_touched,
                      _valid_token_count)
from .tokens import (ESTIMATOR_SOURCE, ESTIMATOR_VERSION,
                     estimate_tokens, language_for_path, slice_version)

TEXT_EXT_SKIP = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf",
                 ".zip", ".gz", ".so", ".dll", ".exe", ".class", ".pyc"}


def _read_text(path: str) -> str | None:
    if os.path.splitext(path)[1].lower() in TEXT_EXT_SKIP:
        return None
    try:
        with open(path, encoding="utf-8", errors="strict") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return None


def _file_tokens(project: Project, rel: str) -> int:
    text = _read_text(os.path.join(project.path, rel))
    if text is None:
        return 0
    return estimate_tokens(text, language_for_path(rel))


def _resolve_spec_path(corpus: Corpus, value: str) -> str:
    if os.path.isabs(value):
        return value
    return os.path.normpath(os.path.join(corpus.base_dir, value))


def _inside_project(project: Project, rel: str) -> str | None:
    """Absolute path for rel if it stays inside the project root,
    else None. An expected_file of '../outside.py' or '/etc/passwd'
    must not let the derived sliced arm count files Bench was never
    asked to measure (which also produced negative savings)."""
    root = os.path.abspath(project.path)
    full = os.path.abspath(os.path.join(root, rel))
    if full != root and os.path.commonpath([root, full]) != root:
        return None
    return full


def _variant_from_spec(corpus: Corpus, spec: dict) -> dict:
    """A variant supplied via bundle_dir / manifest / tokens."""
    out = {"tokens": None, "manifest_sha256": None, "source": "provided"}
    if not isinstance(spec, dict):
        return out
    if _valid_token_count(spec.get("tokens")):
        out["tokens"] = spec["tokens"]
        out["source"] = "provided-tokens"
    bundle_dir = spec.get("bundle_dir")
    manifest = spec.get("manifest")
    if not isinstance(bundle_dir, str):
        bundle_dir = None
    if not isinstance(manifest, str):
        manifest = None
    if bundle_dir:
        bdir = _resolve_spec_path(corpus, bundle_dir)
        out["manifest_sha256"] = manifest_hash_for_bundle(bundle_dir=bdir)
        mt = manifest_tokens(os.path.join(bdir, "manifest.json"))
        if mt is not None:
            out["tokens"] = mt
            out["source"] = "bundle-manifest"
    if manifest:
        mpath = _resolve_spec_path(corpus, manifest)
        out["manifest_sha256"] = manifest_hash_for_bundle(manifest_path=mpath)
        mt = manifest_tokens(mpath)
        if mt is not None:
            out["tokens"] = mt
            out["source"] = "bundle-manifest"
    return out


# ------------------------------------------------------------------
# Contained test execution (evidence contract, Oct 18 2026)
#
# A task's test_command and recorded patch are untrusted input: an
# agent wrote them. The runner below is the only place Bench executes
# either. It enforces what pure Python + git can enforce, and every
# test result carries a ``sandbox`` block stating plainly what is
# enforced and what is NOT - host filesystem writes by the test
# process and network access are not OS-enforced here, so a
# tests-executed verdict means "ran in this contained copy", never
# "ran in a sandbox".
# ------------------------------------------------------------------

#: verification_level enum (shared evidence contract). Rank order:
#: a report's level is the strongest level among its task rows.
VERIFICATION_LEVELS = ("none", "static-analysis", "tests-executed",
                       "live-agent")
_LEVEL_RANK = {name: i for i, name in enumerate(VERIFICATION_LEVELS)}

#: Output retained from a test process: the last this many
#: characters of combined stdout+stderr. The process's full output
#: is never stored in a report.
OUTPUT_TAIL_CHARS = 1000

#: POSIX resource limits for the test process (best-effort: applied
#: via preexec_fn where the OS allows, silently absent elsewhere).
TEST_CPU_SECONDS = 110          # just under the 120s wall timeout
TEST_FILE_SIZE_BYTES = 64 * 1024 * 1024
TEST_ADDRESS_SPACE_BYTES = 2 * 1024 * 1024 * 1024

SANDBOX_ENFORCED = [
    "environment scrubbed to an allowlist (PATH, LANG/LC_*, TMPDIR "
    "and HOME inside the temp area, PYTHONUSERBASE naming the "
    "user's own installed packages); parent-process secrets never "
    "reach the test process",
    "patch paths validated before git apply: '../', absolute, and "
    "symlink-escaping paths are refused, not applied",
    "project copied to a fresh temp directory; symlinks whose "
    "targets resolve outside the project are skipped and recorded, "
    "never followed",
    "wall-clock timeout of 120s on the test process",
    "captured output capped (last 1000 characters kept)",
    "POSIX resource limits where the OS allows: CPU seconds, "
    "max file size, address space, no core dump",
]

SANDBOX_NOT_ENFORCED = [
    "host filesystem writes by the test process are NOT prevented: "
    "the process runs with the user's permissions outside an OS "
    "sandbox and could write outside the temp copy",
    "network access is NOT blocked or monitored",
    "resource limits are best-effort POSIX rlimits, absent on "
    "non-POSIX platforms",
]


def strongest_verification_level(levels) -> str:
    """Strongest verification level among ``levels`` (contract rank:
    none < static-analysis < tests-executed < live-agent). Unknown
    values count as ``none``; an empty input is ``none``."""
    best = "none"
    for level in levels:
        if _LEVEL_RANK.get(level, 0) > _LEVEL_RANK[best]:
            best = level
    return best


def _sandbox_block(skipped_symlinks) -> dict:
    """The honest sandbox statement attached to every executed (or
    attempted) test result. Fresh lists each call: results are
    serialised into reports and must not share mutable state."""
    return {"enforced": list(SANDBOX_ENFORCED),
            "not_enforced": list(SANDBOX_NOT_ENFORCED),
            "skipped_symlinks": list(skipped_symlinks)}


def _scrubbed_env(tmp: str, dest: str) -> dict:
    """Minimal allowlist environment for the test process.

    The parent process's environment is NEVER inherited wholesale:
    API keys and other secrets an agent shell happens to carry must
    not reach untrusted test code. Only benign locale/path variables
    pass, and HOME/TMPDIR point inside the per-run temp area so
    tools that need a writable home land in the contained copy.
    """
    env = {}
    for key in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "SystemRoot",
                "WINDIR", "COMSPEC", "PATHEXT"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    env["HOME"] = dest
    # With HOME redirected into the temp area, Python would lose the
    # user site-packages, where the project's test tooling (pytest)
    # normally lives, and every real test command would fail for an
    # environment reason rather than a code reason. PYTHONUSERBASE
    # names a code location, not a secret: pass the parent's user
    # base through so installed packages stay importable.
    try:
        import site

        user_base = site.getuserbase()
    except Exception:
        user_base = None
    if user_base and os.path.isdir(user_base):
        env["PYTHONUSERBASE"] = user_base
    env["TMPDIR"] = tmp
    env["TEMP"] = tmp
    env["TMP"] = tmp
    # Keep test output deterministic and machine-readable.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    return env


def _set_resource_limits(cpu_seconds: int) -> None:
    """Apply the contained-runner POSIX rlimits in the child process.

    Runs after fork, before exec (as a preexec_fn body). Any limit
    the OS refuses is skipped silently - the wall-clock timeout and
    the report's not_enforced list cover the gap honestly.
    """
    if resource is None:  # pragma: no cover - non-POSIX
        return
    limits = [
        (resource.RLIMIT_CPU, cpu_seconds),
        (resource.RLIMIT_FSIZE, TEST_FILE_SIZE_BYTES),
        (resource.RLIMIT_CORE, 0),
    ]
    if hasattr(resource, "RLIMIT_AS"):
        limits.append((resource.RLIMIT_AS, TEST_ADDRESS_SPACE_BYTES))
    for what, value in limits:
        try:
            _soft, hard = resource.getrlimit(what)
            if hard != resource.RLIM_INFINITY and hard < value:
                value = hard
            resource.setrlimit(what, (value, value))
        except (ValueError, OSError):
            continue


def _apply_resource_limits() -> None:
    """preexec_fn for the test process: POSIX rlimits, best-effort."""
    _set_resource_limits(TEST_CPU_SECONDS)


def _preexec_agent_limits(cpu_seconds: int):
    """preexec_fn for the Tier B agent process, or None off-POSIX.

    Same limit set as the test runner (file size, address space, no
    core dump); only the CPU allowance differs, scaled to the
    agent's own wall-clock timeout by the caller.
    """
    if resource is None:  # pragma: no cover - non-POSIX
        return None

    def _apply() -> None:
        _set_resource_limits(cpu_seconds)

    return _apply


# ------------------------------------------------------------------
# Tier B live-agent containment statement (evidence contract)
#
# A live run executes a user-configured agent command inside the
# same contained copy discipline as the test runner above: safe
# copy, scrubbed environment, rlimits, timeout. The agent is a real
# program the user chose to run, though - not a patch Bench
# validated - so the enforced / not-enforced split differs from
# Tier A's and every live row states it in its own sandbox block.
# ------------------------------------------------------------------

LIVE_SANDBOX_ENFORCED = [
    "project copied to a fresh temp directory; the agent process "
    "runs with that copy as its working directory; symlinks whose "
    "targets resolve outside the project are skipped and recorded, "
    "never followed",
    "environment scrubbed to the same allowlist as the contained "
    "test runner (PATH, LANG/LC_*, TMPDIR and HOME inside the temp "
    "area, PYTHONUSERBASE naming the user's own installed "
    "packages); parent-process secrets never reach the agent "
    "process; the only additions are GHOSTBENCH_TASK_DIR, "
    "GHOSTBENCH_TASK_ID and GHOSTBENCH_TASK_PROMPT",
    "wall-clock timeout on the agent process (configurable via "
    "--agent-timeout, default 300s) and on the task test process "
    "(120s, as in Tier A)",
    "captured agent and test output capped (last 1000 characters "
    "kept)",
    "POSIX resource limits where the OS allows: CPU seconds, max "
    "file size, address space, no core dump",
]

LIVE_SANDBOX_NOT_ENFORCED = [
    "host filesystem writes by the agent process are NOT "
    "prevented: the agent runs with the user's permissions outside "
    "an OS sandbox; Bench directs its work at the task copy by "
    "setting the working directory there, but nothing enforces "
    "that it writes nowhere else",
    "network access is NOT blocked or monitored: the configured "
    "agent may use the network; Bench itself makes no network calls",
    "resource limits are best-effort POSIX rlimits, absent on "
    "non-POSIX platforms",
]


def _live_sandbox_block(skipped_symlinks) -> dict:
    """The honest containment statement attached to every live-agent
    task row. Fresh lists each call, like :func:`_sandbox_block`."""
    return {"enforced": list(LIVE_SANDBOX_ENFORCED),
            "not_enforced": list(LIVE_SANDBOX_NOT_ENFORCED),
            "skipped_symlinks": list(skipped_symlinks)}


_DIFF_GIT_RE = re.compile(r"^diff --git (.+?) (.+)$")
_OLD_FILE_RE2 = re.compile(r"^--- (.+)$")
_NEW_FILE_RE2 = re.compile(r"^\+\+\+ (.+)$")
_MODE_RE = re.compile(r"^(?:new file mode|old mode|new mode) (\d+)$")


def _strip_diff_prefix(path: str) -> str:
    """Remove the a/ or b/ prefix git puts on diff header paths."""
    if path[:2] in ("a/", "b/"):
        return path[2:]
    return path


def _collect_patch_entries(patch_text: str) -> list[dict]:
    """Per-file entries of a unified diff: every path the patch can
    write to (the +++ target, plus the --- source for renames and
    deletions) and, for symlink creations (mode 120000), the link
    target recorded in the added body line."""
    entries: list[dict] = []
    current: dict | None = None
    in_hunk = False

    def _add_path(entry, raw):
        if raw != "/dev/null":
            path = _strip_diff_prefix(raw)
            if path not in entry["paths"]:
                entry["paths"].append(path)

    for line in (patch_text or "").splitlines():
        m = _DIFF_GIT_RE.match(line)
        if m:
            current = {"paths": [], "symlink_target": None}
            entries.append(current)
            in_hunk = False
            for raw in m.groups():
                _add_path(current, raw.strip().strip('"'))
            continue
        if line.startswith(("--- ", "+++ ")) and current is None:
            # A headerless diff (no 'diff --git' line): git apply
            # accepts these, so the validator must see them too.
            current = {"paths": [], "symlink_target": None}
            entries.append(current)
            in_hunk = False
        if current is None:
            continue
        m = _MODE_RE.match(line)
        if m:
            current["is_symlink"] = (m.group(1) == "120000")
            continue
        m = _OLD_FILE_RE2.match(line)
        if m and not in_hunk:
            _add_path(current, m.group(1).strip().strip('"'))
            continue
        m = _NEW_FILE_RE2.match(line)
        if m and not in_hunk:
            _add_path(current, m.group(1).strip().strip('"'))
            continue
        if line.startswith("@@"):
            in_hunk = True
            continue
        if in_hunk and line.startswith("+") \
                and current.get("is_symlink") \
                and current["symlink_target"] is None:
            current["symlink_target"] = line[1:]
    return entries


def _contained_in(root_resolved: str, candidate: str) -> bool:
    """True when ``candidate`` (already resolved) is root or inside it."""
    return candidate == root_resolved or os.path.commonpath(
        [root_resolved, candidate]) == root_resolved


def _validate_patch_paths(patch_text: str, dest: str) -> list[str]:
    """Refuse patch paths that escape the temp copy BEFORE git apply.

    Follows the GhostVerify pattern (its patch.py ``_safe_target``):
    a patch path is attacker-shaped input. ``../`` segments climb
    out, an absolute path ignores the root, and a symlinked parent
    inside the copy can point outside it - so every path is checked
    after resolution against the resolved copy root, including paths
    that traverse a symlink the same patch creates. Returns a list
    of problems; empty means the patch may go to git apply (which
    remains a second line of defence, not the only one).
    """
    problems: list[str] = []
    root = os.path.realpath(dest)
    created_links: dict[str, str] = {}  # rel link path -> resolved target
    for entry in _collect_patch_entries(patch_text):
        for rel in entry["paths"]:
            if os.path.isabs(rel):
                problems.append(f"patch path is absolute: {rel!r}")
                continue
            resolved = os.path.realpath(os.path.join(root, rel))
            if not _contained_in(root, resolved):
                problems.append(
                    f"patch path escapes the temporary copy: {rel!r}")
                continue
            # A path through a symlink this same patch creates must
            # stay inside too, wherever that symlink points.
            parts = rel.replace("\\", "/").split("/")
            for i in range(1, len(parts)):
                parent = "/".join(parts[:i])
                if parent in created_links:
                    through = os.path.realpath(os.path.join(
                        created_links[parent], *parts[i:]))
                    if not _contained_in(root, through):
                        problems.append(
                            f"patch path escapes the temporary copy "
                            f"through a symlink the patch creates: "
                            f"{rel!r}")
                    break
        if entry.get("is_symlink"):
            target = entry.get("symlink_target")
            for rel in entry["paths"]:
                link_abs = os.path.join(root, rel)
                if target is None:
                    resolved_target = link_abs  # unknown: treat as self
                elif os.path.isabs(target):
                    resolved_target = os.path.realpath(target)
                else:
                    resolved_target = os.path.realpath(
                        os.path.join(os.path.dirname(link_abs), target))
                created_links[rel.replace("\\", "/")] = resolved_target
                if not _contained_in(root, resolved_target):
                    problems.append(
                        f"patch creates a symlink escaping the "
                        f"temporary copy: {rel!r} -> {target!r}")
    return problems


def _copy_project_safely(src: str, dest: str) -> list[str]:
    """Copy the project tree, never following an escaping symlink.

    ``shutil.copytree`` with its default settings silently follows
    symlinks, which copies content from OUTSIDE the project into the
    test copy (and a dangling symlink crashes the copy). Here a
    symlink whose target resolves outside the project is skipped
    and recorded; a symlink to somewhere inside the project is
    copied as the regular file/directory it points at, as before.
    Returns the sorted project-relative paths of skipped symlinks.
    """
    root = os.path.realpath(src)
    skipped: list[str] = []

    def _copy_one(src_path, dst_path):
        if os.path.islink(src_path):
            resolved = os.path.realpath(src_path)
            if not _contained_in(root, resolved) \
                    or not os.path.exists(resolved):
                skipped.append(os.path.relpath(src_path, src))
                return dst_path
        return shutil.copy2(src_path, dst_path)

    shutil.copytree(src, dest, copy_function=_copy_one,
                    ignore=shutil.ignore_patterns(
                        ".git", "__pycache__", "node_modules"))
    return sorted(skipped)


def _apply_patch_git(temp_root: str, patch_text: str) -> tuple[bool, str]:
    patch_file = os.path.join(temp_root, ".ghostbench-patch.diff")
    with open(patch_file, "w", encoding="utf-8") as fh:
        fh.write(patch_text)
    try:
        proc = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", patch_file],
            cwd=temp_root, capture_output=True, text=True, timeout=30)
        return proc.returncode == 0, (proc.stderr or proc.stdout or "")[-500:]
    except Exception as exc:  # git missing etc: reported, not hidden
        return False, f"git apply unavailable/failed: {exc}"
    finally:
        try:
            os.remove(patch_file)
        except OSError:
            pass


def _run_test_in_temp(project: Project, task: Task,
                        patch_text: str | None) -> dict:
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
    tmp = tempfile.mkdtemp(prefix="ghostbench-test-")
    try:
        dest = os.path.join(tmp, "project")
        skipped_symlinks = _copy_project_safely(project.path, dest)
        sandbox = _sandbox_block(skipped_symlinks)
        if patch_text:
            problems = _validate_patch_paths(patch_text, dest)
            if problems:
                # Refused BEFORE git apply: containment is Bench's
                # own verdict, not whatever the local git binary
                # happens to enforce.
                return {"ran": False, "status": "patch-apply-failed",
                        "detail": "patch refused (containment): "
                                  + "; ".join(problems),
                        "sandbox": sandbox,
                        "skipped_symlinks": skipped_symlinks}
            ok, msg = _apply_patch_git(dest, patch_text)
            if not ok:
                return {"ran": False, "status": "patch-apply-failed",
                        "detail": msg, "sandbox": sandbox,
                        "skipped_symlinks": skipped_symlinks}
        try:
            proc = subprocess.run(
                argv, cwd=dest, capture_output=True, text=True,
                timeout=120, env=_scrubbed_env(tmp, dest),
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
            # Missing binary / not executable: a scored outcome for
            # this task, not a crash that loses the whole run.
            return {"ran": True, "status": "error", "exit_code": None,
                    "detail": str(exc), "sandbox": sandbox,
                    "skipped_symlinks": skipped_symlinks}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_task(corpus: Corpus, project: Project, task: Task, *,
               suite: str = "slice", run_tests: bool = False,
               model: str | None = None, table: dict | None = None) -> dict:
    """Score one task in Tier A and return its report row.

    The row carries the full and per-variant token estimates, the
    normalised Verify verdict, the recorded-patch facts, the test
    outcome, a ``status`` of ``pass`` / ``fail`` / ``unknown``, and
    every failure reason in ``failures`` (failures are shown, never
    hidden). Tests run only when ``run_tests`` is true, in a temp copy.
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

    suite_extras = {"slice": [], "verify": ["verified"],
                    "recall": ["recalled"], "proxy": ["proxied"]}
    if suite not in suite_extras:
        raise ValueError(
            f"unknown suite: {suite!r} "
            f"(expected one of {sorted(suite_extras)})")
    wanted_extra = suite_extras[suite]
    for name, spec in (task.variants or {}).items():
        if name in ("full", "sliced"):
            continue
        # The suite gates which extra arm is measured. An empty
        # wanted list (slice) means NO extra arm: the old truthiness
        # check treated [] as 'no filter' and measured every extra
        # variant in a slice run.
        if name not in wanted_extra:
            continue
        variants[name] = _variant_from_spec(corpus, spec)

    budget = task.budget_tokens
    for name, var in variants.items():
        var["saving_pct_vs_full"] = saving_pct(full_tokens, var["tokens"])
        var["fit_success"] = (
            None if budget is None or var["tokens"] is None
            else var["tokens"] <= budget)
        var["estimated_input_cost_usd"] = estimate_input_cost_usd(
            var["tokens"] or 0, model, table) if var["tokens"] is not None else None
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

    patch_text = read_task_patch(corpus, project, task)
    patch = parse_patch(patch_text) if patch_text is not None else None
    files_score = score_files_touched(patch, task.expected_files)

    # Expected-symbol coverage: the derived sliced arm is built from
    # expected_files, so an expected symbol absent from those files is
    # a symbol the slice cannot contain - a real gap, surfaced as a
    # failure like a Verify hard gap. When the sliced arm is a provided
    # bundle/manifest Bench cannot inspect its contents, so the check
    # is reported descriptively and does NOT gate the task (Bench
    # surfaces what it cannot measure instead of guessing).
    file_texts = {}
    for rel in task.expected_files:
        text = _read_text(os.path.join(project.path, rel))
        if text is not None:
            file_texts[rel] = text
    symbols_score = score_expected_symbols(
        task.expected_symbols, file_texts, patch_text)
    sliced_source = variants["sliced"].get("source")
    symbols_score["sliced_source"] = sliced_source
    applies_to_sliced = sliced_source == "derived:expected-files"
    symbols_score["applies_to_sliced"] = applies_to_sliced
    missing_slice_symbols = (
        symbols_score["missing_from_expected_files"]
        if applies_to_sliced else [])
    if missing_slice_symbols:
        failures.append(
            "expected symbol(s) missing from sliced context "
            "(derived from expected_files): "
            + ", ".join(missing_slice_symbols))

    test_result = {"ran": False, "status": "not-run"}
    if run_tests and task.test_command:
        test_result = _run_test_in_temp(project, task, patch_text)
        if test_result.get("status") not in ("pass",):
            failures.append(f"test command: {test_result.get('status')}")



    if test_result["ran"]:
        status = "pass" if test_result["status"] == "pass" else "fail"
    elif patch is not None:
        patch_fail = False
        if patch["is_empty"]:
            patch_fail = True
            failures.append("recorded patch is empty")
        if hard_gaps:
            patch_fail = True
        if missing_slice_symbols:
            patch_fail = True
        if not files_score["matched_files"]:
            patch_fail = True
            failures.append("recorded patch touches no expected file")
        status = "fail" if patch_fail else "pass"
    elif hard_gaps or missing_slice_symbols:
        status = "fail"
    else:
        status = "unknown"
        failures.append("no recorded patch and no test result: "
                        "task outcome cannot be scored in Tier A")

    # Evidence contract (verification_level): a row whose tests
    # actually ran in the contained runner is tests-executed; any
    # other Tier A row that carries static evidence (tokens
    # measured, a recorded patch scored, Verify/symbol signals) is
    # static-analysis - even when the task outcome itself stays
    # "unknown", because the static measurement did happen. A row
    # over an empty/unreadable project measured nothing at all and
    # is none. Tier A never produces live-agent rows, and no row is
    # ever labelled above the evidence that backs it.
    if test_result.get("ran"):
        verification_level = "tests-executed"
    elif patch is not None or hard_gaps or missing_slice_symbols \
            or full_tokens > 0:
        verification_level = "static-analysis"
    else:
        verification_level = "none"

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
        "status": status,
        "verification_level": verification_level,
        "failures": failures,
        "flaky": False,
    }


def run_corpus(corpus: Corpus, *, suite: str = "slice",
               run_tests: bool = False, task_filter: set | None = None,
               model: str | None = None) -> dict:
    """Run Tier A over a corpus and return the full report dict.

    ``task_filter``, when given, restricts the run to those task ids;
    the report then labels itself a subset. The returned dict is
    exactly what ``report.write_json_report`` serialises, including
    version stamps and the ``honest_scope`` box.
    """
    table = load_price_table()
    rows = []
    for project, task in corpus.all_tasks():
        if task_filter and task.id not in task_filter:
            continue
        rows.append(run_task(corpus, project, task, suite=suite,
                             run_tests=run_tests, model=model, table=table))
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
                        if r["symbols_score"]["applies_to_sliced"]
                        and r["symbols_score"]["missing_from_expected_files"]),
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
                # A saving against the full total is only meaningful
                # when every task contributed a token total.
                "saving_pct_vs_full": (
                    None if partial else
                    saving_pct(totals["full_tokens"], total_toks)),
                "fit_success_rate": (
                    round(sum(1 for f in fits if f) * 100.0 / len(fits), 1)
                    if fits else None),
            }
    now = datetime.now(timezone.utc)
    fingerprint = hashlib.sha256(json.dumps(
        {"corpus": corpus.name, "version": corpus.version, "rows": rows},
        sort_keys=True, default=str).encode()).hexdigest()[:12]
    subset = (sorted(task_filter) if task_filter else None)
    # Report-level verification level = strongest level among rows.
    report_level = strongest_verification_level(
        r["verification_level"] for r in rows)
    # The report-level sandbox block describes the contained runner
    # whenever any row's tests ran (every executed row carries the
    # same enforced/not_enforced lists); the per-row blocks remain
    # authoritative for skipped_symlinks.
    report_sandbox = None
    for r in rows:
        block = (r.get("test") or {}).get("sandbox")
        if block:
            report_sandbox = {"enforced": block["enforced"],
                              "not_enforced": block["not_enforced"]}
            break
    not_measured = [
        "live agent task completion (Tier B, opt-in, not run)",
        "answer quality (no LLM judge in v0.1)",
    ]
    if report_level == "tests-executed":
        tier_scope = ("A (tests executed in the contained runner; "
                      "no model, no spend)")
    elif report_level == "static-analysis":
        tier_scope = "A (static, no model, no spend)"
    else:
        tier_scope = "A (no task measured; no model, no spend)"
    if not run_tests:
        not_measured.append(
            "task test commands (not run; pass run_tests to execute "
            "them in the contained runner)")
    return {
        "tool": "ghostbench", "tool_version": __version__,
        "tier": "A", "suite": suite,
        "verification_level": report_level,
        "provenance": "live",
        "sandbox": report_sandbox,
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
        "model_for_cost_estimates": model,
        "cost_note": ("Costs are ESTIMATES from a local dated price "
                      "table, never billed amounts."),
        "run_tests": run_tests,
        "honest_scope": {
            "tier": tier_scope,
            "tasks_measured": len(rows),
            "what_was_not_measured": not_measured,
        },
        "totals": totals,
        "tasks": rows,
        "failures_visible": [
            {"project": r["project"], "task": r["task"],
             "failures": r["failures"]}
            for r in rows if r["failures"]],
    }


def append_ledger(report: dict, ledger_path: str) -> str:
    """Append one stamped summary record for ``report`` to the ledger.

    The ledger is JSON Lines (``.ghostbench-history.jsonl`` by
    default). Returns ``ledger_path``.
    """
    os.makedirs(os.path.dirname(os.path.abspath(ledger_path)), exist_ok=True)
    record = {
        "ts": report["created_utc"], "run_id": report["run_id"],
        "tool_version": report["tool_version"], "tier": report["tier"],
        "verification_level": report.get("verification_level"),
        "estimator_version": report["estimator_version"],
        "corpus": report["corpus"]["name"],
        "corpus_version": report["corpus"]["version"],
        "totals": report["totals"],
    }
    with open(ledger_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return ledger_path


def read_ledger(ledger_path: str) -> list[dict]:
    """Read all ledger records; an absent ledger reads as an empty list."""
    if not os.path.isfile(ledger_path):
        return []
    out = []
    with open(ledger_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                # A torn final line (crash mid-append) must not make
                # the whole history unreadable.
                continue
            if isinstance(record, dict):
                out.append(record)
    return out
