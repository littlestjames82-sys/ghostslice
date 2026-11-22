"""Shared helpers for the GhostEnv test suite.

Black-box discipline (same as GhostVerify / GhostExposure Agent B):
the suite drives the CLI described in the task / PLAN

    GhostEnv = .env doctor: compares code env usage against
    .env and .env.example, NAMES ONLY, never values, and can
    generate a clean .env.example.

and never imports GhostEnv internals, so it stays valid whatever
module layout Agent A's core uses.

Because Agent A writes PLAN.md + the core in parallel with this
suite, the exact subcommand names were not final when these tests
were written. Discovery is therefore help-driven and lenient:

1. CLI prefix: ``GHOSTENV_CMD`` env var, a ``ghostenv`` executable
   on PATH, or ``python -m ghostenv`` with PYTHONPATH=src (then
   repo root). Probed with ``--help``.
2. Subcommands: parsed out of ``--help`` output when possible;
   otherwise a candidate list is tried and the first shape that
   does not die with an argparse usage error wins.
   Check candidates: check / scan / doctor / audit / inspect.
   Generate candidates: example / generate / gen / export / init.
3. If no CLI is discoverable, CLI tests skip with an explicit
   reason instead of failing. Fixture tests always run.

Reference parsers in this file are TEST-side only: they extract
env names from fixture code and env files so fixture tests can
prove the fixtures themselves encode the intended differences,
independent of the product.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The unique FAKE canary value planted in canary_project/.env.
# It is not, and has never been, a real credential. Its only job
# is to be unmissable if any tool output ever prints a value.
CANARY = "CANARY_LEAK_VALUE_9f3e7d_do_not_print"
CANARY_NAME = "CANARY_API_KEY"
# Planted in a code default argument in canary_project/app.py.
# GhostEnv records has_default booleans only; this literal must
# never be copied into any output (PLAN verification bar).
CANARY_DEFAULT = "CANARY_DEFAULT_VALUE_do_not_print"
# Planted in a comment in canary_project/.env.example. Generated
# examples regenerate comments from names alone, so this must
# never survive into a generated file either.
CANARY_COMMENT = "CANARY_COMMENT_VALUE_do_not_print"
ALL_CANARIES = (CANARY, CANARY_DEFAULT, CANARY_COMMENT)

CHECK_CANDIDATES = ("check", "scan", "doctor", "audit", "inspect", "validate")
GEN_CANDIDATES = ("example", "generate", "gen", "export", "init")

# ------------------------------------------------------------------
# Reference parsers (test-side only)
# ------------------------------------------------------------------

ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_env_file(path):
    """Parse an env file, NAMES ONLY.

    Returns (names, duplicates, malformed) where names is the
    ordered list of unique variable names, duplicates the names
    seen more than once, and malformed the raw lines that are
    neither blank, comment, nor NAME=... shaped. Values are read
    only to be discarded; callers must never assert on them except
    the dedicated canary presence check.
    """
    names, seen, duplicates, malformed = [], set(), [], []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            malformed.append(raw)
            continue
        name = line.split("=", 1)[0].strip()
        if not ENV_NAME_RE.match(name):
            malformed.append(raw)
            continue
        if name in seen:
            duplicates.append(name)
        else:
            seen.add(name)
            names.append(name)
    return names, duplicates, malformed


_PY_PATTERNS = (
    re.compile(r"""os\.environ\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\]"""),
    re.compile(r"""os\.environ\.get\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""),
    re.compile(r"""os\.getenv\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""),
    re.compile(r"""(?<![\w.])getenv\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""),
    re.compile(r"""environ\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\]"""),
)
_JS_PATTERNS = (
    re.compile(r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"""process\.env\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\]"""),
)


def used_env_names(project):
    """Env names referenced by .py / .js / .ts code under project."""
    project = Path(project)
    used = set()
    for path in sorted(project.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix == ".py":
            patterns = _PY_PATTERNS
        elif path.suffix in (".js", ".ts", ".mjs"):
            patterns = _JS_PATTERNS
        else:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pat in patterns:
            used.update(pat.findall(text))
    return used


def copy_fixture(name, dest):
    """Copy a fixture project to dest/<name> and return the path."""
    src = FIXTURES / name
    dst = Path(dest) / name
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
    return dst


def tree_hashes(root):
    out = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            out[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()).hexdigest()
    return out


def collect_text(root, skip_names=frozenset({".env"})):
    """All readable text under root except the given basenames.

    Used by leak tests: everything the tool wrote or a report
    contains, minus the fixture's own original .env (the one place
    the canary is allowed to exist).
    """
    texts = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_file() and path.name not in skip_names:
            try:
                texts[path.relative_to(root).as_posix()] = path.read_text(
                    encoding="utf-8")
            except (UnicodeDecodeError, ValueError):
                continue
    return texts


# ------------------------------------------------------------------
# CLI discovery
# ------------------------------------------------------------------

_CLI_PREFIX = None
_CLI_ENV = None
_CLI_PROBED = False
_HELP_TEXT = ""


def _probe(prefix, env_extra=None):
    global _HELP_TEXT
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.run(prefix + ["--help"], capture_output=True,
                              text=True, timeout=20, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode == 0 and "ghostenv" in (proc.stdout + proc.stderr).lower():
        _HELP_TEXT = proc.stdout + proc.stderr
        return True
    return False


def cli_prefix():
    global _CLI_PREFIX, _CLI_ENV, _CLI_PROBED
    if _CLI_PROBED:
        return _CLI_PREFIX
    _CLI_PROBED = True
    env_cmd = os.environ.get("GHOSTENV_CMD")
    if env_cmd and _probe(shlex.split(env_cmd)):
        _CLI_PREFIX, _CLI_ENV = shlex.split(env_cmd), {}
        return _CLI_PREFIX
    exe = shutil.which("ghostenv")
    if exe and _probe([exe]):
        _CLI_PREFIX, _CLI_ENV = [exe], {}
        return _CLI_PREFIX
    for base in (REPO_ROOT / "src", REPO_ROOT):
        if (base / "ghostenv").is_dir() or (base / "ghostenv.py").exists():
            env = {"PYTHONPATH": str(base)}
            if _probe([sys.executable, "-m", "ghostenv"], env):
                _CLI_PREFIX = [sys.executable, "-m", "ghostenv"]
                _CLI_ENV = env
                return _CLI_PREFIX
    return None


def cli_available():
    return cli_prefix() is not None


def cli_env():
    cli_prefix()
    env = dict(os.environ)
    if _CLI_ENV:
        env.update(_CLI_ENV)
    return env


def run_cli(args, cwd=None, timeout=60):
    prefix = cli_prefix()
    assert prefix is not None, "ghostenv CLI not available"
    return subprocess.run(prefix + [str(a) for a in args],
                          capture_output=True, text=True, timeout=timeout,
                          cwd=str(cwd) if cwd else None, env=cli_env())


def help_text():
    cli_prefix()
    if _HELP_TEXT:
        return _HELP_TEXT
    try:
        proc = run_cli(["--help"])
        return proc.stdout + proc.stderr
    except AssertionError:
        return ""


def discover_subcommand(candidates):
    """First candidate named in --help, else first candidate that
    does not die with an argparse 'invalid choice' error when run
    bare (probed by the caller shapes in run_check/run_generate,
    so here help is the only source)."""
    text = help_text().lower()
    for cand in candidates:
        if re.search(rf"(?<![a-z]){re.escape(cand)}(?![a-z])", text):
            return cand
    return None


def _is_usage_error(proc):
    blob = (proc.stdout + proc.stderr).lower()
    return proc.returncode == 2 and (
        "invalid choice" in blob or "unrecognized arguments" in blob
        or "usage:" in blob)


def run_check(project, extra=()):
    """Run the check-like command against project, leniently.

    Tries the help-discovered subcommand first, then every
    candidate, then a bare ``ghostenv <project>`` shape. Returns
    the first CompletedProcess that is not a usage error, or the
    last one tried.
    """
    ordered = []
    found = discover_subcommand(CHECK_CANDIDATES)
    if found:
        ordered.append(found)
    ordered.extend(c for c in CHECK_CANDIDATES if c not in ordered)
    last = None
    for cmd in ordered:
        proc = run_cli([cmd, str(project), *extra])
        last = proc
        if not _is_usage_error(proc):
            return proc
    proc = run_cli([str(project), *extra])
    return proc if not _is_usage_error(proc) else last


def find_generated_example(project, before_hashes):
    """A new/changed example-shaped file under project, or None."""
    project = Path(project)
    after = tree_hashes(project)
    for rel, digest in sorted(after.items()):
        name = Path(rel).name.lower()
        if before_hashes.get(rel) == digest:
            continue
        if "example" in name or name in (".env.sample", ".env.template",
                                         ".env.dist"):
            return project / rel
    return None


def run_generate(project, out_path):
    """Run the generate-like command, leniently.

    Returns (proc, generated_path). generated_path is the file at
    out_path when the command honoured -o/--output, else any new
    example-shaped file the command created in the project.
    """
    project = Path(project)
    out_path = Path(out_path)
    before = tree_hashes(project)
    ordered = []
    found = discover_subcommand(GEN_CANDIDATES)
    if found:
        ordered.append(found)
    ordered.extend(c for c in GEN_CANDIDATES if c not in ordered)
    last = None
    shapes = (
        lambda c: [c, str(project), "-o", str(out_path)],
        lambda c: [c, str(project), "--output", str(out_path)],
        lambda c: [c, "-o", str(out_path), str(project)],
        lambda c: [c, str(project)],
    )
    for cmd in ordered:
        for shape in shapes:
            proc = run_cli(shape(cmd))
            last = proc
            if _is_usage_error(proc):
                continue
            if out_path.exists():
                return proc, out_path
            gen = find_generated_example(project, before)
            if gen is not None:
                return proc, gen
            # A non-usage exit with no file may still be the right
            # command printing the example to stdout; caller checks.
            if proc.returncode in (0, 1) and "env" in (
                    proc.stdout + proc.stderr).lower():
                return proc, None
    return last, (out_path if out_path.exists() else
                  find_generated_example(project, before))
