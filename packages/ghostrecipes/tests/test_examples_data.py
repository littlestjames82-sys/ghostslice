"""Pure-data tests for the starter examples: no CLI needed, so these
pin the example content itself whatever the core does."""
import json
import re

from conftest import EXAMPLES, STARTER_IDS, load_example

EM_DASH = "—"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ALLOWED_KINDS = {"manual", "check", "run", "review", "approve", "note"}


def test_three_starters_exist_and_parse():
    for rid in STARTER_IDS:
        path = EXAMPLES / f"{rid}.recipe.json"
        assert path.is_file(), f"missing starter {rid}"
        data = json.loads(path.read_text())
        assert data["id"] == rid


def test_starters_are_well_formed():
    for rid in STARTER_IDS:
        data = load_example(rid)
        assert SLUG.match(data["id"]), data["id"]
        assert SEMVER.match(str(data["version"])), data["version"]
        assert data.get("name")
        assert data.get("description")
        steps = data["steps"]
        assert len(steps) >= 4, f"{rid} too thin to be a workflow"
        ids = [s["id"] for s in steps]
        assert len(ids) == len(set(ids)), f"{rid} duplicate step ids"
        for step in steps:
            assert step.get("title")
            assert step.get("kind") in ALLOWED_KINDS, step


def test_no_em_dashes_anywhere_in_examples_or_readme():
    # Ryan's rule (Oct 13): no em dashes in copy he will post or send.
    # The creator pitch recipe is exactly that kind of copy, and the
    # rule is cheap to hold for the whole examples tree + README.
    targets = list(EXAMPLES.rglob("*"))
    targets.append(EXAMPLES.parent / "README.md")
    for path in targets:
        if path.is_file():
            assert EM_DASH not in path.read_text(), f"em dash in {path}"


def test_marathon_loop_shape():
    steps = [s["id"] for s in load_example("slice-marathon-loop")["steps"]]
    # build, then audit, then improve twice (two distinct steps), then verify
    assert steps.index("audit-1") > steps.index("build")
    assert steps.index("improve-1") > steps.index("audit-1")
    assert steps.index("improve-2") > steps.index("improve-1")
    assert steps.index("verify") > steps.index("improve-2")
    gates = " ".join(s.get("gate", "") for s in
                     load_example("slice-marathon-loop")["steps"]).lower()
    assert "do not move to the next goal" in gates
    assert "separate approval" in \
        load_example("slice-marathon-loop")["notes"].lower()


def test_audit_improve_verify_shape():
    data = load_example("audit-improve-verify")
    steps = [s["id"] for s in data["steps"]]
    assert steps == ["audit", "improve-1", "improve-2", "verify", "report"]
    text = json.dumps(data).lower()
    assert "two separate changes" in text or "different change" in text


def test_creator_pitch_is_draft_first_and_sends_verbatim():
    data = load_example("creator-pitch-draft-first")
    steps = [s["id"] for s in data["steps"]]
    assert steps.index("approval-gate") < steps.index("send-verbatim")
    gates = " ".join(s.get("gate", "") for s in data["steps"]).lower()
    assert "nothing is sent without approval" in gates
    assert "no em dashes" in gates
    assert steps.index("draft") < steps.index("approval-gate")
