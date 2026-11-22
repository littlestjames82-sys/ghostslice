"""Shared fixtures: fake engine executables and a mini project.

The unit tests never touch the real engines. They write small fake
``ghostslice`` / ``ghostverify`` / ``ghostbench`` / ``ghostconsole``
scripts into a temp bin dir on PATH; the fakes emit canned reports
whose behavior is steered by FAKE_* environment variables. Every
test also passes an empty --engine-home so the sibling-checkout
fallback cannot reach the real engines in the workspace.
"""

from __future__ import annotations

import os
import stat

import pytest

FAKE_SLICE = '''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
if argv and argv[0] == "--version":
    print("ghostslice 9.9.9"); raise SystemExit(0)
project = argv[1]
out = argv[argv.index("-o") + 1]
if os.environ.get("FAKE_SLICE_FAIL"):
    print("fake slice boom", file=sys.stderr); raise SystemExit(3)
os.makedirs(out, exist_ok=True)
manifest = {"tool": "ghostslice", "version": "9.9.9", "files": [],
            "total_original_tokens": 100, "total_sliced_tokens": 40}
with open(os.path.join(out, "manifest.json"), "w") as fh:
    json.dump(manifest, fh)
with open(os.path.join(project, ".ghostslice-history.jsonl"), "a") as fh:
    fh.write("{}\\n")
print("bundle written")
'''

FAKE_VERIFY = '''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
if argv and argv[0] == "--version":
    print("ghostverify 9.9.9"); raise SystemExit(0)
project, bundle = argv[1], argv[2]
out_dir = argv[argv.index("--out-dir") + 1] if "--out-dir" in argv else bundle
verdict = os.environ.get("FAKE_VERIFY_VERDICT", "sufficient")
code = {"sufficient": 0, "gaps_found": 1, "could_not_verify": 2}[verdict]
if not os.environ.get("FAKE_VERIFY_NOREPORT"):
    os.makedirs(out_dir, exist_ok=True)
    report = {"tool": "ghostverify", "version": "9.9.9",
              "verdict": verdict, "exit_code": code,
              "project": project, "bundle": bundle,
              "gaps": [{"symbol": "missing_thing"}] if verdict == "gaps_found" else []}
    with open(os.path.join(out_dir, "verify-report.json"), "w") as fh:
        json.dump(report, fh)
raise SystemExit(code)
'''

FAKE_BENCH = '''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
if argv and argv[0] in ("version", "--version"):
    print("ghostbench 9.9.9"); raise SystemExit(0)
if argv and argv[0] == "add":
    corpus = argv[1]
    project = argv[argv.index("--project") + 1]
    pid = argv[argv.index("--id") + 1]
    if os.environ.get("FAKE_BENCH_FAIL"):
        print("fake bench boom", file=sys.stderr); raise SystemExit(4)
    data = {"name": "fake", "version": "1", "projects": []}
    if os.path.isfile(corpus):
        data = json.load(open(corpus))
    entry = {"id": pid, "path": project, "tasks": []}
    if not os.environ.get("FAKE_BENCH_NOTREE"):
        entry["tree_hash"] = "sha256:fake-tree-hash"
    data.setdefault("projects", []).append(entry)
    parent = os.path.dirname(corpus)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(corpus, "w") as fh:
        json.dump(data, fh, indent=2)
    raise SystemExit(0)
if argv and argv[0] == "run":
    out = argv[argv.index("--out") + 1]
    if os.environ.get("FAKE_BENCH_FAIL"):
        print("fake bench boom", file=sys.stderr); raise SystemExit(4)
    level = "tests-executed" if "--run-tests" in argv else "static-analysis"
    failing = int(os.environ.get("FAKE_BENCH_FAILING", "0"))
    tree = None if os.environ.get("FAKE_BENCH_NOTREE") else "sha256:fake-tree-hash"
    report = {"tool": "ghostbench", "tool_version": "9.9.9",
              "verification_level": level, "provenance": "live",
              "totals": {"tasks_failed": failing, "tasks": 1},
              "tasks": [{"id": "wf-001-starter-task",
                         "status": "fail" if failing else "pass",
                         "project_tree_hash": tree,
                         "project_commit": None,
                         "verification_level": level}]}
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "bench-report.json"), "w") as fh:
        json.dump(report, fh, indent=2)
    with open(os.path.join(out, "BENCH.md"), "w") as fh:
        fh.write("# fake bench\\n")
    raise SystemExit(0)
raise SystemExit(2)
'''

FAKE_CONSOLE = '''#!/usr/bin/env python3
import os, sys
argv = sys.argv[1:]
if argv and argv[0] == "--version":
    print("ghostconsole 9.9.9"); raise SystemExit(0)
if argv and argv[0] == "build":
    if os.environ.get("FAKE_CONSOLE_FAIL"):
        print("fake console boom", file=sys.stderr); raise SystemExit(5)
    out = argv[argv.index("-o") + 1]
    with open(out, "w") as fh:
        fh.write("<html><body>fake board</body></html>")
    raise SystemExit(0)
raise SystemExit(2)
'''

FAKES = {
    "ghostslice": FAKE_SLICE,
    "ghostverify": FAKE_VERIFY,
    "ghostbench": FAKE_BENCH,
    "ghostconsole": FAKE_CONSOLE,
}


def write_fakes(bin_dir, names):
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        target = bin_dir / name
        target.write_text(FAKES[name], encoding="utf-8")
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
                     | stat.S_IXOTH)
    return bin_dir


@pytest.fixture
def make_fake_bin(tmp_path):
    """Factory: make_fake_bin([names]) -> bin dir with those fakes."""
    counter = {"n": 0}

    def _make(names):
        counter["n"] += 1
        return write_fakes(tmp_path / f"fakebin{counter['n']}", names)

    return _make


@pytest.fixture
def fake_env(monkeypatch, make_fake_bin):
    """PATH with all four fake engines; returns the bin dir."""
    bin_dir = make_fake_bin(list(FAKES))
    monkeypatch.setenv(
        "PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.delenv("GHOSTWORKFLOW_ENGINE_HOME", raising=False)
    return bin_dir


@pytest.fixture
def empty_home(tmp_path):
    """An engine home with no engine checkouts in it."""
    home = tmp_path / "no-engines"
    home.mkdir(exist_ok=True)
    return home


@pytest.fixture
def project(tmp_path):
    """A minimal real project directory."""
    proj = tmp_path / "mini"
    proj.mkdir()
    (proj / "calc.py").write_text(
        '"""Tiny calculator module."""\n\n\n'
        "def add(a, b):\n    return a + b\n\n\n"
        "def subtract(a, b):\n    return a - b\n",
        encoding="utf-8")
    (proj / "test_calc.py").write_text(
        "from calc import add\n\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8")
    return proj


def find_workflow_report(project):
    """The single workflow-report.json a run wrote under a project."""
    matches = sorted(
        (project / ".ghostworkflow").glob("*/workflow-report.json"))
    assert len(matches) == 1, f"expected one workflow report, got {matches}"
    return matches[0]
