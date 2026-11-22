"""Shared harness for GhostLedger tests.

Black-box discipline: CLI tests run `python -m ghostledger` as a
subprocess against a tmp ledger file and read the ledger / report
files back as JSON. They never import ghostledger internals.

Exit-code contract (core CLI docstring): 0 ok, 1 loop warning
present (report/summary only), 2 error. Tests accept 0 or 1 where a
warning may legitimately be present and assert the distinction where
the warning state is the point of the test.

If the core (src/ghostledger, Agent A's half) is not present, CLI
tests skip with an explicit reason instead of failing spuriously;
the format/fixture tests still run. See REPORT_B.md.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXAMPLES = REPO / "examples"

CORE_AVAILABLE = (SRC / "ghostledger" / "cli.py").exists()

requires_core = pytest.mark.skipif(
    not CORE_AVAILABLE,
    reason="ghostledger core (src/ghostledger/cli.py) not present yet: "
    "Agent A build pending. See REPORT_B.md. Format tests still run.",
)

# The one credential-shaped value in this repo, planted on purpose in
# tests/fixtures/proxy-report.json to prove import drops it. It is a
# labelled fake canary, not a real credential.
CANARY = "FAKE-LEDGER-CANARY-not-a-real-key"

# Local dated snapshot rates (GhostSlice prices.json, as of
# 2026-10-12). Tests hand-compute with these; they are estimates in
# a dated local table, never live prices.
RATES = {
    "claude-sonnet": (3.0, 15.0),
    "claude-opus": (15.0, 75.0),
    "claude-haiku": (0.8, 4.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    "local": (0.0, 0.0),
}
PRICE_TABLE_AS_OF = "2026-10-12"


def hand_cost(model, input_tokens, output_tokens):
    """Expected cost_estimate_usd, or None for an unlisted model."""
    if model not in RATES:
        return None
    in_rate, out_rate = RATES[model]
    return round((input_tokens * in_rate + output_tokens * out_rate) / 1_000_000, 6)


def run_cli(args, *, cwd=None, timeout=60):
    """Run the GhostLedger CLI as a black box: python -m ghostledger ...

    Global flags (--ledger/--prices) come BEFORE the subcommand in
    the core's argparse layout, so callers pass the full arg list.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "ghostledger", *[str(a) for a in args]],
        capture_output=True, text=True, cwd=cwd or REPO, env=env,
        timeout=timeout,
    )


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_jsonl(path):
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


@pytest.fixture()
def ledger_path(tmp_path):
    return tmp_path / "books" / ".ghostledger.jsonl"


def add_entry(ledger, *extra, expect=(0,)):
    """Add one manual entry via the CLI and assert the exit code."""
    proc = run_cli(["--ledger", ledger, "add", *extra])
    assert proc.returncode in expect, proc.stdout + proc.stderr
    return proc
