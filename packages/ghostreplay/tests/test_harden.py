"""Hardening tests (improvement wave, harden lane).

Each test proves a specific fix for a bug found by auditing the
untrusted-input paths: transcripts, bundle manifests, proposal
files, canonical sessions, and the ledger are all data a user may
receive from elsewhere, so malformed/hostile values must fail
loudly or degrade safely -- never crash with a bare KeyError /
TypeError, silently miscount, or write outside the chosen dir.
"""
import json
from pathlib import Path

import pytest

from conftest import BUNDLE, SESSIONS, run_cli

from ghostreplay import secrets
from ghostreplay.analysis import _symbol_outline, analyse_session
from ghostreplay.bundle import BundleError, load_manifest
from ghostreplay.cli import _safe_session_component
from ghostreplay.ledger import read_records, trend_summary
from ghostreplay.profile import REPLAY_DEFAULTS
from ghostreplay.propose import build_proposal, load_proposal
from ghostreplay.transcript import (TranscriptError, load_session,
                                    parse_transcript)


# 1. Duplicate sessions must not satisfy the min-sessions gate.
def test_duplicate_session_does_not_satisfy_min_sessions():
    bundle = load_manifest(BUNDLE)
    session = parse_transcript(SESSIONS / "planted_waste_1.jsonl")
    report = analyse_session(session, bundle,
                             SESSIONS.parent / "project")
    proposal = build_proposal("p", [report, report, report], [],
                              dict(REPLAY_DEFAULTS), {}, [])
    assert proposal["sessions_analysed"] == 1
    assert proposal["status"] == "insufficient-sessions"
    assert proposal["changes"] == []


def test_distinct_sessions_still_reach_ready():
    bundle = load_manifest(BUNDLE)
    reports = []
    for name in ("planted_waste_1.jsonl", "planted_waste_2.jsonl",
                 "planted_waste_3.jsonl"):
        session = parse_transcript(SESSIONS / name)
        reports.append(analyse_session(session, bundle,
                                       SESSIONS.parent / "project"))
    proposal = build_proposal("p", reports, [],
                              dict(REPLAY_DEFAULTS), {}, [])
    assert proposal["sessions_analysed"] == 3
    assert proposal["status"] == "ready"


# 2. sessionId path traversal via ingest / analyse output paths.
def test_safe_session_component_has_no_separator():
    for hostile in ("../../evil", "..\\..\\evil", "/abs/path", ".."):
        safe = _safe_session_component(hostile)
        assert "/" not in safe and "\\" not in safe
        assert safe not in ("", ".", "..")
        assert not safe.startswith(".")


def test_ingest_with_traversal_session_id_stays_in_out_dir(
        tmp_path, require_core, project_copy):
    transcript = tmp_path / "evil.jsonl"
    transcript.write_text(json.dumps({
        "type": "user", "sessionId": "../../evil",
        "message": {"role": "user", "content": "hello"},
    }) + "\n", encoding="utf-8")
    res = run_cli(["ingest", project_copy, transcript], cwd=tmp_path)
    assert res.returncode == 0, f"ingest failed: {res.stdout}\n{res.stderr}"
    # Nothing escaped: neither tmp_path nor the project root gained
    # an evil.json, and a file WAS written inside .ghostreplay/.
    assert not (tmp_path / "evil.json").exists()
    assert not (project_copy / "evil.json").exists()
    written = list((project_copy / ".ghostreplay").glob("*.json"))
    assert written, "ingest wrote no canonical session inside .ghostreplay"


# 3. sanitize_obj must sanitize dict keys, not only values.
def test_sanitize_obj_sanitizes_dict_keys():
    secret = "AKIA" + "IOSFODNN7EXAMPLE"
    out = secrets.sanitize_obj({secret: "x", "nested": {secret: 1}})
    blob = json.dumps(out)
    assert secret not in blob
    assert "[REDACTED:aws-access-key]" in blob


# 4. A file merely claiming the canonical format fails loudly.
def test_canonical_session_missing_fields_fails_loudly(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"format": "ghostreplay-session/1"}),
                   encoding="utf-8")
    with pytest.raises(TranscriptError):
        load_session(bad)
    bad2 = tmp_path / "bad2.json"
    bad2.write_text(json.dumps({
        "format": "ghostreplay-session/1", "session_id": "s",
        "turns": [{"no_turn_number": True}],
    }), encoding="utf-8")
    with pytest.raises(TranscriptError):
        load_session(bad2)


# 5. Bundle manifest: bad token counts / string symbols are loud.
def test_bundle_rejects_non_numeric_and_bool_token_counts(tmp_path):
    for bad_value in ("notanint", True, 1.5):
        (tmp_path / "manifest.json").write_text(json.dumps({
            "files": [{"path": "a.py", "sliced_tokens": bad_value}],
        }), encoding="utf-8")
        with pytest.raises(BundleError):
            load_manifest(tmp_path)


def test_bundle_rejects_string_symbols_included(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({
        "files": [{"path": "a.py", "symbols_included": "abcd"}],
    }), encoding="utf-8")
    with pytest.raises(BundleError):
        load_manifest(tmp_path)


# 6. Ledger trend must survive corrupt / hand-edited records.
def test_trend_summary_tolerates_non_numeric_values():
    summary = trend_summary([
        {"session_id": "s", "ts": "2026-01-01",
         "estimated_waste_percent": "lots",
         "estimated_waste_tokens": None,
         "reread_waste_estimated_tokens": True},
    ])
    assert summary["sessions"] == 1
    assert summary["mean_waste_percent"] == 0.0
    assert summary["total_estimated_waste_tokens"] == 0


def test_read_records_survives_invalid_utf8(tmp_path):
    ledger = tmp_path / ".ghostreplay-history.jsonl"
    good = json.dumps({"session_id": "ok"}).encode()
    ledger.write_bytes(b"\xff\xfe not json\n" + good + b"\n")
    records = read_records(tmp_path)
    assert [r["session_id"] for r in records] == ["ok"]


# 7. JSON true/false in usage must not count as reported tokens.
def test_bool_usage_is_not_counted_as_reported_tokens(tmp_path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({
        "type": "assistant", "sessionId": "s1",
        "message": {"role": "assistant", "content": "hi",
                    "usage": {"input_tokens": True,
                              "output_tokens": False}},
    }) + "\n", encoding="utf-8")
    session = parse_transcript(transcript)
    assert session["reported_input_tokens"] == 0
    assert session["reported_output_tokens"] == 0


# 8. Bundle paths must not read files outside the project tree.
def test_symbol_outline_refuses_path_outside_project(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "inside.py").write_text("def inside_fn():\n    pass\n",
                                       encoding="utf-8")
    (tmp_path / "outside.py").write_text(
        "def outside_fn():\n    pass\n", encoding="utf-8")
    assert _symbol_outline(project, "inside.py") == ["inside_fn"]
    assert _symbol_outline(project, "../outside.py") == []
    assert _symbol_outline(project, str(tmp_path / "outside.py")) == []


# 9. load_proposal validates the shape apply relies on.
def test_load_proposal_rejects_ready_proposal_without_changes(tmp_path):
    bad = tmp_path / "p.json"
    bad.write_text(json.dumps({
        "format": "ghostreplay-proposal/1", "status": "ready",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="changes"):
        load_proposal(bad)
    bad.write_text(json.dumps({
        "format": "ghostreplay-proposal/1", "status": "ready",
        "changes": [{"kind": "mode", "target": "a.py"}],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="changes"):
        load_proposal(bad)
