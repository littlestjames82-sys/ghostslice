"""Shared helpers for the GhostReview test suite.

Black-box: drives the CLI, never imports GhostReview internals.

Assumed canonical CLI (recorded in REPORT_B.md; helpers try a
small set of argument-shape variants so a differing-but-equivalent
Agent A shape still gets exercised, and cache the shape that
first succeeds):

    ghostreview review <project> --diff <file.diff> -o <outdir>
        [--verify-report <verify-report.json>]
        [--scope-pack <pack-dir|scope.json>]

Outputs searched leniently: REVIEW.md and review.json inside the
output dir, the project, or the current directory tree under out.

Discovery: GHOSTREVIEW_CMD env, `ghostreview` on PATH, or
`python -m ghostreview` with PYTHONPATH=src (then repo root).
If none responds to --help, CLI tests skip with a reason and the
fixture tests still run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
DIFFS = FIXTURES / "diffs"
REPORTS = FIXTURES / "reports"
SAMPLE_PROJECT = FIXTURES / "sample_project"
FAKE_SECRET = "FAKE-SECRET-VALUE-12345-not-real"

_CLI_PREFIX: list[str] | None = None
_CLI_ENV: dict | None = None
_CLI_PROBED = False
_WORKING_SHAPE: int | None = None


def _probe(prefix, env_extra=None) -> bool:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.run(prefix + ["--help"], capture_output=True,
                              text=True, timeout=20, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and "ghostreview" in (
        proc.stdout + proc.stderr).lower()


def cli_prefix():
    global _CLI_PREFIX, _CLI_ENV, _CLI_PROBED
    if _CLI_PROBED:
        return _CLI_PREFIX
    _CLI_PROBED = True
    env_cmd = os.environ.get("GHOSTREVIEW_CMD")
    if env_cmd and _probe(shlex.split(env_cmd)):
        _CLI_PREFIX, _CLI_ENV = shlex.split(env_cmd), {}
        return _CLI_PREFIX
    exe = shutil.which("ghostreview")
    if exe and _probe([exe]):
        _CLI_PREFIX, _CLI_ENV = [exe], {}
        return _CLI_PREFIX
    for base in (REPO_ROOT / "src", REPO_ROOT):
        if (base / "ghostreview").is_dir() or (base / "ghostreview.py").exists():
            env = {"PYTHONPATH": str(base)}
            if _probe([sys.executable, "-m", "ghostreview"], env):
                _CLI_PREFIX = [sys.executable, "-m", "ghostreview"]
                _CLI_ENV = env
                return _CLI_PREFIX
    return None


def cli_available() -> bool:
    return cli_prefix() is not None


def cli_env() -> dict:
    cli_prefix()
    env = dict(os.environ)
    if _CLI_ENV:
        env.update(_CLI_ENV)
    return env


def _run(prefix_args, timeout=60):
    prefix = cli_prefix()
    assert prefix is not None, "ghostreview CLI not available"
    return subprocess.run(prefix + prefix_args, capture_output=True,
                          text=True, timeout=timeout, env=cli_env())


def _shapes(project, diff, out, verify, scope):
    """Argument-shape variants, canonical first."""
    extra = []
    if verify:
        extra += ["--verify-report", str(verify)]
    if scope:
        extra += ["--scope-pack", str(scope)]
    d, o, p = str(diff), str(out), str(project)
    return [
        ["review", p, "--diff", d, "-o", o] + extra,
        ["review", p, "--diff", d, "--out", o] + extra,
        [p, "--diff", d, "-o", o] + extra,
        ["review", "--diff", d, "-o", o] + extra,
        ["--diff", d, "-o", o] + extra,
        ["review", d, "-o", o] + extra,
        ["review", p, "--diff", d] + extra,
    ]


_USAGE_HINTS = ("unrecognized", "invalid choice", "usage:",
                "no such option", "unexpected")


def run_review(project, diff, out, verify=None, scope=None, timeout=60):
    """Run a review, trying shape variants on usage errors only."""
    global _WORKING_SHAPE
    shapes = _shapes(project, diff, out, verify, scope)
    order = list(range(len(shapes)))
    if _WORKING_SHAPE is not None:
        order = [_WORKING_SHAPE] + [i for i in order if i != _WORKING_SHAPE]
    last = None
    for idx in order:
        proc = _run(shapes[idx], timeout=timeout)
        last = proc
        blob = (proc.stdout + proc.stderr).lower()
        if proc.returncode == 2 and any(h in blob for h in _USAGE_HINTS) \
                and "could not" not in blob and "no such file" not in blob \
                and "not found" not in blob:
            continue  # likely wrong shape, try next
        _WORKING_SHAPE = idx
        return proc
    return last


def find_outputs(out, extra_bases=()):
    """Locate (review.json, REVIEW.md) leniently."""
    rj = md = None
    bases = [Path(out)] + [Path(b) for b in extra_bases]
    seen = []
    for base in bases:
        if not base.exists():
            continue
        cands = [base] if base.is_file() else list(base.rglob("*"))
        for cand in cands:
            seen.append(cand)
            if cand.name.lower() == "review.json" and rj is None:
                rj = cand
            if cand.name.lower() == "review.md" and md is None:
                md = cand
    return rj, md


def load_review_json(out, extra_bases=()):
    rj, _ = find_outputs(out, extra_bases)
    if rj is None:
        return None
    try:
        return json.loads(rj.read_text(encoding="utf-8"))
    except ValueError:
        return None


def review_text(out, extra_bases=()):
    rj, md = find_outputs(out, extra_bases)
    parts = []
    for p in (rj, md):
        if p is not None:
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def copy_project(dest):
    dest = Path(dest)
    shutil.copytree(SAMPLE_PROJECT, dest,
                    ignore=shutil.ignore_patterns("__pycache__"))
    return dest


def tree_hashes(root):
    out = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            out[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()).hexdigest()
    return out


# --- fixture diff parsing (tests only, validates planted fixtures) ---

SECRET_PATH_RE = re.compile(
    r"(^|/)(\.env(\..*)?|credentials[^/]*|secrets?[^/]*|id_rsa[^/]*|"
    r"[^/]*\.(pem|key|p12|pfx))$", re.IGNORECASE)
TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|spec)/|(^|/)test_[^/]*\.py$|_test\.py$|\.test\.[^/]+$|"
    r"\.spec\.[^/]+$", re.IGNORECASE)


def is_secret_path(path: str) -> bool:
    return bool(SECRET_PATH_RE.search(path.replace("\\", "/")))


def is_test_path(path: str) -> bool:
    return bool(TEST_PATH_RE.search(path.replace("\\", "/")))


def parse_diff(path):
    """Minimal unified-diff parser for fixture validation.

    Returns dict with files: [{old, new, status}], additions,
    deletions (content lines only, not ---/+++ headers).
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    files, cur = [], None
    additions = deletions = 0
    for line in text.splitlines():
        if line.startswith("diff --git "):
            cur = {"old": None, "new": None, "status": "modified"}
            files.append(cur)
            m = re.match(r"diff --git a/(.*) b/(.*)$", line)
            if m:
                cur["old"], cur["new"] = m.group(1), m.group(2)
        elif cur is not None and line.startswith("new file mode"):
            cur["status"] = "added"
        elif cur is not None and line.startswith("deleted file mode"):
            cur["status"] = "deleted"
        elif cur is not None and line.startswith("Binary files "):
            cur["status"] = "binary"
        elif cur is not None and line.startswith("rename from "):
            cur["status"] = "renamed"
            cur["old"] = line[len("rename from "):].strip()
        elif cur is not None and line.startswith("rename to "):
            cur["new"] = line[len("rename to "):].strip()
        elif line.startswith("+++") or line.startswith("---"):
            continue
        elif line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return {"files": files, "additions": additions,
            "deletions": deletions, "text": text}


def flags_of(data) -> list:
    """Pull a flags/findings list out of review.json, leniently."""
    if not isinstance(data, dict):
        return []
    for key in ("flags", "findings", "warnings", "risks", "issues"):
        v = data.get(key)
        if isinstance(v, list):
            return v
    for key in ("review", "result", "summary"):
        nested = data.get(key)
        if isinstance(nested, dict):
            got = flags_of(nested)
            if got:
                return got
    return []
