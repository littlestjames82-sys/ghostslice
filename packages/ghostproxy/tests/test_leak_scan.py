"""Leak scan (PLAN.md Verification bar): zero hits is the pass bar.

Runs a full proxy session carrying a canary API key (in the auth
header) and a canary secret (inside a project file), then scans
every file the proxy wrote - ledger, reports, logs, transform
maps, its own process log - for either canary. The scanner reports
file + canary label only, never the canary value.
"""

import json
import time
from pathlib import Path

from conftest import (
    CANARIES,
    CANARY_API_KEY,
    ProxyProcess,
    http_post,
    make_project,
    messages_request,
    project_sections,
    requires_core,
)
from leakscan import scan_tree

HEADERS = {"x-api-key": CANARY_API_KEY, "anthropic-version": "2023-06-01",
           "content-type": "application/json"}


def test_scanner_finds_a_planted_canary(tmp_path):
    """The scanner itself must work, or a clean integration result means nothing."""
    planted = tmp_path / "planted.log"
    planted.write_text(f"prefix {CANARIES['secret']} suffix")
    hits = scan_tree(tmp_path, CANARIES)
    assert hits == [(str(planted), "secret")]


def test_scanner_clean_tree_has_zero_hits(tmp_path):
    (tmp_path / "clean.jsonl").write_text('{"tokens_in": 10, "fallback": false}\n')
    assert scan_tree(tmp_path, CANARIES) == []


def test_scanner_covers_binary_files(tmp_path):
    blob = tmp_path / "cache.bin"
    blob.write_bytes(b"\x00\x01" + CANARIES["api-key"].encode() + b"\xff")
    assert scan_tree(tmp_path, CANARIES) == [(str(blob), "api-key")]


def _proxy_written_files(roots, before):
    written = []
    for root in roots:
        for path in Path(root).rglob("*"):
            if path.is_file() and str(path) not in before:
                written.append(path)
            elif path.is_file() and path.stat().st_mtime > before[str(path)]:
                written.append(path)
    return written


def _snapshot(roots):
    snap = {}
    for root in roots:
        for path in Path(root).rglob("*"):
            if path.is_file():
                snap[str(path)] = path.stat().st_mtime
    return snap


@requires_core
def test_no_canary_in_anything_the_proxy_writes(fake_upstream, tmp_path):
    project = make_project(tmp_path)
    workdir = tmp_path / "work"
    before = _snapshot([project, workdir])
    request = messages_request(project_sections(project))
    with ProxyProcess(project, fake_upstream.url, workdir) as proxy:
        status, _ = http_post(proxy.url + "/v1/messages",
                              json.dumps(request).encode(), HEADERS)
        assert status == 200
        time.sleep(0.5)  # let ledger writes flush before the proxy stops
    written = _proxy_written_files([project, workdir], before)
    assert written, "the proxy wrote nothing at all; there is no ledger/log to audit"
    hits = []
    for path in written:
        hits.extend(scan_tree(path, CANARIES))
    assert hits == [], f"canary leaks in proxy output (file, label): {hits}"


@requires_core
def test_generated_report_is_canary_free(fake_upstream, tmp_path):
    """The `ghostproxy report` output is a proxy-written file too."""
    import os
    import subprocess
    import sys

    from conftest import GHOSTSLICE_SRC, SRC

    project = make_project(tmp_path)
    workdir = tmp_path / "work"
    request = messages_request(project_sections(project))
    with ProxyProcess(project, fake_upstream.url, workdir) as proxy:
        http_post(proxy.url + "/v1/messages", json.dumps(request).encode(), HEADERS)
        time.sleep(0.5)
    ledgers = list(project.rglob("*.jsonl")) + list(workdir.rglob("*.jsonl"))
    assert ledgers, "no ledger was written under the project or the proxy work dir"
    ledger = ledgers[0]
    report_path = tmp_path / "report.json"
    env = dict(os.environ)
    paths = [str(SRC)] + ([str(GHOSTSLICE_SRC)] if GHOSTSLICE_SRC.is_dir() else [])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    proc = subprocess.run(
        [sys.executable, "-m", "ghostproxy", "report",
         "--ledger", str(ledger), "--json"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"report CLI failed: {proc.stderr[-1000:]}"
    report_path.write_text(proc.stdout)
    json.loads(report_path.read_text())  # the report must be valid JSON
    assert scan_tree(report_path, CANARIES) == []
