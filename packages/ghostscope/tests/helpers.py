"""Shared helpers for GhostScope tests.

Contract assumed from PLAN.md (Agent B assumptions, see REPORT_B.md):
  CLI:  ghostscope pack <project> --base <ref> --head <ref> -o <outdir>
        (module form: python -m ghostscope pack ...)
  Pack: a normal GhostSlice-style bundle (manifest.json) plus scope.json
        sidecar (base, head, per-file graph distance, risk reasons) and
        REVIEW.md (riskiest-first reading order, risk reasons in words).

If the core (Agent A) is not present, core_runner() returns None and the
integration tests fail with a clear message rather than skipping silently:
the parent verifies the combined tree, so a missing core must be visible.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def core_runner():
    """Return a command prefix list for the GhostScope CLI, or None."""
    src = ROOT / "src"
    env_path = str(src) if src.exists() else None
    # Module form
    probe_env = dict(os.environ)
    if env_path:
        probe_env["PYTHONPATH"] = env_path + os.pathsep + probe_env.get("PYTHONPATH", "")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "ghostscope", "--help"],
            capture_output=True, text=True, timeout=15, env=probe_env,
        )
        if r.returncode == 0:
            return [sys.executable, "-m", "ghostscope"]
    except Exception:
        pass
    exe = shutil.which("ghostscope")
    if exe:
        return [exe]
    return None


def run(cmd, cwd=None, env_extra=None):
    env = dict(os.environ)
    src = ROOT / "src"
    if src.exists():
        env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=120, env=env)


def git(repo: Path, *args):
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
    return r.stdout.strip()


def build_git_project(base_dir: Path, tmp: Path) -> Path:
    """Copy a fixture base/ tree into tmp/proj and commit it."""
    proj = tmp / "proj"
    shutil.copytree(base_dir, proj)
    git(proj.parent, "init", "-q", proj.name) if False else None
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    git(proj, "config", "user.email", "test@example.com")
    git(proj, "config", "user.name", "GhostScope Tests")
    git(proj, "add", "-A")
    git(proj, "commit", "-qm", "base")
    return proj


def apply_change(proj: Path, change_dir: Path, deletions_file: Path = None):
    if change_dir.exists():
        for src in change_dir.rglob("*"):
            if src.is_file():
                dst = proj / src.relative_to(change_dir)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    if deletions_file and deletions_file.exists():
        for line in deletions_file.read_text().splitlines():
            line = line.strip()
            if line:
                (proj / line).unlink(missing_ok=True)
    git(proj, "add", "-A")
    git(proj, "commit", "-qm", "change")


def run_pack(proj: Path, out: Path):
    """Run ghostscope pack base..head. Tries -o, then --output, then bare."""
    runner = core_runner()
    assert runner is not None, (
        "GhostScope core not found (no importable ghostscope module and no "
        "ghostscope executable). Integration test cannot pass until Agent A's "
        "src/** lands. See REPORT_B.md assumptions."
    )
    attempts = [
        runner + ["pack", str(proj), "--base", "HEAD~1", "--head", "HEAD", "-o", str(out)],
        runner + ["pack", str(proj), "--base", "HEAD~1", "--head", "HEAD", "--output", str(out)],
        runner + ["pack", str(proj), "--base", "HEAD~1", "--head", "HEAD"],
    ]
    last = None
    for cmd in attempts:
        last = run(cmd, cwd=proj)
        if last.returncode == 0:
            return last
    raise AssertionError(
        f"ghostscope pack failed on all invocation forms.\n"
        f"stdout: {last.stdout}\nstderr: {last.stderr}"
    )


def find_pack_file(out: Path, proj: Path, name: str):
    """Locate a pack artifact under the output dir or the project dir."""
    for base in (out, proj):
        if base.exists():
            hits = sorted(base.rglob(name))
            if hits:
                return hits[0]
    return None


def load_json_recursive(path: Path):
    return json.loads(path.read_text())


def flatten_text(obj) -> str:
    """All keys+values of a JSON structure as searchable text."""
    if isinstance(obj, dict):
        return " ".join(f"{k} {flatten_text(v)}" for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return " ".join(flatten_text(v) for v in obj)
    return str(obj)
