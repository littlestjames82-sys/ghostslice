"""Parity and bypass (PLAN.md Verification bar).

Parity: the proxy estimates context with the same GhostSlice
estimator a manual run uses, so for the same file text the
proxy's ledger total and `ghostslice scan`'s total agree, and the
ledger stamps the estimator version. Bypass: the documented undo
(point the client back at the upstream, proxy stopped) restores
direct behaviour, and the proxy refuses to bind anywhere but
localhost.
"""

import json
import os
import subprocess
import sys
import time

from conftest import (
    GHOSTSLICE_SRC,
    SRC,
    ProxyProcess,
    context_block,
    free_port,
    http_post,
    make_project,
    messages_request,
    project_sections,
    requires_core,
    requires_ghostslice,
)

HEADERS = {"x-api-key": "CANARY-API-KEY-ghostproxy-leak-test-0000000001",
           "content-type": "application/json"}


def _ledger_rows(project, workdir):
    rows = []
    for base in (project, workdir):
        for path in base.rglob("*.jsonl"):
            for line in path.read_text(errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    return rows


@requires_core
def test_proxy_refuses_non_localhost_bind(tmp_path):
    project = make_project(tmp_path)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    proc = subprocess.run(
        [sys.executable, "-m", "ghostproxy", "serve", "--host", "0.0.0.0",
         "--port", str(free_port()), "--upstream", "http://127.0.0.1:9",
         "--project", str(project)],
        env=env, capture_output=True, text=True, timeout=20,
    )
    assert proc.returncode != 0, \
        "binding a non-localhost interface must be refused in v0.1 (PLAN hard rule)"


@requires_core
def test_bypass_with_proxy_stopped_matches_direct_upstream(fake_upstream, tmp_path):
    fake_upstream.mode = "mirror"
    project = make_project(tmp_path)
    raw = json.dumps(messages_request(project_sections(project))).encode()
    proxy = ProxyProcess(project, fake_upstream.url, tmp_path / "work")
    proxy.stop()  # the documented undo state: no proxy in the path at all
    status, body = http_post(fake_upstream.url + "/v1/messages", raw, HEADERS)
    assert status == 200
    assert body == raw
    assert fake_upstream.recorded[-1]["body"] == raw


@requires_core
@requires_ghostslice
def test_context_estimate_matches_ghostslice_scan(fake_upstream, tmp_path):
    """One plain file, big budget (no downgrade): proxy context total
    must equal GhostSlice's own scan estimate for the same text."""
    project = tmp_path / "project"
    project.mkdir()
    text = '"""Only file."""\n\n\ndef add(a, b):\n    return a + b\n'
    (project / "only.py").write_text(text)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(GHOSTSLICE_SRC)
    proc = subprocess.run(
        [sys.executable, "-m", "ghostslice", "scan", str(project), "--json"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"ghostslice scan failed: {proc.stderr[-1000:]}"
    scan = json.loads(proc.stdout)
    scan_tokens = scan["files"][0]["tokens"]
    assert scan_tokens > 0

    # Manual GhostSlice export of the same project: the parity claim
    # in the plan is proxy totals vs this export's sliced total.
    bundle = tmp_path / "bundle"
    proc = subprocess.run(
        [sys.executable, "-m", "ghostslice", "export", str(project), "-o", str(bundle)],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"ghostslice export failed: {proc.stderr[-1000:]}"
    manifest = json.loads((bundle / "manifest.json").read_text())
    manual_sliced = manifest["total_sliced_tokens"]

    workdir = tmp_path / "work"
    request = messages_request([context_block("only.py", text)])
    with ProxyProcess(project, fake_upstream.url, workdir) as proxy:
        status, _ = http_post(proxy.url + "/v1/messages",
                              json.dumps(request).encode(), HEADERS)
        assert status == 200
        time.sleep(0.5)
    rows = [r for r in _ledger_rows(project, workdir) if "context_tokens_in" in r]
    assert rows, "no ledger row carries a context token total to compare"
    row = rows[-1]
    assert row["context_tokens_in"] == scan_tokens, (
        f"proxy estimated {row['context_tokens_in']} context tokens for only.py, "
        f"ghostslice scan estimated {scan_tokens}: the two must use the same estimator"
    )
    assert row["context_tokens_out"] == manual_sliced, (
        f"proxy transformed the context to {row['context_tokens_out']} tokens, "
        f"a manual GhostSlice export slices it to {manual_sliced}: "
        "the plan's parity bar is that these match"
    )
    assert row.get("estimator_version"), \
        "the ledger row must stamp the estimator version (PLAN: stamped on both)"
