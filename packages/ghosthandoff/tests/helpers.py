"""Shared helpers for the GhostHandoff test suite.

The suite is black-box: it drives the PLAN-specified CLI

    ghosthandoff pack <project> [-o <dir>] [--since <when>] [--base <ref>]
    ghosthandoff show <pack-dir>
    ghosthandoff mcp

and never imports GhostHandoff internals, so it stays valid whatever
module layout the core build uses. CLI discovery order:

1. ``GHOSTHANDOFF_CMD`` env var (a shell-style command prefix).
2. A ``ghosthandoff`` executable on PATH (installed console script).
3. ``python -m ghosthandoff`` with ``PYTHONPATH`` set to ``src/`` and
   then to the repo root (covers a ``src/`` layout and a flat layout).

If none of those responds to ``--help``, CLI tests skip with an
explicit reason instead of failing: the fixture tests still run and
still validate the constructed git repos against git itself.

Fixture repos are real git repositories built with the git CLI in a
temp directory, so the ground truth (branch, porcelain status, stash,
log) is whatever git itself reports, never a hand-written guess.

Assumptions are recorded in REPORT_B.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_CLI_PREFIX: list[str] | None = None
_CLI_ENV: dict | None = None
_CLI_PROBED = False


# ---------------------------------------------------------------- CLI

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
    return proc.returncode == 0 and "ghosthandoff" in (
        proc.stdout + proc.stderr).lower()


def cli_prefix() -> list[str] | None:
    """Return the command prefix for the ghosthandoff CLI, or None."""
    global _CLI_PREFIX, _CLI_ENV, _CLI_PROBED
    if _CLI_PROBED:
        return _CLI_PREFIX
    _CLI_PROBED = True

    env_cmd = os.environ.get("GHOSTHANDOFF_CMD")
    if env_cmd and _probe(shlex.split(env_cmd)):
        _CLI_PREFIX = shlex.split(env_cmd)
        _CLI_ENV = {}
        return _CLI_PREFIX

    exe = shutil.which("ghosthandoff")
    if exe and _probe([exe]):
        _CLI_PREFIX = [exe]
        _CLI_ENV = {}
        return _CLI_PREFIX

    for base in (REPO_ROOT / "src", REPO_ROOT):
        if (base / "ghosthandoff").is_dir() or (base / "ghosthandoff.py").exists():
            env = {"PYTHONPATH": str(base)}
            if _probe([sys.executable, "-m", "ghosthandoff"], env):
                _CLI_PREFIX = [sys.executable, "-m", "ghosthandoff"]
                _CLI_ENV = env
                return _CLI_PREFIX
    return None


def cli_available() -> bool:
    return cli_prefix() is not None


def cli_env() -> dict:
    """Environment a CLI subprocess needs (PYTHONPATH for src runs)."""
    cli_prefix()
    env = dict(os.environ)
    if _CLI_ENV:
        env.update(_CLI_ENV)
    return env


def run_cli(args: list[str], cwd: Path | None = None,
            timeout: int = 60) -> subprocess.CompletedProcess:
    prefix = cli_prefix()
    assert prefix is not None, "ghosthandoff CLI not available"
    return subprocess.run(
        prefix + args, capture_output=True, text=True,
        timeout=timeout, cwd=str(cwd) if cwd else None, env=cli_env(),
    )


# ------------------------------------------------------- git fixtures

BRANCH = "feature/handoff-fixture"
OLD_SUBJECT = "Initial import"
SESSION_SUBJECTS = ("Add pricing module", "Wire pricing into the app entry point")
STAGED_FILE = "CHANGELOG.md"
MODIFIED_FILE = "README.md"
UNTRACKED_FILE = "scratch.py"
STASH_MESSAGE = "experiment: alternate config mode"
MARKER_FILES = {
    "pricing.py": "TODO: handle tax rounding at checkout",
    "app.py": "FIXME: retry the pricing call on failure",
    "scratch.py": "TODO: decide whether this scratch file ships",
}
# The "old" commit is dated 3 days before the fixture is built:
# outside the default 12h window, inside a --since 4d window. It is
# computed relative to build time, never a fixed calendar date: a
# hard-coded date rots as real time passes (the 2026-10-11 original
# silently aged out of the 4d window a week after it was written).
OLD_COMMIT_DATE = (datetime.now() - timedelta(days=3)).strftime(
    "%Y-%m-%dT%H:%M:%S")

GIT_ENV_EXTRA = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Fixture Dev",
    "GIT_AUTHOR_EMAIL": "fixture@example.com",
    "GIT_COMMITTER_NAME": "Fixture Dev",
    "GIT_COMMITTER_EMAIL": "fixture@example.com",
}


def git(repo: Path, *args: str, env_extra: dict | None = None,
        check: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_ENV_EXTRA)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=30, env=env,
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed in {repo}: {proc.stderr.strip()}")
    return proc


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, subject: str, when: str | None = None) -> None:
    env = None
    if when:
        env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", subject, env_extra=env)


def make_fixture_repo(dest: Path) -> Path:
    """Build the PLAN verification-bar repo at ``dest``.

    Known state when done:
    - branch ``feature/handoff-fixture``
    - 1 old commit (3 days before build time, outside the default
      12h window) and 2 recent commits (inside any sane window)
    - 1 staged modification (CHANGELOG.md)
    - 1 unstaged modification (README.md)
    - 1 untracked file (scratch.py)
    - 1 stash entry
    - 3 markers (TODO / FIXME / TODO) in pricing.py, app.py, scratch.py
    - verify-report.json + VERIFY.md recording a failing verdict
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    git(dest, "init", "-q", "-b", BRANCH)
    git(dest, "config", "commit.gpgsign", "false")

    _write(dest, "README.md",
           "# Fixture Project\n\nA small project used to test handoff packs.\n")
    _write(dest, "app.py",
           '"""Entry point for the fixture project."""\n\n\n'
           "def main():\n"
           '    print("fixture app")\n\n\n'
           'if __name__ == "__main__":\n'
           "    main()\n")
    _write(dest, "config.txt", "mode=fixture\n")
    _commit(dest, OLD_SUBJECT, when=OLD_COMMIT_DATE)

    _write(dest, "pricing.py",
           '"""Pricing helpers."""\n\n'
           "# TODO: handle tax rounding at checkout\n\n\n"
           "def total(items):\n"
           "    return sum(items)\n")
    _commit(dest, SESSION_SUBJECTS[0])

    _write(dest, "app.py",
           '"""Entry point for the fixture project."""\n\n'
           "from pricing import total\n\n"
           "# FIXME: retry the pricing call on failure\n\n\n"
           "def main():\n"
           '    print("fixture app", total([1, 2, 3]))\n\n\n'
           'if __name__ == "__main__":\n'
           "    main()\n")
    _write(dest, "CHANGELOG.md",
           "# Changelog\n\n## 0.2.0\n- Pricing wired into the entry point.\n")
    _commit(dest, SESSION_SUBJECTS[1])

    # One stash entry: change a tracked file and stash it away.
    _write(dest, "config.txt", "mode=fixture-experimental\n")
    git(dest, "stash", "push", "-q", "-m", STASH_MESSAGE)

    # One staged modification.
    with open(dest / STAGED_FILE, "a", encoding="utf-8") as fh:
        fh.write("- Pending release notes.\n")
    git(dest, "add", STAGED_FILE)

    # One unstaged modification.
    with open(dest / MODIFIED_FILE, "a", encoding="utf-8") as fh:
        fh.write("\nLocal note: not committed yet.\n")

    # One untracked file carrying the third marker.
    _write(dest, UNTRACKED_FILE,
           "# TODO: decide whether this scratch file ships\n\n"
           "SCRATCH = True\n")

    # A recorded failing verification verdict (GhostVerify-shaped).
    (dest / "verify-report.json").write_text(json.dumps({
        "tool": "ghostverify",
        "verdict": "failed",
        "exit_code": 1,
        "gaps": [{"kind": "missing-hard", "symbol": "helper",
                  "file": "pricing.py"}],
    }, indent=2), encoding="utf-8")
    _write(dest, "VERIFY.md",
           "# Verify report\n\nVerdict: failed\n"
           "One hard gap was found; see verify-report.json.\n")

    # Settle the index so later byte-compares are not fooled by a
    # stat-refresh git itself would do on first contact.
    git(dest, "status", "--porcelain")
    return dest


def make_clean_repo(dest: Path) -> Path:
    """A repo with nothing to hand off: one commit, clean tree, no
    markers, no reports, no stash, nothing unpushed anywhere."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    git(dest, "init", "-q", "-b", "main")
    git(dest, "config", "commit.gpgsign", "false")
    _write(dest, "clean.py",
           '"""A finished module."""\n\n\n'
           "def done():\n"
           "    return True\n")
    _write(dest, "README.md", "# Clean Project\n\nAll finished here.\n")
    _commit(dest, "Initial import")
    git(dest, "status", "--porcelain")
    return dest


def make_plain_folder(dest: Path) -> Path:
    """Not a git repo at all: one file with one marker."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    _write(dest, "notes.txt",
           "Plain folder notes.\nTODO: water the plants on Friday.\n")
    _write(dest, "data.txt", "1,2,3\n")
    return dest


# --------------------------------------------------------- inspection

def tree_hashes(root: Path) -> dict[str, str]:
    """sha256 per file under root, .git included, for read-only proof."""
    out = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            out[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()).hexdigest()
    return out


def porcelain(repo: Path) -> str:
    env = dict(os.environ)
    env.update(GIT_ENV_EXTRA)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    proc = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True, text=True, timeout=30, env=env)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def head_short(repo: Path) -> str:
    return git(repo, "rev-parse", "--short", "HEAD").stdout.strip()


def count_markers(root: Path) -> list[tuple[str, int, str]]:
    """Independent marker scan: (relpath, lineno, line) for lines
    containing TODO / FIXME / XXX / HACK outside .git."""
    found = []
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(m in line for m in ("TODO", "FIXME", "XXX", "HACK")):
                found.append((path.relative_to(root).as_posix(), lineno, line))
    return found


# ------------------------------------------------- handoff.json diggers
# The plan fixes the facts a pack must carry, not every key name, so
# these diggers are deliberately lenient about key naming while strict
# about the values they find.

def all_strings(obj) -> list[str]:
    out = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for value in obj.values():
            out.extend(all_strings(value))
    elif isinstance(obj, list):
        for value in obj:
            out.extend(all_strings(value))
    return out


def values_for_key(obj, *needles: str) -> list:
    """Every value whose dict key contains one of ``needles``."""
    out = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if any(n in str(key).lower() for n in needles):
                out.append(value)
            out.extend(values_for_key(value, *needles))
    elif isinstance(obj, list):
        for value in obj:
            out.extend(values_for_key(value, *needles))
    return out


def entry_name(entry) -> str | None:
    """Normalise a list entry (string, or dict with a path-ish key)."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        for key in ("path", "file", "name", "relpath", "relative_path"):
            value = entry.get(key)
            if isinstance(value, str):
                return value
    return None


def names_in(values: list) -> set[str]:
    names = set()
    for value in values:
        if isinstance(value, list):
            for entry in value:
                name = entry_name(entry)
                if name:
                    names.add(name)
        elif isinstance(value, str):
            names.add(value)
    return names


def find_pack(outdir: Path) -> tuple[Path | None, Path | None]:
    """Locate (HANDOFF.md, handoff.json) written by a pack run."""
    md = Path(outdir) / "HANDOFF.md"
    js = Path(outdir) / "handoff.json"
    return (md if md.exists() else None, js if js.exists() else None)


def load_pack_json(outdir: Path) -> dict:
    _, js = find_pack(outdir)
    assert js is not None, f"no handoff.json in {outdir}"
    return json.loads(js.read_text(encoding="utf-8"))


def pack_text(outdir: Path) -> str:
    md, _ = find_pack(outdir)
    assert md is not None, f"no HANDOFF.md in {outdir}"
    return md.read_text(encoding="utf-8")
