"""Standalone tests: docs, examples, and suite assumptions.

These run even when Agent A's core has not landed yet, and pin the
contract the README and examples promise.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_documents_all_four_commands():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for command in ("create", "list", "status", "cleanup"):
        assert command in readme


def test_readme_states_the_dirty_cleanup_rule():
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "dirty" in readme
    assert "force" in readme


def test_readme_states_local_only_and_stdlib():
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "stdlib" in readme or "standard library" in readme
    assert "local" in readme


def test_examples_exist_and_demo_covers_the_lifecycle():
    examples = ROOT / "examples"
    assert (examples / "README.md").exists()
    demo = examples / "demo.sh"
    assert demo.exists()
    text = demo.read_text(encoding="utf-8")
    for step in ("create", "list", "status", "cleanup"):
        assert step in text


def test_sample_state_file_is_valid_and_complete():
    sample = ROOT / "examples" / "sample-state.json"
    assert sample.exists()
    data = json.loads(sample.read_text(encoding="utf-8"))
    text = json.dumps(data).lower()
    # Whatever exact schema the core uses, a worktree record needs at
    # least a name/task, a path, and a port to be useful.
    assert "port" in text
    assert "path" in text or "worktree" in text
    assert "task" in text or "name" in text


def test_no_test_uses_the_network():
    # The suite is local-only by gate: guard against regressions.
    from tests import helpers
    source = Path(helpers.__file__).read_text(encoding="utf-8")
    for banned in ("urllib.request", "requests.", "socket.create_connection",
                   "http.client"):
        assert banned not in source
