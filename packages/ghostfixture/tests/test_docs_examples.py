"""Docs and examples contract tests. Always run, no core needed.

Pins the documentation promises the rest of the suite leans on:
the README states the plain-words trust rules and the honest
limits, the examples walkthrough exists with its demo project
and demo bundle, and no document prepared for Ryan carries an
em dash.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

ROOT = helpers.REPO_ROOT
EM_DASH = "—"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_readme_states_the_trust_rules_and_limits():
    text = _read(ROOT / "README.md")
    lowered = text.lower()
    for anchor in ("never modified", "excluded by default",
                   "size cap", "check", "import closure",
                   "honest limits", "not guaranteed to run",
                   "secret-free"):
        assert anchor in lowered, anchor


def test_no_em_dashes_in_docs():
    for doc in (ROOT / "README.md", ROOT / "examples" / "README.md"):
        assert EM_DASH not in _read(doc), doc


def test_examples_walkthrough_contents_exist():
    examples = ROOT / "examples"
    assert (examples / "README.md").is_file()
    assert (examples / "make_demo_bundle.py").is_file()
    project = examples / "demo_project" / "demo"
    for name in ("pricing.py", "rates.py", "keys.py", "scratch.py"):
        assert (project / name).is_file(), name
    bundle = examples / "demo_bundle"
    manifest = json.loads(_read(bundle / "manifest.json"))
    paths = [f["path"] for f in manifest["files"]]
    assert paths == ["demo/pricing.py", "demo/keys.py"]
    assert (bundle / "PROMPT.md").is_file()
    assert (bundle / "files" / "demo" / "pricing.py").is_file()


def test_examples_closure_premise_holds():
    pricing = _read(ROOT / "examples" / "demo_project" / "demo"
                    / "pricing.py")
    assert "from demo.rates import" in pricing
    walkthrough = _read(ROOT / "examples" / "README.md")
    assert "ghostfixture build" in walkthrough
    assert "ghostfixture check" in walkthrough
