"""Shared fixtures and CLI discovery for GhostData tests.

Contract source: PLAN.md (MVP v0.1).

CLI (from PLAN.md, confirmed against the landed core):
    ghostdata schema <file> [--no-redact] [--format FMT]
    ghostdata pack   <file> -o <pack-dir> [--sample N] [--no-redact]
    ghostdata check  <pack-dir>
    ghostdata mcp

Discovery order:
  1. GHOSTDATA_CMD environment override (split on whitespace)
  2. an installed ``ghostdata`` executable on PATH
  3. ``python -m ghostdata`` with ``src/`` on PYTHONPATH (repo layout)

If no CLI is discoverable, CLI tests skip with "core not ready" instead
of failing: Agent B (tests/docs) is built in parallel with Agent A
(core). Fixture sanity tests do not need the core and always run.
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

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Planted sensitive values. All are FAKE, test-only literals in
# sensitive shapes (the card number is the public Visa test number and
# the SSN is the famous Woolworth sample; neither is a real credential
# or a real person's number). They must never appear in any pack file
# or command output while redaction is on.
CANARIES = [
    "canary.invalid",          # covers every planted email address
    "CANARY_PWHASH",           # covers every planted password hash
    "CANARY_TOKEN",            # covers every planted api token
    "4111111111111111",        # Luhn-valid test card number
    "078-05-1120",             # SSN-shaped sample value
]


def _cli_cmd():
    override = os.environ.get("GHOSTDATA_CMD")
    if override:
        return shlex.split(override)
    exe = shutil.which("ghostdata")
    if exe:
        return [exe]
    return [sys.executable, "-m", "ghostdata"]


def core_available() -> bool:
    if os.environ.get("GHOSTDATA_CMD"):
        return True
    if shutil.which("ghostdata"):
        return True
    pkg = ROOT / "src" / "ghostdata"
    return (pkg / "cli.py").exists()


def run_cli(args, timeout=120):
    """Run the GhostData CLI and return the CompletedProcess (text)."""
    env = dict(os.environ)
    src = ROOT / "src"
    env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        _cli_cmd() + [str(a) for a in args],
        env=env, capture_output=True, text=True, timeout=timeout)


def run_schema(path, *extra):
    proc = run_cli(["schema", path, *extra])
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def run_pack(path, out_dir, *extra, timeout=120):
    proc = run_cli(["pack", path, "-o", out_dir, *extra], timeout=timeout)
    assert proc.returncode == 0, proc.stderr
    manifest = json.loads(
        (Path(out_dir) / "manifest.json").read_text(encoding="utf-8"))
    return proc, manifest


def column(schema_like, name):
    """Find one column dict by name in a schema or manifest payload."""
    cols = schema_like["columns"]
    for col in cols:
        if col["name"] == name:
            return col
    raise AssertionError("column %r not in %r"
                         % (name, [c["name"] for c in cols]))


def sha256_of(path) -> str:
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def assert_no_canaries_in_text(text, where):
    for canary in CANARIES:
        assert canary not in text, (
            "planted sensitive value %r leaked into %s" % (canary, where))


def assert_no_canaries_in_tree(root, extra_texts=()):
    root = Path(root)
    for path in sorted(root.rglob("*")):
        if path.is_file():
            assert_no_canaries_in_text(
                path.read_text(encoding="utf-8", errors="replace"),
                str(path))
    for text in extra_texts:
        assert_no_canaries_in_text(text, "command output")


def sample_row_count(pack_dir, manifest) -> int:
    import csv as csv_mod
    sample_path = Path(pack_dir) / manifest["sample"]["file"]
    fmt = manifest["source"]["format"]
    if fmt in ("csv", "tsv"):
        with open(sample_path, newline="", encoding="utf-8") as fh:
            rows = list(csv_mod.reader(
                fh, delimiter="\t" if fmt == "tsv" else ","))
        return len(rows) - 1  # header
    if fmt == "jsonl":
        return len([ln for ln in sample_path.read_text(
            encoding="utf-8").splitlines() if ln.strip()])
    if fmt == "json":
        return len(json.loads(sample_path.read_text(encoding="utf-8")))
    raise AssertionError("unknown format %r" % fmt)


@pytest.fixture
def people_csv():
    return FIXTURES / "people.csv"


@pytest.fixture
def orders_csv():
    return FIXTURES / "orders.csv"


@pytest.fixture
def events_jsonl():
    return FIXTURES / "events.jsonl"


@pytest.fixture
def records_json():
    return FIXTURES / "records.json"


@pytest.fixture
def temps_tsv():
    return FIXTURES / "temps.tsv"


requires_core = pytest.mark.skipif(
    not core_available(), reason="core not ready")
