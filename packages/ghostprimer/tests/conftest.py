"""Shared helpers for GhostPrimer tests.

Tests target the PUBLIC CLI and bundle formats described in PLAN.md.
They do not import ghostprimer internals: if the CLI contract changes,
these tests are supposed to fail loudly.

Assumed CLI (PLAN.md MVP, see REPORT_B.md assumptions):
  ghostprimer build  <project> -o <bundle> [--budget N]
                     [--recall-bundle <dir>] [--task "..."]
  ghostprimer check  <bundle>          exit 0 pass / 1 fail / 2 cannot check
  ghostprimer doctor <project>
  ghostprimer mcp                       stdio JSON-RPC, primer_build/primer_check

Assumed bundle layout:
  <bundle>/PRIMER.md        the pack itself
  <bundle>/manifest.json    Slice-schema files + memory items + totals
  <bundle>/files/...        sliced code, at the recorded relative paths

CLI discovery order: $GHOSTPRIMER_CMD, `ghostprimer` on PATH, then
`python -m ghostprimer` with PYTHONPATH=<repo>/src.
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

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
GHOSTSLICE_SRC = Path.home() / "workspace" / "ghostslice" / "src"
GHOSTRECALL_SRC = Path.home() / "workspace" / "ghostrecall" / "src"

# Synthetic planted secret. Deliberately contains none of the placeholder
# words secret scanners exempt (fake / example / dummy / test-key ...),
# otherwise the guard would wave it through as a labelled placeholder.
# It is not a real credential.
PLANTED_SECRET = "<redacted_api_token_1>"

ENTRY_REL = "src/widgetforge/main.py"
FANIN_REL = "src/widgetforge/core.py"
ORPHAN_REL = "src/widgetforge/orphan.py"


def cli_base():
    override = os.environ.get("GHOSTPRIMER_CMD")
    if override:
        return shlex.split(override)
    exe = shutil.which("ghostprimer")
    if exe:
        return [exe]
    return [sys.executable, "-m", "ghostprimer"]


def cli_env(extra=None):
    env = dict(os.environ)
    parts = [str(REPO_ROOT / "src"), str(REPO_ROOT)]
    if env.get("PYTHONPATH"):
        parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    if extra:
        env.update(extra)
    return env


def run_cli(*args, cwd=None, timeout=120, env_extra=None):
    return subprocess.run(
        cli_base() + [str(a) for a in args],
        capture_output=True, text=True, cwd=cwd, env=cli_env(env_extra),
        timeout=timeout,
    )


def combined(proc):
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


def core_available():
    try:
        r = run_cli("--help", timeout=30)
    except Exception:
        return False
    return r.returncode == 0


@pytest.fixture(scope="session", autouse=True)
def require_core():
    if not core_available():
        pytest.skip("ghostprimer CLI not discoverable "
                    "(GHOSTPRIMER_CMD / PATH / python -m ghostprimer)")


# ---------------------------------------------------------------- projects

def copy_fixture(name, dest):
    src = FIXTURES / name
    shutil.copytree(src, dest)
    return dest


@pytest.fixture()
def starter_project(tmp_path):
    return copy_fixture("starter_project", tmp_path / "starter_project")


@pytest.fixture()
def recall_project(tmp_path):
    return copy_fixture("recallproj", tmp_path / "recallproj")


@pytest.fixture()
def secret_project(tmp_path):
    return copy_fixture("secretmem_project", tmp_path / "secretmem_project")


def build(project, out, *extra, timeout=120, env_extra=None):
    return run_cli("build", project, "-o", out, *extra,
                   timeout=timeout, env_extra=env_extra)


@pytest.fixture()
def built_bundle(starter_project, tmp_path):
    out = tmp_path / "bundle"
    proc = build(starter_project, out)
    assert proc.returncode == 0, combined(proc)
    return out


# ---------------------------------------------------------------- manifest

def load_manifest(bundle):
    return json.loads((Path(bundle) / "manifest.json").read_text())


def manifest_files(manifest):
    files = manifest.get("files")
    return files if isinstance(files, list) else []


def file_entry(manifest, rel):
    for entry in manifest_files(manifest):
        path = entry.get("path") or entry.get("rel") or entry.get("name")
        if path and Path(path).as_posix().endswith(rel):
            return entry
    return None


def memory_items(manifest):
    """All memory-ish records anywhere in the manifest, tolerantly."""
    found = []

    def walk(node, key_hint=""):
        if isinstance(node, dict):
            blob = json.dumps(node).lower()
            if any(k in node for k in ("provenance", "source")) and (
                    "memory" in blob or "decision" in blob
                    or "agents.md" in blob or "changelog" in blob):
                found.append(node)
            for key, value in node.items():
                walk(value, key)
        elif isinstance(node, list):
            for value in node:
                walk(value, key_hint)

    for key in ("memory", "memory_items", "primer_memory", "items"):
        if key in manifest:
            walk(manifest[key], key)
    return found


def bundle_texts(bundle):
    """(relpath, text) for every readable file in the bundle."""
    out = []
    for path in sorted(Path(bundle).rglob("*")):
        if path.is_file():
            try:
                out.append((str(path.relative_to(bundle)),
                            path.read_text(errors="strict")))
            except (UnicodeDecodeError, ValueError):
                continue
    return out


def bundle_blob(bundle):
    return "\n".join(text for _, text in bundle_texts(bundle))


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest_primer_sha(manifest):
    """Find a recorded sha256 of PRIMER.md anywhere plausible."""
    candidates = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if "sha256" in key and isinstance(value, str):
                    candidates.append((key, value))
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(manifest.get("primer", {}))
    for key, value in manifest.items():
        if "primer" in key and "sha" in key and isinstance(value, str):
            candidates.append((key, value))
    walk({k: v for k, v in manifest.items()
          if k not in ("files", "memory", "memory_items", "items")})
    return [value for _, value in candidates]


# ------------------------------------------------------- sibling CLIs

def ghostslice_available():
    return (GHOSTSLICE_SRC / "ghostslice").is_dir()


def run_ghostslice_check(bundle):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(GHOSTSLICE_SRC)
    return subprocess.run(
        [sys.executable, "-m", "ghostslice", "check", str(bundle)],
        capture_output=True, text=True, env=env, timeout=120)


def ghostrecall_available():
    return (GHOSTRECALL_SRC / "ghostrecall").is_dir()


def run_ghostrecall_bundle(project, task, out, fit=4000):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(GHOSTRECALL_SRC)
    return subprocess.run(
        [sys.executable, "-m", "ghostrecall", "bundle", str(project),
         "--task", task, "--fit", str(fit), "-o", str(out)],
        capture_output=True, text=True, env=env, timeout=120)
