"""Budget honesty, doctor, and the MCP surface."""
from __future__ import annotations

import json
import subprocess

from conftest import (ENTRY_REL, build, cli_base, cli_env, combined,
                      file_entry, load_manifest, run_cli)


def test_tiny_budget_still_writes_bundle_and_reports_unmet(
        starter_project, tmp_path):
    out = tmp_path / "bundle"
    proc = build(starter_project, out, "--budget", "60")
    assert (out / "PRIMER.md").is_file(), combined(proc)
    blob = (combined(proc) + json.dumps(load_manifest(out))).lower()
    assert "unmet" in blob or "not met" in blob or "exceed" in blob, (
        "an impossible budget must be reported, never hidden")
    entry = file_entry(load_manifest(out), ENTRY_REL)
    assert entry is not None, "entry point dropped entirely under tiny budget"
    assert entry.get("mode") in ("outline", "signatures"), entry
    assert (out / "files" / ENTRY_REL).is_file()


def test_doctor_reports_sources(starter_project):
    proc = run_cli("doctor", starter_project)
    assert proc.returncode == 0, combined(proc)
    out = combined(proc).lower()
    assert "readme" in out
    assert "decisions" in out or "agents" in out


def test_mcp_lists_primer_tools():
    proc = subprocess.Popen(
        cli_base() + ["mcp"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env=cli_env())
    payload = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05",
                               "capabilities": {},
                               "clientInfo": {"name": "pytest",
                                              "version": "0"}}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                    "params": {}}),
    ]) + "\n"
    try:
        stdout, _ = proc.communicate(payload, timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError("MCP server did not answer tools/list")
    names = set()
    for line in stdout.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        tools = (msg.get("result") or {}).get("tools") or []
        names.update(t.get("name") for t in tools)
    assert "primer_build" in names, names
    assert "primer_check" in names, names
