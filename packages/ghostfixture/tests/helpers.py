"""Shared helpers for the GhostFixture test suite.

The suite is black-box: it drives the CLI contract from
PLAN.md (MVP v0.1)

    ghostfixture build <project> <bundle> -o <out-dir>
                     [--task "..."] [--max-bytes N]
                     [--include-flagged]
    ghostfixture check <fixture-dir>

and never imports GhostFixture internals, so it stays valid
whatever module layout the core build uses. Only the command
prefix is discovered (see below); the verb and flags are the
plan's, confirmed against the landed core's cli.py.

CLI discovery order:

1. ``GHOSTFIXTURE_CMD`` env var (a shell-style command prefix).
2. A ``ghostfixture`` executable on PATH (installed console script).
3. ``python -m ghostfixture`` with ``PYTHONPATH`` set to ``src/``
   and then to the repo root (covers a ``src/`` layout and a flat
   layout).

If none of those responds to ``--help``, CLI tests skip with an
explicit reason instead of failing: the fixture tests still run
and still validate the fixture projects and the bundle builder
against the GhostSlice bundle format GhostFixture consumes.

The bundles used here are built by :func:`build_bundle`, which
writes a GhostSlice-shaped bundle directory (manifest.json with
per-file sha256 + token totals, PROMPT.md with ``# File:``
headers, and ``files/`` copies) from a fixture project. Building
them at test time keeps the manifest's ``root`` and hashes honest
for whatever temp directory the project was copied into.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPRO_PROJECT = FIXTURES / "repro_project"
BIG_PROJECT = FIXTURES / "big_project"

# The planted canary: a FAKE, test-only literal in a Stripe
# live-key shape, planted in repro_project/app/secrets_store.py.
# It is not, and has never been, a real credential. Tests scan
# every byte GhostFixture writes for this exact string.
CANARY = "sk_live_FIXTURECANARY7d3f9a2b51"
SECRET_FILE = "app/secrets_store.py"

# Files the repro bundle references, (path, mode) pairs.
REPRO_BUNDLE_FILES = [
    ("app/main.py", "full"),
    ("app/config.py", "full"),
    ("app/secrets_store.py", "full"),
]
BIG_BUNDLE_FILES = [
    ("pkg/__init__.py", "full"),
    ("pkg/alpha.py", "full"),
    ("pkg/beta.py", "full"),
    ("pkg/gamma.py", "full"),
    ("pkg/delta.py", "full"),
]

# ---------------------------------------------------------------- CLI probe

_CLI_PREFIX: list[str] | None = None
_CLI_ENV: dict | None = None
_CLI_PROBED = False


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
    return proc.returncode == 0 and "ghostfixture" in (
        proc.stdout + proc.stderr).lower()


def cli_prefix() -> list[str] | None:
    """Return the command prefix for the ghostfixture CLI, or None."""
    global _CLI_PREFIX, _CLI_ENV, _CLI_PROBED
    if _CLI_PROBED:
        return _CLI_PREFIX
    _CLI_PROBED = True

    env_cmd = os.environ.get("GHOSTFIXTURE_CMD")
    if env_cmd and _probe(shlex.split(env_cmd)):
        _CLI_PREFIX = shlex.split(env_cmd)
        _CLI_ENV = {}
        return _CLI_PREFIX

    exe = shutil.which("ghostfixture")
    if exe and _probe([exe]):
        _CLI_PREFIX = [exe]
        _CLI_ENV = {}
        return _CLI_PREFIX

    for base in (REPO_ROOT / "src", REPO_ROOT):
        env = {"PYTHONPATH": str(base)}
        if _probe([sys.executable, "-m", "ghostfixture"], env):
            _CLI_PREFIX = [sys.executable, "-m", "ghostfixture"]
            _CLI_ENV = env
            return _CLI_PREFIX
    return None


def cli_available() -> bool:
    return cli_prefix() is not None


def cli_env() -> dict:
    """Environment for spawning the CLI directly (MCP test)."""
    env = dict(os.environ)
    if _CLI_ENV:
        env.update(_CLI_ENV)
    return env


def run_cli(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    prefix = cli_prefix()
    assert prefix is not None, "CLI not discoverable"
    env = dict(os.environ)
    if _CLI_ENV:
        env.update(_CLI_ENV)
    return subprocess.run(
        prefix + args, capture_output=True, text=True,
        timeout=timeout, env=env,
    )


# ------------------------------------------------------- build invocation

def build_fixture(project, bundle, out, cap=None, extra=(), timeout=60):
    """Run ``ghostfixture build`` per the PLAN.md contract.

    Argument order is the plan's: project first, then bundle.
    ``extra`` carries additional flags verbatim (for example
    ``--include-flagged``). Returns the CompletedProcess.
    """
    args = ["build", str(project), str(bundle), "-o", str(out)]
    if cap is not None:
        args += ["--max-bytes", str(cap)]
    args += list(extra)
    return run_cli(args, timeout=timeout)


def check_fixture(fixture_dir, timeout=60):
    """Run ``ghostfixture check <fixture-dir>``."""
    return run_cli(["check", str(fixture_dir)], timeout=timeout)


def fixture_manifest(out) -> dict:
    """Load the fixture-manifest.json the build wrote into ``out``."""
    path = Path(out) / "fixture-manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------ bundle kit

def _language(path: str) -> str:
    return {".py": "python", ".md": "markdown", ".txt": "text"}.get(
        Path(path).suffix, "text")


def _est_tokens(text: str) -> int:
    # Fixture-side estimate only; internal consistency is what the
    # fixture tests check, not parity with Slice's estimator.
    return max(1, (len(text) + 3) // 4)


def build_bundle(project: Path, out: Path,
                 entries: list[tuple[str, str]]) -> Path:
    """Write a GhostSlice-shaped bundle of ``project`` into ``out``.

    ``entries`` are (relative path, mode) pairs. Writes files/
    copies, a manifest.json whose sha256 and totals match the
    copies, and a PROMPT.md with standard ``# File:`` headers.
    Returns the bundle directory.
    """
    project = Path(project)
    out = Path(out)
    files_dir = out / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    manifest_files = []
    prompt_parts = []
    total_original = 0
    total_sliced = 0
    for rel, mode in entries:
        src = project / rel
        text = src.read_text(encoding="utf-8")
        dest = files_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        tokens = _est_tokens(text)
        total_original += tokens
        total_sliced += tokens
        manifest_files.append({
            "path": rel,
            "mode": mode,
            "language": _language(rel),
            "package": None,
            "original_tokens": tokens,
            "sliced_tokens": tokens,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        })
        prompt_parts.append(f"# File: {rel} (mode: {mode})\n{text}")
    manifest = {
        "tool": "ghostslice",
        "version": "1.0.6",
        "generated_at": "2026-10-14T00:00:00+00:00",
        "root": str(project),
        "token_method": "fixture estimate (chars/4), test bundle only",
        "files": manifest_files,
        "total_original_tokens": total_original,
        "total_sliced_tokens": total_sliced,
        "total_saved_tokens": 0,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out / "PROMPT.md").write_text(
        "\n".join(prompt_parts), encoding="utf-8")
    return out


# ------------------------------------------------------------- tree utils

def tree_hashes(root: Path) -> dict[str, str]:
    """Map every file under ``root`` to its sha256, keyed by relpath."""
    root = Path(root)
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def output_files(root: Path) -> list[Path]:
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file())


def output_json_docs(root: Path) -> list[tuple[Path, object]]:
    """Parse every .json file under the output dir; skip unparseable."""
    docs = []
    for path in output_files(root):
        if path.suffix == ".json":
            try:
                docs.append((path, json.loads(
                    path.read_text(encoding="utf-8"))))
            except (ValueError, UnicodeDecodeError):
                continue
    return docs


def all_output_bytes(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in output_files(root))


def combined(proc) -> str:
    return (proc.stdout or "") + (proc.stderr or "")
