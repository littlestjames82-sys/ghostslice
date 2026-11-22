"""Shared helpers for the GhostWatch test suite (Agent B).

INTERFACE (verified against Agent A's core as shipped in
src/ghostwatch/cli.py + core.py on Oct 14, 2026; this file is the
single place to change if it moves):

  Layout:    src/ghostwatch/ package, run as `python -m ghostwatch`
             with PYTHONPATH=<repo>/src, or a `ghostwatch` executable.
  Commands:  ghostwatch snapshot <project> [--bundle <path>] [-o <out>]
             ghostwatch check <project> [--bundle <path>]
                                  [--snapshot <path>] [--strict-added]
                                  [--reexport] [--json]
                                  [--json-out <f>] [--md-out <f>]
             ghostwatch watch <project> [--bundle <path>]
                                  [--interval S] [--max-polls N]
                                  [--strict-added] [--reexport]
                                  [--write-report] [--json-out] [--md-out]
  Exit codes: 0 = fresh, 1 = stale, 2 = unknown / could not determine.
  Snapshot:  <project>/.ghostwatch/snapshot.json by default. JSON
             object: tool, version, snapshot_version, created_at, root,
             ignore, files_hashed, bundle (null or {path,
             manifest_sha256, generated_at, tool, version, files}),
             files = OBJECT keyed by relative path, each value
             {sha256, size, mtime_ns, symbols, symbol_method}.
             A bundle manifest's per-file sha256 is the hash of the
             SLICED text; the snapshot's sha256 is the SOURCE bytes.
  Report:    check --json prints / the report dict carries verdict
             (fresh|stale|unknown), baseline (snapshot|
             manifest_heuristic), bundle_manifest_sha256,
             pack_stale (mirrors stale), findings object with classes
             changed_in_bundle, changed_not_in_bundle,
             added_not_in_bundle, removed_from_project,
             missing_bundle_file, stale_symbols, touched_only,
             and reexport (null or {status: ok|failed|unavailable}).

Tests are stdlib + pytest only, make no network calls, and write only
under pytest tmp dirs. GhostSlice is deliberately NOT importable in
the test environment (PYTHONPATH carries only GhostWatch's src and
PATH is inherited without any ghostslice shim) except in the tests
that install a fake `ghostslice` executable on purpose.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WATCH_SRC = REPO_ROOT / "src"

APP_PY = '''"""Demo application module."""


def compute_total(items):
    """Sum the priced items."""
    total = 0
    for item in items:
        total += item_price(item) * item_count(item)
    return total


def item_price(item):
    """Return the price field of one item."""
    return item["price"]


def item_count(item):
    """Return the count field of one item."""
    return item.get("count", 1)


def render_total(total):
    """Format a total for display."""
    return "Total: %.2f" % total
'''

UTIL_PY = '''"""Demo utility module."""


def slugify(text):
    """Turn display text into a slug."""
    return "-".join(text.lower().split())


def clamp(value, low, high):
    """Clamp a value into a range."""
    return max(low, min(high, value))
'''

NOTES_TXT = "Release notes live here.\nSecond line.\n"


# ---------------------------------------------------------------- CLI

def core_available() -> bool:
    return (WATCH_SRC / "ghostwatch" / "__main__.py").exists() or (
        shutil.which("ghostwatch") is not None
    )


def base_env(extra: dict | None = None) -> dict:
    env = dict(os.environ)
    # Only GhostWatch's src: ghostslice must stay unimportable unless a
    # test installs a fake executable on purpose.
    env["PYTHONPATH"] = str(WATCH_SRC)
    if extra:
        env.update(extra)
    return env


def run_ghostwatch(*args: str, env_extra: dict | None = None,
                   timeout: int = 60) -> subprocess.CompletedProcess:
    """Run the GhostWatch CLI. Returns a CompletedProcess even when the
    core is missing (returncode 127, explanatory stderr)."""
    if (WATCH_SRC / "ghostwatch" / "__main__.py").exists():
        cmd = [sys.executable, "-m", "ghostwatch", *args]
    elif shutil.which("ghostwatch"):
        cmd = ["ghostwatch", *args]
    else:
        return subprocess.CompletedProcess(
            args=list(args), returncode=127, stdout="",
            stderr="ghostwatch core not found: expected "
                   "src/ghostwatch/__main__.py or a ghostwatch executable",
        )
    return subprocess.run(cmd, capture_output=True, text=True,
                          env=base_env(env_extra), timeout=timeout)


def snapshot(project: Path, *extra: str, **kw) -> subprocess.CompletedProcess:
    return run_ghostwatch("snapshot", str(project), *extra, **kw)


def check(project: Path, *extra: str, **kw) -> subprocess.CompletedProcess:
    return run_ghostwatch("check", str(project), *extra, **kw)


def check_json(project: Path, *extra: str, **kw) -> tuple[subprocess.CompletedProcess, dict]:
    proc = check(project, "--json", *extra, **kw)
    try:
        return proc, json.loads(proc.stdout)
    except ValueError:
        raise AssertionError(
            f"check --json did not print JSON (rc={proc.returncode}):\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr}")


def watch(project: Path, *extra: str, **kw) -> subprocess.CompletedProcess:
    return run_ghostwatch("watch", str(project), *extra, **kw)


def combined(proc: subprocess.CompletedProcess) -> str:
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


def assert_no_traceback(proc: subprocess.CompletedProcess) -> None:
    assert "Traceback" not in combined(proc), combined(proc)


# ---------------------------------------------------------------- project

def make_project(base: Path, with_bundle: bool = True) -> Path:
    project = base / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "app.py").write_text(APP_PY)
    (project / "src" / "util.py").write_text(UTIL_PY)
    (project / "notes.txt").write_text(NOTES_TXT)
    if with_bundle:
        make_bundle(project)
    return project


def make_bundle(project: Path, bundle_dir: Path | None = None,
                files: list[str] | None = None,
                generated_at: str | None = None,
                symbols_included: dict[str, list[str]] | None = None,
                modes: dict[str, str] | None = None) -> Path:
    """Write a GhostSlice-shaped bundle for the project's current files.

    manifest.json carries per-file path/mode/language/original and
    sliced token placeholders, sha256 OF THE SLICED TEXT (as a real
    GhostSlice manifest does), and optional symbols_included.
    Default bundle files: src/app.py (full) and src/util.py
    (signatures, sliced text is a stub, NOT the source)."""
    bundle = bundle_dir or (project / ".claude_context")
    files = files if files is not None else ["src/app.py", "src/util.py"]
    modes = modes or {}
    entries = []
    for rel in files:
        src = project / rel
        full = src.read_text() if src.exists() else ""
        mode = modes.get(rel, "full" if rel.endswith("app.py") else "signatures")
        sliced = full if mode == "full" else f"# signatures for {rel}\n"
        dest = bundle / "files" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(sliced)
        entry = {
            "path": rel, "mode": mode,
            "language": "python" if rel.endswith(".py") else "text",
            "package": None,
            "original_tokens": max(1, len(full) // 4),
            "sliced_tokens": max(1, len(sliced) // 4),
            "sha256": hashlib.sha256(sliced.encode()).hexdigest(),
        }
        if symbols_included and rel in symbols_included:
            entry["symbols_included"] = symbols_included[rel]
        entries.append(entry)
    manifest = {
        "tool": "ghostslice", "version": "1.0.6", "preset": "claude-code",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "root": str(project.resolve()),
        "token_method": "estimate",
        "total_original_tokens": sum(e["original_tokens"] for e in entries),
        "total_sliced_tokens": sum(e["sliced_tokens"] for e in entries),
        "total_saved_tokens": 0,
        "files": entries,
    }
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (bundle / "PROMPT.md").write_text("# Prompt\n")
    return bundle


@pytest.fixture()
def project_factory(tmp_path):
    def _make(with_bundle: bool = True) -> Path:
        return make_project(tmp_path, with_bundle=with_bundle)
    return _make


@pytest.fixture()
def snapshotted_project(project_factory):
    """A project + bundle with a GhostWatch snapshot taken."""
    project = project_factory()
    proc = snapshot(project)
    assert proc.returncode == 0, combined(proc)
    return project


def load_default_snapshot(project: Path) -> dict:
    return json.loads((project / ".ghostwatch" / "snapshot.json").read_text())


def set_mtime(path: Path, when: float) -> None:
    ns = int(when * 1_000_000_000)
    os.utime(path, ns=(ns, ns))


# ---------------------------------------------------------------- fake ghostslice

FAKE_OK = '''#!/usr/bin/env python3
"""Fake ghostslice: `export <root> -o <bundle>` writes a fresh manifest."""
import json, sys
from datetime import datetime, timezone
from pathlib import Path
args = sys.argv[1:]
assert args[0] == "export", args
root = Path(args[1])
out = Path(args[args.index("-o") + 1])
out.mkdir(parents=True, exist_ok=True)
files = []
for p in sorted(root.rglob("*.py")):
    rel = p.relative_to(root).as_posix()
    if ".claude_context" in rel or ".ghostwatch" in rel:
        continue
    files.append({"path": rel, "mode": "full", "language": "python",
                  "sha256": "0" * 64})
(out / "manifest.json").write_text(json.dumps({
    "tool": "ghostslice", "version": "fake",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "root": str(root), "files": files}, indent=2) + "\\n")
(out / "PROMPT.md").write_text("# fake export\\n")
print("fake export ok")
'''

FAKE_FAIL = '''#!/usr/bin/env python3
import sys
print("fake ghostslice exploded", file=sys.stderr)
sys.exit(3)
'''


def install_fake_ghostslice(base: Path, script: str = FAKE_OK) -> dict:
    """Return env_extra putting a fake `ghostslice` first on PATH."""
    bindir = base / "fakebin"
    bindir.mkdir(parents=True, exist_ok=True)
    exe = bindir / "ghostslice"
    exe.write_text(script)
    exe.chmod(0o755)
    return {"PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")}


def no_ghostslice_env() -> dict:
    """env_extra where ghostslice is neither on PATH nor importable."""
    return {"PATH": os.defpath}
