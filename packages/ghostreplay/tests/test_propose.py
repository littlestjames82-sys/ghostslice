"""Propose contract tests (PLAN: propose-only, >=3 sessions, evidence).

- 3 planted-waste sessions -> a proposal that cites src/legacy.py with
  per-change evidence (counts, not bare recommendations);
- 3 zero-waste sessions -> an EMPTY diff (a tool that always finds
  savings is inventing them);
- a single session -> no proposal; the tool explains the >=3 threshold.
"""
import json
from pathlib import Path

from conftest import NEVER, BUNDLE, SESSIONS, run_cli


def propose(tmp_path, project_copy, session_names):
    out = tmp_path / "prop"
    args = ["propose", project_copy] + [SESSIONS / n for n in session_names] + \
           ["--bundle", BUNDLE, "--out", out]
    res = run_cli(args, cwd=tmp_path)
    return res, out


def load_changes(out_dir):
    diff = Path(out_dir) / "ghostreplay-proposal.json"
    assert diff.is_file(), f"ghostreplay-proposal.json not written to {out_dir}"
    data = json.loads(diff.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("changes", [])
    assert isinstance(data, list)
    return data


def test_propose_from_planted_waste_cites_legacy_with_evidence(tmp_path, require_core, project_copy):
    res, out = propose(tmp_path, project_copy, ["planted_waste_1.jsonl", "planted_waste_2.jsonl",
                                  "planted_waste_3.jsonl"])
    assert res.returncode == 0, f"propose failed: {res.stdout}\n{res.stderr}"
    changes = load_changes(out)
    hits = [c for c in changes if NEVER in json.dumps(c)]
    assert hits, f"proposal does not cite {NEVER}: {changes}"
    blob = json.dumps(hits)
    # Evidence per change: session counts must be cited, e.g. 3 sessions / 0 refs.
    assert "3" in blob and "0" in blob, (
        f"proposal change for {NEVER} carries no count evidence: {hits}"
    )


def test_propose_from_zero_waste_is_an_empty_diff(tmp_path, require_core, project_copy):
    res, out = propose(tmp_path, project_copy, ["zero_waste_1.jsonl", "zero_waste_2.jsonl",
                                  "zero_waste_3.jsonl"])
    assert res.returncode == 0, f"propose failed: {res.stdout}\n{res.stderr}"
    changes = load_changes(out)
    assert changes == [], (
        f"zero-waste sessions must propose an EMPTY diff, got: {changes}"
    )


def test_propose_refuses_a_single_session_and_says_why(tmp_path, require_core, project_copy):
    res, out = propose(tmp_path, project_copy, ["planted_waste_1.jsonl"])
    combined = (res.stdout + res.stderr).lower()
    assert "3" in combined and ("session" in combined), (
        "single-session propose must explain the >=3-session threshold; "
        f"got stdout={res.stdout!r} stderr={res.stderr!r}"
    )
    diff = Path(out) / "ghostreplay-proposal.json"
    if diff.is_file():
        changes = json.loads(diff.read_text(encoding="utf-8"))
        changes = changes.get("changes", []) if isinstance(changes, dict) else changes
        assert changes == [], "single-session propose emitted changes anyway"
