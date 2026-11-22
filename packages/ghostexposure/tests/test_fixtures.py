"""Fixture self-tests. These need no core and must always pass: if a
fixture is wrong, every CLI test built on it is meaningless."""
from __future__ import annotations

import json
from pathlib import Path

from conftest import FAKE_SECRET, FIXTURES
from helpers import inventory


def test_basic_project_shape():
    inv = inventory(FIXTURES / "basic_project")
    assert len(inv) >= 7
    for expected in (
        "auth/login.py",
        "payments/charge.py",
        "app/main.py",
        "app/profile.py",
        "util/format.py",
        "docs/guide.md",
    ):
        assert expected in inv


def test_starter_surface_pack_is_valid_and_reasoned():
    pack = json.loads((FIXTURES / "surfaces" / "starter-surface.json").read_text())
    assert pack["id"] and pack["version"]
    kinds = {p["kind"] for p in pack["patterns"]}
    assert {"glob", "import", "data"} <= kinds
    for pattern in pack["patterns"]:
        assert pattern["id"] and pattern["pattern"] and pattern["reason"], (
            "every surface pattern needs an id, a pattern and a plain-words reason"
        )
    limits = pack["coverage_limits"]
    limits_text = " ".join(limits) if isinstance(limits, list) else limits
    assert "does not detect" in limits_text
    assert pack["date"] and pack["kind"] == "surface"


def test_conflict_fixture_really_conflicts():
    profile = json.loads((FIXTURES / "conflict_project" / ".ghostslice.json").read_text())
    pin_out = profile["exposure"]["pinned_out"]
    assert "auth/session.py" in pin_out
    pack = json.loads((FIXTURES / "surfaces" / "starter-surface.json").read_text())
    globs = [p["pattern"] for p in pack["patterns"] if p["kind"] == "glob"]
    assert "auth/**" in globs, "auth/session.py must also match a surface glob, or there is no conflict"
    assert (FIXTURES / "conflict_project" / "auth" / "session.py").exists()


def test_planted_key_fixture_has_exactly_one_fake_secret():
    src = (FIXTURES / "planted_key_project" / "config" / "secrets_config.py").read_text()
    assert src.count(FAKE_SECRET) == 1
    assert "not, and has never been, a real credential" in src


def test_no_real_project_files_in_fixtures():
    # Fixtures are invented. Guard against someone pasting real code in.
    for p in FIXTURES.rglob("*.py"):
        text = p.read_text()
        assert "ghostslice" not in text.lower() or "fixture" in text.lower()
