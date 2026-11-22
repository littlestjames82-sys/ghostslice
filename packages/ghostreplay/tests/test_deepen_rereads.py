"""Deepen-wave tests: re-read accounting, turn timeline, hotspots.

Covers the deepen change:
- a text mention is a reference, never a re-read (no tokens charged);
- re-reads are charged on distinct tool-input turns only, once per
  file per turn however many times that turn repeats the input;
- the turn timeline's per-turn re-read tokens sum to the report's
  re-read waste total, with the cumulative column ending there too;
- propose aggregates re-reads across sessions into reread_hotspots
  (diagnostic only, never entries in `changes`), and zero-waste
  sessions produce no hotspots.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from ghostreplay.analysis import analyse_session  # noqa: E402

from conftest import BUNDLE, HOT, SESSIONS, load_report, run_cli  # noqa: E402

HOT_TOKENS = 67  # manifest sliced_tokens for src/hot.py (see fixtures)


def _bundle():
    return {
        "root": None, "manifest_path": "m.json", "manifest_sha256": "x",
        "tool_version": "fixture", "total_original_tokens": 100,
        "total_sliced_tokens": 100,
        "by_path": {
            "src/util.py": {
                "path": "src/util.py", "mode": "full", "language": "python",
                "original_tokens": 100, "sliced_tokens": 100,
                "sha256": "", "symbols_included": [],
            },
        },
    }


def _session(turns):
    return {
        "session_id": "unit", "transcript_sha256": "x", "entry_count": 0,
        "turn_count": len(turns), "models": [], "started_at": None,
        "ended_at": None, "reported_input_tokens": 0,
        "reported_output_tokens": 0, "secret_findings": [],
        "turns": turns,
    }


def _turn(n, texts=(), tool_uses=()):
    return {
        "turn": n,
        "texts": [{"role": "assistant", "kind": "text", "text": t,
                   "estimated_tokens": 1} for t in texts],
        "tool_uses": [{"name": name, "file_paths": [p]}
                      for name, p in tool_uses],
        "instruction_blocks": [],
    }


def test_text_mentions_alone_are_references_not_rereads():
    session = _session([
        _turn(1, texts=["we discussed src/util.py here"]),
        _turn(2, texts=["src/util.py again in prose"]),
        _turn(3, texts=["and src/util.py once more"]),
    ])
    report = analyse_session(session, _bundle())
    assert report["rereads"] == []
    assert report["totals"]["reread_waste_estimated_tokens"] == 0
    referenced = {f["path"] for f in report["referenced_files"]}
    assert "src/util.py" in referenced
    assert all(row["reread_estimated_tokens"] == 0
               for row in report["turn_timeline"])


def test_rereads_count_tool_input_turns_not_mention_turns():
    session = _session([
        _turn(1, tool_uses=[("Read", "src/util.py")]),
        _turn(2, texts=["src/util.py mentioned, not read"]),
        _turn(3, tool_uses=[("Read", "src/util.py")]),
        _turn(4, tool_uses=[("Read", "src/util.py")]),
    ])
    report = analyse_session(session, _bundle())
    assert len(report["rereads"]) == 1
    entry = report["rereads"][0]
    assert entry["distinct_turns"] == 3
    assert entry["turns"] == [1, 3, 4]
    assert entry["extra_reads"] == 2
    assert entry["estimated_reread_tokens"] == 200
    assert entry["direct_read_turns"] == [1, 3, 4]


def test_repeated_input_within_one_turn_counts_once():
    session = _session([
        _turn(1, tool_uses=[("Read", "src/util.py"),
                            ("Read", "src/util.py")]),
        _turn(2, tool_uses=[("Read", "src/util.py")]),
    ])
    report = analyse_session(session, _bundle())
    entry = report["rereads"][0]
    assert entry["distinct_turns"] == 2
    assert entry["extra_reads"] == 1
    timeline = {row["turn"]: row for row in report["turn_timeline"]}
    assert timeline[1]["reread_estimated_tokens"] == 0
    assert timeline[2]["reread_estimated_tokens"] == 100
    assert timeline[2]["cumulative_reread_estimated_tokens"] == 100


def test_timeline_reconciles_with_totals_on_planted_fixture(
        tmp_path, require_core, project_copy):
    out = tmp_path / "out"
    res = run_cli(["analyse", project_copy, SESSIONS / "planted_waste_1.jsonl",
                   "--bundle", BUNDLE, "--out", out], cwd=tmp_path)
    assert res.returncode == 0, f"{res.stdout}\n{res.stderr}"
    report = load_report(out)
    timeline = report["turn_timeline"]
    assert [row["turn"] for row in timeline] == \
        list(range(1, report["turn_count"] + 1))
    total = report["totals"]["reread_waste_estimated_tokens"]
    assert sum(row["reread_estimated_tokens"] for row in timeline) == total
    assert timeline[-1]["cumulative_reread_estimated_tokens"] == total
    # hot.py is Read in turns 1-5, so it is a re-read from turn 2 on.
    reread_turns = [row["turn"] for row in timeline
                    if HOT in row["reread_files"]]
    assert reread_turns == [2, 3, 4, 5]
    md = (out / "REPLAY.md").read_text(encoding="utf-8")
    assert "## Turn timeline" in md
    assert HOT in md


def _propose(tmp_path, project_copy, names):
    out = tmp_path / "prop"
    res = run_cli(["propose", project_copy]
                  + [SESSIONS / n for n in names]
                  + ["--bundle", BUNDLE, "--out", out], cwd=tmp_path)
    assert res.returncode == 0, f"{res.stdout}\n{res.stderr}"
    data = json.loads((out / "ghostreplay-proposal.json")
                      .read_text(encoding="utf-8"))
    return data, (out / "PROPOSAL.md").read_text(encoding="utf-8")


def test_propose_hotspots_aggregate_planted_rereads(
        tmp_path, require_core, project_copy):
    data, md = _propose(tmp_path, project_copy,
                        ["planted_waste_1.jsonl", "planted_waste_2.jsonl",
                         "planted_waste_3.jsonl"])
    hotspots = data["reread_hotspots"]
    hits = [h for h in hotspots if h["target"] == HOT]
    assert hits, f"no hotspot for {HOT}: {hotspots}"
    hit = hits[0]
    # 5 Read turns per session -> 4 extra reads; 3 sessions.
    assert hit["sessions_with_rereads"] == 3
    assert hit["total_extra_reads"] == 12
    assert hit["total_estimated_reread_tokens"] == 12 * HOT_TOKENS
    assert hit["max_distinct_turns_in_one_session"] == 5
    assert "3" in hit["evidence"] and "12" in hit["evidence"]
    # Hotspots are diagnostic only: they never appear as changes.
    assert all(c.get("kind") != "reread_hotspot"
               for c in data["changes"])
    assert "## Re-read hotspots" in md and HOT in md


def test_propose_zero_waste_has_no_hotspots(
        tmp_path, require_core, project_copy):
    data, md = _propose(tmp_path, project_copy,
                        ["zero_waste_1.jsonl", "zero_waste_2.jsonl",
                         "zero_waste_3.jsonl"])
    assert data["reread_hotspots"] == []
    assert data["changes"] == []
