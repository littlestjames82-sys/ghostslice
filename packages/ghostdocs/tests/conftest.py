"""Shared helpers for the GhostDocs behavioural tests.

CONTRACT ASSUMED FROM PLAN.md (see REPORT_B.md for the full list).
Core (Agent A's src/**) was not present when these tests were written, so
they drive GhostDocs only through the public surface the plan describes:

    ghostdocs scan   <corpus> [--json]
    ghostdocs export <corpus> -o <out-dir> [--format chunks]
    ghostdocs report <corpus> [-o <file>]

Entrypoint discovery, in order:
  1. a ``ghostdocs`` console script on PATH
  2. ``python -m ghostdocs`` with ``src/`` on PYTHONPATH (repo layout)
  3. ``python -m ghostdocs`` as an installed package

If no entrypoint exists the behavioural tests FAIL with a clear
"core not ready" message - they do not skip, so a green run can never be
faked by a missing build. Fixture-sanity tests in
``test_fixtures_sanity.py`` do not need the core and pass on their own.

Every behavioural test first copies its fixture corpus into ``tmp_path``
so runs never write ledgers, profiles, or reports into the checked-in
fixtures.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def find_entrypoint():
    """Return a command prefix list for ghostdocs, or None."""
    script = shutil.which("ghostdocs")
    if script:
        return [script]
    src = REPO / "src"
    if (src / "ghostdocs" / "__main__.py").exists() or (
        src / "ghostdocs" / "__init__.py"
    ).exists():
        return [sys.executable, "-m", "ghostdocs"]
    try:
        import ghostdocs  # noqa: F401

        return [sys.executable, "-m", "ghostdocs"]
    except Exception:
        return None


ENTRYPOINT = find_entrypoint()


def run_ghostdocs(args, timeout=120):
    """Run ghostdocs with args (list of str/Path). Fail if core missing."""
    if ENTRYPOINT is None:
        pytest.fail(
            "GhostDocs core not ready: no entrypoint found (no `ghostdocs` "
            "script on PATH, no src/ghostdocs package, package not "
            "installed). This test needs Agent A's core - see REPORT_B.md."
        )
    env = dict(os.environ)
    src = REPO / "src"
    if src.is_dir():
        env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    env["NO_COLOR"] = "1"
    return subprocess.run(
        ENTRYPOINT + [str(a) for a in args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def out_text(proc):
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


def scan_corpus(corpus):
    """Run `ghostdocs scan`, preferring --json, falling back to text."""
    proc = run_ghostdocs(["scan", corpus, "--json"])
    if proc.returncode == 0 and proc.stdout.strip():
        return proc
    return run_ghostdocs(["scan", corpus])


def export_corpus(corpus, out_dir, extra_args=()):
    return run_ghostdocs(["export", corpus, "-o", out_dir, *extra_args])


def report_corpus(corpus, out_file):
    """Run `ghostdocs report`; try -o first, then a bare report run."""
    proc = run_ghostdocs(["report", corpus, "-o", out_file])
    texts = [out_text(proc)]
    if Path(out_file).is_file():
        texts.append(Path(out_file).read_text(errors="replace"))
    else:
        bare = run_ghostdocs(["report", corpus])
        texts.append(out_text(bare))
        # A bare report may drop an HTML file next to the corpus.
        for html in Path(corpus).rglob("*.html"):
            texts.append(html.read_text(errors="replace"))
    return proc, "\n".join(texts)


def copy_corpus(tmp_path, name):
    dst = tmp_path / name
    shutil.copytree(FIXTURES / name, dst)
    return dst


def bundle_text(out_dir):
    """All readable text under an export dir, plus relative file names."""
    out_dir = Path(out_dir)
    texts, names = [], []
    if not out_dir.is_dir():
        return "", []
    for p in sorted(out_dir.rglob("*")):
        if p.is_file():
            names.append(str(p.relative_to(out_dir)))
            try:
                texts.append(p.read_text(errors="replace"))
            except Exception:
                pass
    return "\n".join(texts), names


def load_manifest(out_dir):
    """Find and parse a manifest.json anywhere under an export dir."""
    for p in sorted(Path(out_dir).rglob("manifest*.json")):
        try:
            return json.loads(p.read_text())
        except Exception:
            continue
    return None


def context_window(text, needle, width=600):
    """Text around the first occurrence of needle (case-insensitive)."""
    low = text.lower()
    idx = low.find(needle.lower())
    if idx < 0:
        return ""
    return low[max(0, idx - width): idx + len(needle) + width]
