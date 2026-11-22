"""Shared helpers for the GhostWorktree test suite (Agent B).

The suite is black-box: it drives the CLI described in the build scope

    GhostWorktree = isolated git worktree + port + env-copy manager
    per agent task: create / list / status / cleanup, with dirty
    cleanup refused by default.

ASSUMED CORE INTERFACE (recorded in REPORT_B.md; if Agent A's core
differs in spelling, only this file should need changing):

  Layout:    src/ghostworktree/ package, run as
             ``python -m ghostworktree`` with PYTHONPATH=<repo>/src
             (GhostSlice house layout), or a ``ghostworktree``
             executable on PATH.
  Commands:  (positional, exactly as Agent A's PLAN.md / cli.py ship)
             ghostworktree create <repo> <name> [--branch B] [--base HEAD]
                           [--port <n>] [--port-range S-E] [--path DIR]
                           [--no-env] [--root DIR] [--json]
             ghostworktree list   <repo> [--json]
             ghostworktree status <repo> [<name>] [--json]
             ghostworktree cleanup <repo> <name> [--force]
                           [--delete-branch] [--json]
  Registry:  <repo-parent>/<repo-name>-worktrees/registry.json with
             records {name, repo, path, branch, base, port,
             env_source, created_at}.
  Env rule:  the real .env is NEVER read or copied. Only
             .env.example (fallback .env.sample / .env.template) is
             copied in, and the worktree .env is seeded from that
             example only. A planted marker value in the real .env
             must appear in no created file, registry, or output.

The create / cleanup helpers try several plausible argument orders
and spellings (cleanup vs remove, --force vs --yes) before giving up,
so minor CLI spelling differences do not fail the whole suite. The
created worktree is located authoritatively via
``git -C <repo> worktree list --porcelain``, never by guessing a
directory layout.

If no CLI responds to ``--help``, integration tests skip with an
explicit reason instead of failing: the fixture / documentation tests
still run. That state is also recorded in REPORT_B.md.

Tests are stdlib + pytest only, use git only on throwaway repos under
pytest tmp dirs, make no network calls, and never touch a real repo.
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

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

_CLI_PREFIX: list[str] | None = None
_CLI_ENV: dict | None = None
_CLI_PROBED = False


# ---------------------------------------------------------------- CLI

def _probe(prefix: list[str], env_extra: dict | None = None) -> bool:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.run(prefix + ["--help"], capture_output=True,
                              text=True, timeout=20, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and "ghostworktree" in (
        proc.stdout + proc.stderr).lower() or (
            proc.returncode == 0 and "worktree" in (proc.stdout + proc.stderr).lower())


def cli_prefix() -> list[str] | None:
    global _CLI_PREFIX, _CLI_ENV, _CLI_PROBED
    if _CLI_PROBED:
        return _CLI_PREFIX
    _CLI_PROBED = True

    env_cmd = os.environ.get("GHOSTWORKTREE_CMD")
    if env_cmd and _probe(shlex.split(env_cmd)):
        _CLI_PREFIX, _CLI_ENV = shlex.split(env_cmd), {}
        return _CLI_PREFIX

    exe = shutil.which("ghostworktree")
    if exe and _probe([exe]):
        _CLI_PREFIX, _CLI_ENV = [exe], {}
        return _CLI_PREFIX

    for base in (SRC, ROOT):
        if (base / "ghostworktree").is_dir() or (base / "ghostworktree.py").exists():
            env = {"PYTHONPATH": str(base)}
            if _probe([sys.executable, "-m", "ghostworktree"], env):
                _CLI_PREFIX = [sys.executable, "-m", "ghostworktree"]
                _CLI_ENV = env
                return _CLI_PREFIX
    return None


def cli_available() -> bool:
    return cli_prefix() is not None


def run_cli(args: list[str], cwd: Path | None = None,
            timeout: int = 60) -> subprocess.CompletedProcess:
    prefix = cli_prefix()
    assert prefix is not None, "ghostworktree CLI not available"
    env = dict(os.environ)
    if _CLI_ENV:
        env.update(_CLI_ENV)
    return subprocess.run(prefix + [str(a) for a in args],
                          capture_output=True, text=True, timeout=timeout,
                          cwd=str(cwd) if cwd else None, env=env)


def combined(proc: subprocess.CompletedProcess) -> str:
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


# ---------------------------------------------------------------- git

def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=30)


def git_ok(repo: Path, *args: str) -> str:
    proc = git(repo, *args)
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


SECRET_MARKER = "planted-marker-not-a-real-secret"
FAKE_ENV = f"APP_NAME=ghostworktree-demo\nFAKE_TOKEN={SECRET_MARKER}\nPORT=0\n"


def make_repo(base: Path, name: str = "repo") -> Path:
    """Create a committed throwaway git repo with an .env and code."""
    repo = base / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True, timeout=30)
    git_ok(repo, "config", "user.email", "test@example.com")
    git_ok(repo, "config", "user.name", "GhostWorktree Tests")
    (repo / "app.py").write_text(
        '"""Demo app."""\n\n\ndef main():\n    return "ok"\n', encoding="utf-8")
    (repo / "README.md").write_text("# demo repo\n", encoding="utf-8")
    (repo / ".env").write_text(FAKE_ENV, encoding="utf-8")
    (repo / ".env.example").write_text(
        "APP_NAME=\nFAKE_TOKEN=\nPORT=\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".env\n__pycache__/\n", encoding="utf-8")
    git_ok(repo, "add", "app.py", "README.md", ".env.example", ".gitignore")
    git_ok(repo, "commit", "-qm", "base")
    return repo


def make_plain_dir(base: Path, name: str = "not-a-repo") -> Path:
    plain = base / name
    plain.mkdir(parents=True)
    (plain / "file.txt").write_text("not a git repo\n", encoding="utf-8")
    return plain


def worktree_paths(repo: Path) -> list[Path]:
    """All worktree paths registered for repo, main worktree first."""
    out = git_ok(repo, "worktree", "list", "--porcelain")
    paths = []
    for line in out.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line[len("worktree "):].strip()))
    return paths


def extra_worktrees(repo: Path) -> list[Path]:
    main = Path(git_ok(repo, "rev-parse", "--show-toplevel")).resolve()
    return [p for p in worktree_paths(repo) if p.resolve() != main]


# ---------------------------------------------------------------- create

def _create_forms(repo: Path, name: str, port: int | None) -> list[list[str]]:
    port_args: list[str] = ["--port", str(port)] if port else []
    return [
        ["create", str(repo), name, *port_args],
        ["create", str(repo), "--name", name, *port_args],
    ]


def create_worktree(repo: Path, name: str, port: int | None = None):
    """Try the plausible create forms.

    Returns (proc, worktree_path_or_None). A form counts as success
    only when it exits 0 AND git reports a new worktree afterwards
    (or the path it prints exists and is a registered worktree).
    """
    before = {str(p) for p in worktree_paths(repo)} if (repo / ".git").exists() else set()
    last = None
    first = None
    for form in _create_forms(repo, name, port):
        proc = run_cli(form, cwd=repo.parent)
        if first is None:
            first = proc
        last = proc
        if proc.returncode != 0:
            continue
        now = worktree_paths(repo)
        new = [p for p in now if str(p) not in before]
        if new:
            # Prefer a path whose name mentions the task name.
            for p in new:
                if name in p.name:
                    return proc, p
            return proc, new[0]
        # Exit 0 but git sees no new worktree: maybe the tool printed
        # a path not yet registered (should not happen) - accept an
        # existing directory printed on stdout that mentions the name.
        for token in re.findall(r"[\w./\-]+", combined(proc)):
            p = Path(token)
            if name in token and p.is_dir():
                return proc, p
    # On total failure, report the shipped (positional) form's result:
    # fallback spellings fail in argparse and would mask the real error
    # (for example "not a git working tree", exit 2).
    return first if first is not None else last, None


def parse_port(text: str) -> int | None:
    m = re.search(r"\bport\b\s*[:=]?\s*(\d{2,5})", text, re.IGNORECASE)
    if m:
        value = int(m.group(1))
        if 0 < value < 65536:
            return value
    return None


def find_state_files(repo: Path, wt: Path | None) -> list[Path]:
    """JSON state/registry files a core might keep, searched leniently."""
    hits: list[Path] = []
    bases = [repo, wt] if wt else [repo]
    for base in bases:
        if not base or not base.exists():
            continue
        for path in base.rglob("*.json"):
            if ".git" in path.parts:
                continue
            if any(k in path.name.lower() for k in
                   ("ghostworktree", "worktree", "registry", "state", "manifest")):
                hits.append(path)
    return hits


def state_text(repo: Path, wt: Path | None) -> str:
    out = []
    for path in find_state_files(repo, wt):
        try:
            out.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return "\n".join(out)


def worktree_port(repo: Path, wt: Path | None, proc=None) -> int | None:
    """Port for a worktree, from CLI output, state files, or its .env."""
    texts = []
    if proc is not None:
        texts.append(combined(proc))
    texts.append(state_text(repo, wt))
    if wt:
        for env_name in (".env", ".env.example"):
            env_file = wt / env_name
            if env_file.exists():
                for line in env_file.read_text(
                        encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("PORT="):
                        value = line.split("=", 1)[1].strip()
                        if value.isdigit() and int(value) > 0:
                            return int(value)
    for text in texts:
        port = parse_port(text)
        if port:
            return port
    return None


# ---------------------------------------------------------------- list/status

def list_worktrees(repo: Path):
    """Return the first list-form invocation that exits 0, else last."""
    last = None
    for form in (["list", str(repo)], ["list", "--repo", str(repo)],
                 ["list"], ["ls", str(repo)]):
        proc = run_cli(form, cwd=repo)
        last = proc
        if proc.returncode == 0:
            return proc
    return last


def status_worktree(repo: Path, name: str | None = None):
    forms = []
    if name:
        # Named forms only: falling back to an unnamed status would
        # mask the unknown-name error with a successful full listing.
        forms += [["status", str(repo), name],
                  ["status", str(repo), "--name", name]]
    else:
        forms += [["status", str(repo)], ["status"]]
    last = None
    for form in forms:
        proc = run_cli(form, cwd=repo)
        last = proc
        if proc.returncode == 0:
            return proc
    return last


# ---------------------------------------------------------------- cleanup

def _cleanup_forms(repo: Path, name: str, wt: Path | None,
                   force: bool) -> list[list[str]]:
    flags: list[str] = []
    if force:
        flags = ["--force"]
    forms = [
        ["cleanup", str(repo), name, *flags],
        ["cleanup", str(repo), "--name", name, *flags],
        ["remove", str(repo), name, *flags],
    ]
    if wt:
        forms += [["cleanup", str(wt), *flags]]
    if force:
        # Some CLIs spell the override --yes instead of --force.
        yes_forms = [[a if a != "--force" else "--yes" for a in f] for f in forms]
        forms += yes_forms
    return forms


def cleanup_worktree(repo: Path, name: str, wt: Path | None,
                     force: bool = False):
    """Try cleanup forms. Returns the first proc that exits 0, else last.

    Callers verify the effect with git (extra_worktrees), not just
    the exit code.
    """
    last = None
    for form in _cleanup_forms(repo, name, wt, force):
        try:
            proc = run_cli(form, cwd=repo)
        except Exception as exc:  # a hanging/broken form must not stall the suite
            last = exc  # type: ignore[assignment]
            continue
        last = proc
        if proc.returncode == 0:
            return proc
    return last


def registry_path(repo: Path) -> Path:
    """The registry location from PLAN.md / registry.py."""
    repo = Path(repo).resolve()
    return repo.parent / f"{repo.name}-worktrees" / "registry.json"


def flatten(obj) -> str:
    if isinstance(obj, dict):
        return " ".join(f"{k} {flatten(v)}" for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return " ".join(flatten(v) for v in obj)
    return str(obj)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
