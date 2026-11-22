"""README and examples tests. No core needed: these guard the plan's
documentation rules (written for BOTH sender and receiver, evidence
language, no assurance language)."""
from __future__ import annotations

import json

from conftest import ROOT


def test_readme_speaks_to_both_sides():
    readme = (ROOT / "README.md").read_text()
    low = readme.lower()
    assert "for senders" in low
    assert "for receivers" in low
    assert "ghostexposure verify" in low, "receivers need the verify command up front"
    assert "ghostexposure export" in low


def test_readme_uses_evidence_language_not_assurance_language():
    readme = (ROOT / "README.md").read_text()
    low = readme.lower()
    # The disclaimer must be present in these words or close to them.
    assert "does not certify" in low
    assert "not a security audit" in low or "not an audit" in low
    # Assurance words may only appear inside that disclaimer, never as a
    # capability claim. The disclaimer sentence above is the one place
    # "certif" appears in the README.
    assert low.count("certif") <= 2


def test_readme_states_the_redaction_default():
    low = (ROOT / "README.md").read_text().lower()
    assert "redact" in low
    assert "by default" in low


def test_example_surface_pack_is_valid():
    pack = json.loads((ROOT / "examples" / "starter-surface.example.json").read_text())
    assert pack["id"] and pack["version"]
    for pattern in pack["patterns"]:
        assert pattern["id"] and pattern["reason"]


def test_example_mini_project_exists():
    mini = ROOT / "examples" / "mini_project"
    assert (mini / "auth" / "login.py").exists()
    assert (mini / "util" / "format.py").exists()
