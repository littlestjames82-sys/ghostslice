"""Fixture/example sanity: passes with NO core present.

These guard the Agent B artefacts themselves (examples + adversarial
fixtures): valid JSON where claimed, the fields the queue contract
needs, all four upstream sources represented, a spread of risk levels,
and no real secret-shaped values anywhere.
"""
import json
import re
from pathlib import Path

from conftest import EXAMPLES, FIXTURES

SECRET_SHAPES = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
]
REQUIRED = ("id", "source", "risk", "action", "summary")


def example_files():
    return sorted(EXAMPLES.glob("*-request.json"))


def test_examples_exist_for_all_four_sources():
    assert len(example_files()) >= 4
    sources = set()
    for p in example_files():
        sources.add(json.loads(p.read_text())["source"])
    assert {"seatbelt", "ghostguard", "ghostdeploy", "ghostbridge"} <= sources


def test_examples_have_required_fields_and_valid_risk():
    for p in example_files():
        data = json.loads(p.read_text())
        for field in REQUIRED:
            assert data.get(field), f"{p.name}: missing/empty {field}"
        assert data["risk"] in ("low", "medium", "high", "critical"), p.name
        assert data["id"].startswith("req-"), p.name


def test_examples_cover_a_risk_spread():
    risks = {json.loads(p.read_text())["risk"] for p in example_files()}
    assert "high" in risks and "low" in risks


def test_examples_ids_are_unique():
    ids = [json.loads(p.read_text())["id"] for p in example_files()]
    assert len(ids) == len(set(ids))


def test_no_secret_shapes_in_examples_or_fixtures():
    for folder in (EXAMPLES, FIXTURES):
        for p in Path(folder).rglob("*"):
            if p.is_file():
                text = p.read_text(errors="replace")
                for shape in SECRET_SHAPES:
                    assert not shape.search(text), (
                        f"{p}: secret-shaped value must never be planted")


def test_adversarial_fixtures_are_what_they_claim():
    tampered = json.loads(
        (FIXTURES / "tampered-hash-request.json").read_text())
    assert tampered["hash"] == "0" * 64
    missing = json.loads(
        (FIXTURES / "missing-fields-request.json").read_text())
    assert "source" not in missing and "risk" not in missing
    broken = (FIXTURES / "not-json-request.json").read_text()
    try:
        json.loads(broken)
        raise AssertionError("not-json fixture unexpectedly parses")
    except json.JSONDecodeError:
        pass
