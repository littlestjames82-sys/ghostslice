"""Shared helpers for the GhostLogs behavioural tests.

CONTRACT ASSUMED FROM THE WAVE 4 PLAN LINE (see REPORT_B.md for the full
list, including any alignment changes made once Agent A's core landed).
GhostLogs is a log slicer: it reads one log file and writes a
token-budgeted incident pack. The public surface these tests drive:

    ghostlogs pack <logfile> -o <pack-dir> [--budget <tokens>]

Pack contents assumed at plan level:
  - manifest.json in the pack dir, with line accounting whose inputs
    reconcile exactly: lines in = lines kept + lines collapsed + lines
    dropped, and a stated token budget the pack estimate respects.
  - a human/agent readable pack file (PACK.md) with error windows and
    deduped exemplars (each repeated line shown once, with its count).

Entrypoint discovery, in order:
  1. GHOSTLOGS_CMD environment override (split on whitespace)
  2. a ``ghostlogs`` console script on PATH
  3. ``python -m ghostlogs`` with ``src/`` on PYTHONPATH (repo layout)
  4. ``python -m ghostlogs`` as an installed package

If no entrypoint exists the behavioural tests FAIL with a clear
"core not ready" message - they do not skip, so a green run can never be
faked by a missing build. Fixture-sanity tests in
``test_fixtures_sanity.py`` do not need the core and pass on their own.

Behavioural tests copy the fixture log into ``tmp_path`` first so runs
never write anything next to the checked-in fixtures.
"""
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The planted secret-shaped literals in fixtures/noisy.log. They are
# canaries: fake, labelled by shape only, and they must never appear in
# any output. CANARY (GitHub token shape) sits on a routine INFO line;
# AWS_CANARY (AWS access key shape) sits inside an ERROR line, so it
# lands inside an error window: the plan's own planted-secret bar.
CANARY = "ghp_" + "ZQXW" * 9
AWS_CANARY = "AKIA" + "ZQXW7EXAMPLEKEY1"

HEARTBEAT = "heartbeat ok"
HEARTBEAT_COUNT = 40
CACHE_WARN = "cache miss rate above threshold"
CACHE_WARN_COUNT = 12
ERROR_LINE = "ERROR db connection failed host=db1"
ERROR_COUNT = 5
TOTAL_LINES = 70


def find_entrypoint():
    """Return a command prefix list for ghostlogs, or None."""
    override = os.environ.get("GHOSTLOGS_CMD")
    if override:
        return shlex.split(override)
    script = shutil.which("ghostlogs")
    if script:
        return [script]
    src = REPO / "src"
    if (src / "ghostlogs" / "__main__.py").exists() or (
        src / "ghostlogs" / "__init__.py"
    ).exists():
        return [sys.executable, "-m", "ghostlogs"]
    try:
        import ghostlogs  # noqa: F401

        return [sys.executable, "-m", "ghostlogs"]
    except Exception:
        return None


ENTRYPOINT = find_entrypoint()


def run_ghostlogs(args, timeout=120):
    """Run ghostlogs with args (list of str/Path). Fail if core missing."""
    if ENTRYPOINT is None:
        pytest.fail(
            "ghostlogs core not ready: no entrypoint found "
            "(GHOSTLOGS_CMD, PATH, src layout, or installed package)"
        )
    env = dict(os.environ)
    src = REPO / "src"
    if src.exists():
        env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        ENTRYPOINT + [str(a) for a in args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return proc


def sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture()
def log_copy(tmp_path):
    """A private copy of the noisy fixture plus its pre-run hash."""
    src = FIXTURES / "noisy.log"
    dst = tmp_path / "noisy.log"
    shutil.copyfile(src, dst)
    return dst


def build_pack(log_path, out_dir, extra_args=()):
    """Run `ghostlogs pack` and return (proc, out_dir Path)."""
    proc = run_ghostlogs(["pack", log_path, "-o", out_dir, *extra_args])
    return proc, Path(out_dir)


def load_manifest(out_dir):
    """Load manifest.json from a pack dir, failing with its text if odd."""
    mpath = Path(out_dir) / "manifest.json"
    assert mpath.exists(), f"manifest.json missing from pack dir {out_dir}"
    try:
        return json.loads(mpath.read_text())
    except json.JSONDecodeError:
        pytest.fail(f"manifest.json is not valid JSON:\n{mpath.read_text()[:2000]}")


def pack_text(out_dir):
    """Return the concatenated text of the readable pack file(s).

    Looks for PACK.md first, then any other markdown/text pack file in
    the pack dir besides the manifest.
    """
    out = Path(out_dir)
    for name in ("INCIDENT.md", "PACK.md"):
        preferred = out / name
        if preferred.exists():
            return preferred.read_text(errors="replace")
    chunks = []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.suffix in {".md", ".txt"} and p.name != "manifest.json":
            chunks.append(p.read_text(errors="replace"))
    return "\n".join(chunks)


def all_output_text(out_dir, proc=None):
    """Every byte of text the run produced: pack files plus stdio."""
    parts = []
    out = Path(out_dir)
    if out.exists():
        for p in sorted(out.rglob("*")):
            if p.is_file():
                parts.append(p.read_bytes().decode("utf-8", errors="replace"))
    if proc is not None:
        parts.append(proc.stdout or "")
        parts.append(proc.stderr or "")
    return "\n".join(parts)


def find_accounting(manifest):
    """Extract (lines_in, kept, collapsed, dropped) from a manifest.

    Accepts the field spellings documented in REPORT_B.md. Fails with a
    dump of the manifest keys if none of the spellings are present, so a
    contract drift is loud rather than silently green.
    """
    candidates = [
        manifest,
        manifest.get("lines", {}),
        manifest.get("accounting", {}),
        manifest.get("totals", {}),
        manifest.get("counts", {}),
    ]

    def pick(d, names):
        for n in names:
            if isinstance(d, dict) and isinstance(d.get(n), int):
                return d[n]
        return None

    in_names = ["lines_in", "total_lines", "input_lines", "lines_total", "in"]
    kept_names = ["kept", "lines_kept", "kept_lines"]
    coll_names = ["collapsed", "lines_collapsed", "collapsed_lines", "deduped"]
    drop_names = ["dropped", "lines_dropped", "dropped_lines"]
    for d in candidates:
        vals = (
            pick(d, in_names),
            pick(d, kept_names),
            pick(d, coll_names),
            pick(d, drop_names),
        )
        if all(v is not None for v in vals):
            return vals
    pytest.fail(
        "no line accounting found in manifest; top-level keys: "
        f"{sorted(manifest.keys())}"
    )


def find_budget(manifest):
    """Extract (budget, pack_estimate) token figures from a manifest."""
    candidates = [
        manifest,
        manifest.get("tokens", {}),
        manifest.get("totals", {}),
        manifest.get("budget", {}) if isinstance(manifest.get("budget"), dict) else {},
    ]

    def pick(d, names):
        for n in names:
            if isinstance(d, dict) and isinstance(d.get(n), (int, float)):
                return d[n]
        return None

    budget = None
    estimate = None
    for d in candidates:
        if budget is None:
            budget = pick(d, ["budget_tokens", "token_budget", "budget"])
        if estimate is None:
            estimate = pick(
                d,
                [
                    "pack_tokens",
                    "estimated_tokens",
                    "pack_estimated_tokens",
                    "total_sliced_tokens",
                    "tokens",
                ],
            )
    return budget, estimate
