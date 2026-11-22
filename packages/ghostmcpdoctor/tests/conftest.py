"""Shared helpers for the GhostMCP Doctor behavioural tests.

CONTRACT ASSUMED FROM THE TASK / SUITE PLAN (see REPORT_B.md).
Core (Agent A's src/**, PLAN.md, pyproject.toml) is built in parallel,
so these tests drive GhostMCP Doctor only through its public CLI surface
and keep every adaptation in this one file:

  Scope (task): read-only MCP config scanner. Reports duplicates,
  missing commands, and broad permissions. Env secret values are
  redacted (present / absent only). It never edits configs.

  Plausible CLI shapes the harness accepts, in preference order:
    ghostmcpdoctor scan   <path> [--json] [-o <report>]
    ghostmcpdoctor check  <path> [--json]
    ghostmcpdoctor doctor <path> [--json]
    ghostmcpdoctor audit  <path> [--json]
    ghostmcpdoctor report <path> [--json]
    ghostmcpdoctor        <path> [--json]

  <path> may be a single config file or a directory of configs.
  The subcommand is discovered from `--help` when possible, then by
  probing. Findings may exit 0 or 1; a config that cannot be scanned
  at all must never look like a clean pass.

Entrypoint discovery, in order:
  1. a ``ghostmcpdoctor`` console script on PATH
  2. ``python -m ghostmcpdoctor`` with ``src/`` on PYTHONPATH
  3. ``python -m ghostmcpdoctor`` as an installed package

If no entrypoint exists the behavioural tests FAIL with a clear
"core not ready" message - they do not skip, so a green run can never
be faked by a missing build. Fixture-sanity tests in
``test_fixtures_sanity.py`` do not need the core and pass on their own.

Every behavioural test copies its fixture configs into ``tmp_path``
first, so a scan can be proved read-only against the copies (hash and
file list before vs after) and checked-in fixtures are never touched.
Report files a run creates inside its working directory are collected
as part of the output, which is what the redaction tests inspect.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXAMPLES = REPO / "examples"

FAKE_SECRET_CANARIES = (
    "FAKE-SECRET-CANARY-DOCTOR-7f3a9c-never-print",
    "FAKE-TOKEN-CANARY-DOCTOR-51bd02-never-print",
)

_SUBCOMMAND_CANDIDATES = ("scan", "check", "doctor", "audit", "report")


def find_entrypoint():
    """Return a command prefix list for ghostmcpdoctor, or None."""
    for name in ("ghostmcpdoctor", "ghost-mcp-doctor"):
        script = shutil.which(name)
        if script:
            return [script]
    src = REPO / "src"
    for mod in ("ghostmcpdoctor", "ghost_mcp_doctor"):
        pkg = src / mod
        if (pkg / "__main__.py").exists() or (pkg / "__init__.py").exists():
            return [sys.executable, "-m", mod]
    try:
        import ghostmcpdoctor  # noqa: F401

        return [sys.executable, "-m", "ghostmcpdoctor"]
    except Exception:
        return None


ENTRYPOINT = find_entrypoint()


def _base_env():
    env = dict(os.environ)
    src = REPO / "src"
    if src.is_dir():
        env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    env["NO_COLOR"] = "1"
    return env


def run_cli(args, cwd=None, timeout=120):
    """Run the raw CLI (no subcommand discovery). Fail if core missing."""
    if ENTRYPOINT is None:
        pytest.fail(
            "GhostMCP Doctor core not ready: no entrypoint found (no "
            "`ghostmcpdoctor` script on PATH, no src/ghostmcpdoctor "
            "package, package not installed). This test needs Agent A's "
            "core - see REPORT_B.md."
        )
    return subprocess.run(
        ENTRYPOINT + [str(a) for a in args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
        env=_base_env(),
    )


def out_text(proc):
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


_discovered_subcommand = ...


def discover_subcommand():
    """Pick the scan subcommand: from --help if listed, else probe/None.

    Returns a string like "scan", or None if the CLI appears to take a
    bare path (or help is unusable, in which case probing decides).
    """
    global _discovered_subcommand
    if _discovered_subcommand is not ...:
        return _discovered_subcommand
    _discovered_subcommand = None
    if ENTRYPOINT is None:
        return None
    try:
        proc = run_cli(["--help"])
    except Exception:
        return None
    help_text = out_text(proc).lower()
    # Only trust words that appear as command entries, not prose: look at
    # the help as a whole but prefer the earliest candidate that occurs
    # as a standalone token.
    for cand in _SUBCOMMAND_CANDIDATES:
        if re.search(r"(?m)^\s{0,4}" + cand + r"\b", help_text) or \
                re.search(r"\{[^}]*\b" + cand + r"\b[^}]*\}", help_text) or \
                re.search(r"(?m)" + cand + r"\s{2,}\S", help_text):
            _discovered_subcommand = cand
            break
    return _discovered_subcommand


def _looks_like_scan(proc, workdir):
    """Heuristic: did this invocation actually scan something?"""
    text = out_text(proc).lower()
    if "traceback" in text:
        return False
    if proc.returncode not in (0, 1):
        # 2 is a legitimate "findings / could not scan" code in the
        # family, but for probing it usually means usage error.
        if not any(tok in text for tok in ("server", "mcp", "config")):
            return False
    usage_markers = ("usage:", "invalid choice", "unrecognized arguments",
                     "no such command", "unknown command")
    if any(m in text for m in usage_markers) and \
            not any(tok in text for tok in ("mcpservers", "server", "duplicate")):
        return False
    if any(tok in text for tok in ("server", "mcp", "config", "scan")):
        return True
    # A silent success that wrote a report file also counts.
    return workdir is not None and any(
        p.is_file() for p in Path(workdir).rglob("*"))


def scan_path(target, tmp_path, want_json=False):
    """Scan a config file or directory; return (proc, combined_text).

    combined_text is stdout + stderr + the text of any report files the
    run created inside its fresh working directory (tmp_path/_work).
    That is exactly the surface the redaction tests must inspect: a
    secret leaking into a report file is still a leak.
    """
    workdir = Path(tmp_path) / "_work"
    workdir.mkdir(parents=True, exist_ok=True)
    attempts = []
    sub = discover_subcommand()
    ordered = []
    if sub:
        ordered.append(sub)
    ordered += [c for c in _SUBCOMMAND_CANDIDATES if c != sub]
    ordered.append(None)  # bare path form last

    for cand in ordered:
        args = ([cand] if cand else []) + [target]
        if want_json:
            args = args + ["--json"]
        attempts.append(args)
        proc = run_cli(args, cwd=workdir)
        if _looks_like_scan(proc, workdir):
            return proc, combined_output(proc, workdir)
    # Nothing probed cleanly: return the most plausible attempt so the
    # test failure shows a real invocation, not a probe artefact.
    proc = run_cli(attempts[0], cwd=workdir)
    return proc, combined_output(proc, workdir)


def combined_output(proc, workdir):
    texts = [out_text(proc)]
    workdir = Path(workdir)
    if workdir.is_dir():
        for p in sorted(workdir.rglob("*")):
            if p.is_file():
                try:
                    texts.append(p.read_text(errors="replace"))
                except Exception:
                    pass
    return "\n".join(texts)


def parse_json_output(text):
    """Best-effort: parse stdout-shaped JSON out of combined output."""
    stripped = text.strip()
    for candidate in (stripped,):
        try:
            return json.loads(candidate)
        except Exception:
            pass
    start, end = stripped.find("{"), stripped.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(stripped[start:end + 1])
        except Exception:
            return None
    start, end = stripped.find("["), stripped.rfind("]")
    if 0 <= start < end:
        try:
            return json.loads(stripped[start:end + 1])
        except Exception:
            return None
    return None


def load_report_json(tmp_path):
    """Parse the mcpdoctor-report.json a scan wrote into its work dir.

    This is the precise structured surface: prefer it over text-window
    heuristics whenever a test needs per-server / per-issue precision
    (the human summary legitimately contains words like 'duplicates: 0'
    and a MISSING-COMMAND note, which would poison naive text checks).
    Returns None if no report file was written.
    """
    workdir = Path(tmp_path) / "_work"
    candidates = []
    if workdir.is_dir():
        candidates = sorted(workdir.rglob("mcpdoctor-report.json")) + \
            sorted(workdir.rglob("*report*.json"))
    for p in candidates:
        try:
            return json.loads(p.read_text())
        except Exception:
            continue
    return None


def copy_fixture(tmp_path, name):
    dst = Path(tmp_path) / name
    shutil.copytree(FIXTURES / name, dst)
    return dst


def snapshot_tree(root):
    """Map relpath -> sha256 for every file under root."""
    root = Path(root)
    snap = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            snap[str(p.relative_to(root))] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return snap


def window_around(text, needle, width=700):
    low = text.lower()
    idx = low.find(needle.lower())
    if idx < 0:
        return ""
    return low[max(0, idx - width): idx + len(needle) + width]
