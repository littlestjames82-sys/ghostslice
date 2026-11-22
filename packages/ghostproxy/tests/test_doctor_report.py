"""Doctor and report surface (PLAN.md MVP sections 4 and 5).

Doctor is a read-only health check: it must not make a billable
call (the fake upstream records any POST to the messages endpoint;
headers-only or no contact at all is the pass bar). The report must
roll the ledger into the per-request shape GhostBench consumes and
must not contain request bodies, which are off by default.
"""

import json
import os
import subprocess
import sys
import time

from conftest import (
    GHOSTSLICE_SRC,
    PROMPT_MARKER,
    SRC,
    ProxyProcess,
    http_post,
    make_project,
    messages_request,
    project_sections,
    requires_core,
)

HEADERS = {"x-api-key": "CANARY-API-KEY-ghostproxy-leak-test-0000000001",
           "content-type": "application/json"}


def _cli(args, timeout=60):
    env = dict(os.environ)
    paths = [str(SRC)] + ([str(GHOSTSLICE_SRC)] if GHOSTSLICE_SRC.is_dir() else [])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return subprocess.run([sys.executable, "-m", "ghostproxy"] + args,
                          env=env, capture_output=True, text=True, timeout=timeout)


@requires_core
def test_doctor_passes_against_fake_upstream_and_spends_nothing(fake_upstream, tmp_path):
    project = make_project(tmp_path)
    proc = _cli(["doctor", "--project", str(project), "--upstream", fake_upstream.url])
    assert proc.returncode == 0, f"doctor failed: {proc.stdout} {proc.stderr}"
    billable = [r for r in fake_upstream.recorded
                if r["method"] == "POST" and "/messages" in r["path"]]
    assert billable == [], "doctor must never make a billable messages call by default"


@requires_core
def test_doctor_flags_a_bad_profile(tmp_path):
    project = make_project(tmp_path)
    (project / ".ghostslice.json").write_text('{"proxy": {"port": "not-a-number"}}')
    proc = _cli(["doctor", "--project", str(project)])
    assert proc.returncode != 0, "an invalid profile must fail loudly, per house rules"


@requires_core
def test_ledger_rows_have_bench_shape_and_no_bodies(fake_upstream, tmp_path):
    project = make_project(tmp_path)
    workdir = tmp_path / "work"
    request = messages_request(project_sections(project))
    with ProxyProcess(project, fake_upstream.url, workdir) as proxy:
        status, _ = http_post(proxy.url + "/v1/messages",
                              json.dumps(request).encode(), HEADERS)
        assert status == 200
        time.sleep(0.5)
    ledger_files = list(project.rglob("*.jsonl")) + list(workdir.rglob("*.jsonl"))
    assert ledger_files, "no ledger was written"
    rows = []
    for path in ledger_files:
        for line in path.read_text(errors="replace").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    assert rows, "ledger files exist but hold no rows"
    row = rows[-1]
    for field in ("tokens_in", "tokens_out"):
        assert field in row, f"ledger row is missing {field} (GhostBench consumes this shape)"
    assert "fallback" in row, "ledger row must record whether the fail-open path was used"
    blob = json.dumps(rows)
    assert PROMPT_MARKER not in blob, \
        "request bodies are never in the ledger by default (PLAN hard rule)"
