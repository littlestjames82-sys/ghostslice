"""Staleness contract: a fresh bundle reports fresh; changed, missing,
or refused sources, facts drift, new entry points, and missing memory
sources report stale; an unverifiable bundle cannot be pronounced on.
Staleness is slice-level: an edit that leaves the recorded slice
unchanged is not detected, and a new non-entry file is information,
not a verdict."""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from conftest import (ENTRY_REL, FANIN_REL, cli_base, cli_env, combined,
                      load_manifest, run_cli)


def run_stale(*args):
    proc = run_cli("stale", *args)
    try:
        report = json.loads(proc.stdout)
    except ValueError:
        raise AssertionError(f"stale gave no JSON: {combined(proc)}")
    return proc, report


def changed_paths(report):
    return [entry["path"] for entry in report["changed"]]


def refused_paths(report):
    return [entry["path"] for entry in report["refused"]]


def test_stale_fresh_bundle_reports_fresh(starter_project, built_bundle):
    proc, report = run_stale(built_bundle)
    assert proc.returncode == 0, combined(proc)
    assert report["ok"] is True and report["stale"] is False, report
    assert ENTRY_REL in report["unchanged"], report
    assert FANIN_REL in report["unchanged"], report
    assert report["files_checked"] == len(
        load_manifest(built_bundle)["files"]), report
    assert report["changed"] == [] and report["missing"] == [], report


def test_stale_detects_changed_source(starter_project, built_bundle):
    target = starter_project / FANIN_REL
    target.write_text(target.read_text()
                      + "\n\ndef brand_new_helper():\n    return 1\n")
    proc, report = run_stale(built_bundle)
    assert proc.returncode == 1, combined(proc)
    assert report["stale"] is True, report
    assert FANIN_REL in changed_paths(report), report
    assert ENTRY_REL in report["unchanged"], report


def test_stale_ignores_edit_that_leaves_slice_unchanged(
        starter_project, built_bundle):
    target = starter_project / FANIN_REL
    target.write_text(target.read_text() + "\n# a trailing comment\n")
    proc, report = run_stale(built_bundle)
    assert proc.returncode == 0, combined(proc)
    assert FANIN_REL in report["unchanged"], report


def test_stale_detects_missing_source(starter_project, built_bundle):
    (starter_project / FANIN_REL).unlink()
    proc, report = run_stale(built_bundle)
    assert proc.returncode == 1, combined(proc)
    assert FANIN_REL in report["missing"], report


def test_stale_detects_new_entry_point(starter_project, built_bundle):
    (starter_project / "src" / "widgetforge" / "app.py").write_text(
        "def main():\n    return 0\n")
    proc, report = run_stale(built_bundle)
    assert proc.returncode == 1, combined(proc)
    assert "src/widgetforge/app.py" in report["new_entry_points"], report


def test_stale_new_nonentry_file_is_information_only(
        starter_project, built_bundle):
    (starter_project / "src" / "widgetforge" / "extra.py").write_text(
        "VALUE = 1\n")
    proc, report = run_stale(built_bundle)
    assert proc.returncode == 0, combined(proc)
    assert report["ok"] is True, report
    assert "src/widgetforge/extra.py" in report["new_files"], report


def test_stale_detects_facts_drift(starter_project, built_bundle):
    toml = starter_project / "pyproject.toml"
    text = toml.read_text()
    assert re.search(r'version\s*=\s*"[^"]+"', text), text
    toml.write_text(re.sub(r'version\s*=\s*"[^"]+"',
                           'version = "9.9.9"', text, count=1))
    proc, report = run_stale(built_bundle)
    assert proc.returncode == 1, combined(proc)
    fields = [entry["field"] for entry in report["facts_changed"]]
    assert "version" in fields, report


def test_stale_detects_missing_memory_source(
        starter_project, built_bundle):
    (starter_project / "DECISIONS.md").unlink()
    proc, report = run_stale(built_bundle)
    assert proc.returncode == 1, combined(proc)
    assert "DECISIONS.md" in report["memory_missing"], report


def test_stale_missing_bundle_is_could_not_check(tmp_path):
    proc, _report = run_stale(tmp_path / "no-such-bundle")
    assert proc.returncode == 2, combined(proc)


def test_stale_refuses_unverifiable_bundle(built_bundle):
    primer = built_bundle / "PRIMER.md"
    primer.write_text(primer.read_text() + "\nOne quiet extra line.\n")
    proc, report = run_stale(built_bundle)
    assert proc.returncode == 2, combined(proc)
    assert report["ok"] is False and report["stale"] is None, report


def test_stale_project_override_compares_against_given_tree(
        starter_project, built_bundle, tmp_path):
    moved = tmp_path / "moved_project"
    shutil.copytree(starter_project, moved)
    target = moved / FANIN_REL
    target.write_text(target.read_text()
                      + "\n\ndef moved_helper():\n    return 2\n")
    proc, report = run_stale(built_bundle, "--project", moved)
    assert proc.returncode == 1, combined(proc)
    assert report["project_root_source"] == "argument", report
    assert FANIN_REL in changed_paths(report), report
    proc, report = run_stale(built_bundle, "--project", starter_project)
    assert proc.returncode == 0, combined(proc)
    assert report["ok"] is True, report


def test_stale_refuses_symlinked_source_escaping_project(
        starter_project, built_bundle, tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text("OUTSIDE_MARKER = 'not project code'\n")
    target = starter_project / FANIN_REL
    target.unlink()
    try:
        target.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available on this platform")
    proc, report = run_stale(built_bundle)
    # Parent resolution at merge (Oct 18, 2026): the harden lane
    # strengthened check_bundle to refuse a source that escapes the
    # project, so the swapped symlink now fails check itself and
    # stale's documented gate (any check failure -> exit 2,
    # could-not-check) fires before the per-source refusal pass.
    # The refusal still happens, one step earlier; assert that.
    assert proc.returncode == 2, combined(proc)
    assert any(FANIN_REL in err for err in report["errors"]), report
    assert "OUTSIDE_MARKER" not in proc.stdout, proc.stdout


def _mcp_session(payload_lines, timeout=30):
    proc = subprocess.Popen(
        cli_base() + ["mcp"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env=cli_env())
    payload = "\n".join(json.dumps(line) for line in payload_lines) + "\n"
    try:
        stdout, _ = proc.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError("MCP server did not answer")
    messages = []
    for line in stdout.splitlines():
        try:
            messages.append(json.loads(line))
        except ValueError:
            continue
    return messages


def test_mcp_primer_stale_tool(built_bundle):
    messages = _mcp_session([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "primer_stale",
                    "arguments": {"bundle": str(built_bundle)}}},
    ])
    names = set()
    call_payload = None
    for msg in messages:
        result = msg.get("result") or {}
        names.update(t.get("name") for t in result.get("tools") or [])
        if msg.get("id") == 3:
            content = result.get("content") or []
            if content:
                call_payload = json.loads(content[0]["text"])
    assert "primer_stale" in names, names
    assert call_payload is not None, messages
    assert call_payload["exit_code"] == 0, call_payload
    assert call_payload["stale"] is False, call_payload
