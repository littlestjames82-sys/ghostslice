"""Unresolved-contradiction detection (deepen lane).

Two ACTIVE decisions that say opposite things about the same topic,
with no Supersedes link between them, must be flagged as a conflict
- never silently served as compatible, and never resolved by
dropping one. Detection is deterministic: shared content terms plus
a negation flip or an opposite-directive pair, over the decision
line only (reasons mention rejected options legitimately).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostrecall.conflicts import detect_contradictions
from ghostrecall.model import Item, Provenance
from ghostrecall.recall import select

from conftest import bundle_all_text, bundle_prompt, load_manifest, run_bundle, run_cli


def _decision(id_, title, decision, text=None, status="active",
              source_type="decision"):
    it = Item(id=id_, title=title, text=text if text is not None else decision,
              source_type=source_type,
              provenance=Provenance(path="DECISIONS.md", line=1, date="2026-01-01"),
              status=status)
    it.decision_text = decision
    return it


USE_SQLITE = "Use SQLite for all local storage in the widget service."
NEVER_SQLITE = "Never use SQLite for local storage in the widget service."


def test_negation_flip_between_active_decisions_is_flagged():
    out = detect_contradictions([
        _decision("d1", "D-001", USE_SQLITE),
        _decision("d2", "D-002", NEVER_SQLITE),
    ])
    assert len(out) == 1
    c = out[0]
    assert c["type"] == "possible-contradiction"
    assert c["signal"] == "negation"
    assert c["items"] == ["d1", "d2"]
    assert "sqlite" in c["opposing_terms"]
    assert "storage" in c["shared_terms"]


def test_opposite_directive_pair_is_flagged():
    out = detect_contradictions([
        _decision("d1", "D-001", "Open the signup gate for new trial users."),
        _decision("d2", "D-002", "Close the signup gate for new trial users."),
    ])
    assert len(out) == 1
    assert out[0]["signal"] == "opposite-directives"
    assert set(out[0]["opposing_terms"]) == {"open", "close"}


def test_agreeing_decisions_are_not_flagged():
    out = detect_contradictions([
        _decision("d1", "D-001", USE_SQLITE),
        _decision("d2", "D-002",
                  "Use SQLite for local storage backups in the widget service."),
    ])
    assert out == []


def test_negated_but_unrelated_decisions_are_not_flagged():
    out = detect_contradictions([
        _decision("d1", "D-001", USE_SQLITE),
        _decision("d2", "D-002",
                  "Never rename a public command once it has shipped."),
    ])
    assert out == []


def test_one_shared_term_is_not_enough():
    out = detect_contradictions([
        _decision("d1", "D-001", "Use SQLite for storage."),
        _decision("d2", "D-002", "Never store passwords in SQLite backups."),
    ])
    assert out == []


def test_superseded_and_non_decision_items_are_not_flagged():
    old = _decision("d1", "D-001", USE_SQLITE, status="superseded")
    new = _decision("d2", "D-002", NEVER_SQLITE)
    note = _decision("n1", "note", NEVER_SQLITE, source_type="note")
    assert detect_contradictions([old, new]) == []
    assert detect_contradictions([new, note]) == []


def test_rejected_option_mentioned_in_a_reason_is_not_flagged():
    """Reasons routinely name the option that lost. Detection reads
    the decision line only, so this pair (which agrees) is clean."""
    a = _decision(
        "d1", "D-001", USE_SQLITE,
        text=USE_SQLITE + "\nReason: Never use Postgres here; it was rejected.")
    b = _decision(
        "d2", "D-002", "Use SQLite for local storage backups in the widget service.",
        text="Use SQLite for local storage backups.\nReason: Postgres was rejected.")
    assert detect_contradictions([a, b]) == []


def test_select_flags_contradiction_and_keeps_both_decisions():
    items = [_decision("d1", "D-001", USE_SQLITE),
             _decision("d2", "D-002", NEVER_SQLITE)]
    selected, _not, conflicts = select(items, "SQLite local storage", {})
    assert {e["item"].id for e in selected} == {"d1", "d2"}, (
        "a contradiction must be flagged, not resolved by dropping one side")
    assert [c["type"] for c in conflicts] == ["possible-contradiction"]


def _contradiction_project(tmp_path):
    proj = tmp_path / "contra_project"
    proj.mkdir()
    (proj / "DECISIONS.md").write_text(
        "# Decisions\n\n"
        "## D-001 (2026-01-10)\n"
        f"Decision: {USE_SQLITE}\n"
        "Reason: Zero-config, single file.\nSupersedes: none\n"
        "Status: current\nTags: storage\n\n"
        "## D-002 (2026-02-10)\n"
        f"Decision: {NEVER_SQLITE} Use flat files instead.\n"
        "Reason: A sync bug corrupted the database file.\n"
        "Supersedes: none\nStatus: current\nTags: storage\n",
        encoding="utf-8")
    return proj


def test_bundle_manifest_flags_contradiction_and_exports_both(tmp_path):
    proj = _contradiction_project(tmp_path)
    out = tmp_path / "bundle"
    r = run_bundle(proj, out, "SQLite local storage")
    assert r.returncode == 0, r.stdout + r.stderr
    data = load_manifest(out)
    contra = [c for c in data.get("conflicts", [])
              if c.get("type") == "possible-contradiction"]
    assert len(contra) == 1, data.get("conflicts")
    assert set(contra[0]["items"]) == {
        "decision-d-001-2026-01-10", "decision-d-002-2026-02-10"}
    assert "sqlite" in contra[0]["opposing_terms"]
    prompt = bundle_prompt(out)
    assert USE_SQLITE in prompt and NEVER_SQLITE in prompt, (
        "both sides must stay in the bundle; the flag is the fix")
    assert "possible-contradiction" in bundle_all_text(out)
    r2 = run_cli("check", out)
    assert r2.returncode == 0, r2.stdout + r2.stderr


def test_recall_json_surfaces_contradiction(tmp_path):
    proj = _contradiction_project(tmp_path)
    r = run_cli("recall", proj, "--task", "SQLite local storage", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(r.stdout)
    assert [c["type"] for c in data["conflicts"]] == ["possible-contradiction"]
    assert len(data["selected"]) >= 2
