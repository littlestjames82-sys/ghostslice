"""Shared helpers for the GhostIndex test suite.

The suite is black-box: it drives the PLAN-specified CLI

    ghostindex index  <root> [<root> ...] [--db <path>]
    ghostindex update [<root> ...]       [--db <path>]
    ghostindex search "<terms>" [--root <path>] [--limit N]
                      [--context N] [--max-tokens N] [--any] [--json]
    ghostindex list | stats | remove <root> | doctor

and never imports GhostIndex internals, so it stays valid whatever
module layout the core build uses. CLI discovery order:

1. ``GHOSTINDEX_CMD`` env var (a shell-style command prefix).
2. A ``ghostindex`` executable on PATH (installed console script).
3. ``python -m ghostindex`` with ``PYTHONPATH`` set to ``src/`` and
   then to the repo root (covers a ``src/`` layout and a flat layout).

Where the PLAN leaves the exact placement of ``--db`` open (global
flag, per-subcommand flag, or the ``GHOSTINDEX_DB`` environment
variable), the helpers probe the forms once, in that order, and cache
the first form the real CLI accepts. That tolerance is about flag
placement only: every behavioural assertion in the tests (what is
indexed, what search returns, exit codes, counts) is strict.

Search exit codes are the PLAN contract: 0 = matches found,
1 = no matches, 2 = could not search.
"""
from __future__ import annotations

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

_CLI_PREFIX: list[str] | None = None
_CLI_ENV: dict | None = None
_CLI_PROBED = False
_DB_FORM: str | None = None  # "suffix" | "prefix" | "env"


def _probe(prefix: list[str], env_extra: dict | None = None) -> bool:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.run(
            prefix + ["--help"],
            capture_output=True, text=True, timeout=20, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and "ghostindex" in (
        proc.stdout + proc.stderr).lower()


def cli_prefix() -> list[str] | None:
    """Return the command prefix for the ghostindex CLI, or None."""
    global _CLI_PREFIX, _CLI_ENV, _CLI_PROBED
    if _CLI_PROBED:
        return _CLI_PREFIX
    _CLI_PROBED = True

    env_cmd = os.environ.get("GHOSTINDEX_CMD")
    if env_cmd and _probe(shlex.split(env_cmd)):
        _CLI_PREFIX = shlex.split(env_cmd)
        _CLI_ENV = {}
        return _CLI_PREFIX

    exe = shutil.which("ghostindex")
    if exe and _probe([exe]):
        _CLI_PREFIX = [exe]
        _CLI_ENV = {}
        return _CLI_PREFIX

    for base in (REPO_ROOT / "src", REPO_ROOT):
        if (base / "ghostindex").is_dir() or (base / "ghostindex.py").exists():
            env = {"PYTHONPATH": str(base)}
            if _probe([sys.executable, "-m", "ghostindex"], env):
                _CLI_PREFIX = [sys.executable, "-m", "ghostindex"]
                _CLI_ENV = env
                return _CLI_PREFIX
    return None


def cli_available() -> bool:
    return cli_prefix() is not None


def run_cli(args: list[str], db: Path | None = None,
            cwd: Path | None = None, timeout: int = 60,
            env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """Run the CLI. ``db`` selects the index database using the first
    placement form the CLI accepts (cached after the first success)."""
    prefix = cli_prefix()
    assert prefix is not None, "ghostindex CLI not available"
    env = dict(os.environ)
    if _CLI_ENV:
        env.update(_CLI_ENV)
    if env_extra:
        env.update(env_extra)

    forms: list[tuple[str, list[str], dict]] = []
    if db is not None:
        forms.append(("suffix", args + ["--db", str(db)], {}))
        forms.append(("prefix", ["--db", str(db)] + args, {}))
        forms.append(("env", args, {"GHOSTINDEX_DB": str(db)}))
    else:
        forms.append(("none", args, {}))

    global _DB_FORM
    if _DB_FORM is not None and db is not None:
        forms.sort(key=lambda f: 0 if f[0] == _DB_FORM else 1)

    last: subprocess.CompletedProcess | None = None
    for name, argv, extra in forms:
        run_env = dict(env)
        run_env.update(extra)
        proc = subprocess.run(
            prefix + argv, capture_output=True, text=True,
            timeout=timeout, cwd=str(cwd) if cwd else None, env=run_env,
        )
        last = proc
        out = proc.stdout + proc.stderr
        # An argparse usage error means this placement is wrong; try the
        # next form. Anything else is a real answer from the CLI.
        if proc.returncode == 2 and ("usage:" in out.lower()
                                     and ("unrecognized" in out.lower()
                                          or "invalid choice" in out.lower()
                                          or "expected one argument" in out.lower())):
            continue
        if db is not None and name != "none":
            _DB_FORM = name
        return proc
    assert last is not None
    return last


def index_roots(db: Path, roots: list[Path], **kw) -> subprocess.CompletedProcess:
    return run_cli(["index"] + [str(r) for r in roots], db=db, **kw)


def update_roots(db: Path, roots: list[Path] | None = None,
                 **kw) -> subprocess.CompletedProcess:
    args = ["update"] + [str(r) for r in (roots or [])]
    return run_cli(args, db=db, **kw)


def search(db: Path, query: str, extra: list[str] | None = None,
           **kw) -> subprocess.CompletedProcess:
    return run_cli(["search", query] + (extra or []), db=db, **kw)


def search_json(db: Path, query: str, extra: list[str] | None = None,
                **kw) -> tuple[subprocess.CompletedProcess, list[dict] | None]:
    """Search with --json. Returns (proc, hits) where hits is a
    normalised list of dicts, or None when the output is not JSON."""
    proc = search(db, query, (extra or []) + ["--json"], **kw)
    if proc.returncode not in (0, 1):
        return proc, None
    text = proc.stdout.strip()
    try:
        data = json.loads(text)
    except ValueError:
        return proc, None
    if isinstance(data, dict):
        for key in ("hits", "results", "matches", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data] if data else []
    if not isinstance(data, list):
        return proc, None
    return proc, [normalise_hit(h) for h in data if isinstance(h, dict)]


def normalise_hit(hit: dict) -> dict:
    """Normalise one JSON hit across reasonable key namings."""
    def pick(*keys, default=None):
        for k in keys:
            if hit.get(k) not in (None, ""):
                return hit[k]
        return default

    path = pick("path", "rel", "relpath", "relative_path", "file",
                "filepath", default="")
    excerpt = pick("excerpt", "text", "snippet", "body", "content",
                   "context", default="")
    if isinstance(excerpt, list):  # excerpt as a list of lines
        excerpt = "\n".join(str(x) for x in excerpt)
    lines = pick("lines", "line_range", "line_ranges", "start_line",
                 "line", default=None)
    # Windowed excerpt shape: {"windows": [{"start_line": n,
    # "end_line": m, "text": "...", "match_lines": [...]}, ...]}.
    windows = hit.get("windows")
    if isinstance(windows, list) and windows:
        texts = [str(w.get("text", "")) for w in windows
                 if isinstance(w, dict)]
        if texts:
            excerpt = "\n".join(texts)
        ranges = [(w.get("start_line"), w.get("end_line"))
                  for w in windows if isinstance(w, dict)]
        if lines is None and ranges:
            lines = ranges
    return {
        "root": str(pick("root", "project", "project_root", default="")),
        "path": str(path),
        "excerpt": str(excerpt),
        "lines": lines,
        "excerpt_tokens": _first_int(hit, ("excerpt_tokens", "excerpt_tokens_est",
                                           "excerpt_token_estimate",
                                           "tokens_excerpt")),
        "file_tokens": _first_int(hit, ("file_tokens", "file_tokens_est",
                                        "file_token_estimate",
                                        "tokens_file", "total_tokens",
                                        "tokens")),
        "raw": hit,
    }


def _first_int(d: dict, keys) -> int | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return None


_COUNT_PATTERNS = {
    "added": (r"(\d+)\s+added\b", r"\badded\D{0,20}?(\d+)"),
    "changed": (r"(\d+)\s+changed\b", r"\bchanged\D{0,20}?(\d+)",
                r"(\d+)\s+updated\b", r"\bupdated\D{0,20}?(\d+)"),
    "removed": (r"(\d+)\s+removed\b", r"\bremoved\D{0,20}?(\d+)",
                r"(\d+)\s+deleted\b", r"\bdeleted\D{0,20}?(\d+)"),
    "unchanged": (r"(\d+)\s+unchanged\b", r"\bunchanged\D{0,20}?(\d+)"),
}


def parse_update_counts(output: str) -> dict[str, int | None]:
    """Pull added/changed/removed/unchanged counts out of update
    output (also accepts a JSON report). Missing keys come back None."""
    counts: dict[str, int | None] = {k: None for k in _COUNT_PATTERNS}
    text = output.strip()
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        for k in counts:
            v = data.get(k)
            if isinstance(v, (int, float)):
                counts[k] = int(v)
        if all(v is not None for v in counts.values()):
            return counts
    low = output.lower()
    for key, patterns in _COUNT_PATTERNS.items():
        if counts[key] is not None:
            continue
        # Multi-root reports print one line per root; the totals the
        # PLAN promises are the sums across those lines.
        total: int | None = None
        for pat in patterns:
            found = re.findall(pat, low)
            if found:
                total = sum(int(x) for x in found)
                break
        counts[key] = total
    return counts


def copy_fixture(name: str, dest_parent: Path) -> Path:
    src = FIXTURES / name
    dst = dest_parent / name
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
    return dst


def tree_snapshot(root: Path) -> dict[str, str]:
    """Map rel path -> sha256 for every file under root."""
    import hashlib

    snap = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            snap[p.relative_to(root).as_posix()] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return snap
