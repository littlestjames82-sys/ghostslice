"""Polish round (Oct 14, 2026) regression tests.

Every test here pins a defect that was first DEMONSTRATED against the
v0.1 core (see POLISH.md for the audit trail), then fixed:

  * a record file swapped wholesale for a different, internally
    consistent request could be approved against a hash that was
    never ingested under that id (the ingested ledger event's hash
    was never compared)
  * a record whose inner id disagrees with its file name was trusted
  * ingest succeeded against a torn (crash-truncated) ledger, merged
    the new event onto the partial line, and left an orphan record
  * a record file with invalid UTF-8, or a JSON array instead of an
    object, crashed list/show with a traceback
Plus the pass-2 clarity work (age in list/show, history tolerant of a
null hash) and the standing proof that no flag or environment
variable added or imagined can create a decision.
"""
import json
import os
import sys
from pathlib import Path

from conftest import (REPO, decide, history, history_events, ingest_example,
                      ledger_text, list_requests, make_queue, out_text,
                      run_ga, show_request, status_of)


def _record_path(queue, req_id):
    return Path(queue) / "requests" / f"{req_id}.json"


def test_wholesale_record_replacement_refuses_decision(tmp_path):
    """Replace req A's record with req B's content+hash (inner id
    edited to A's, so the file is internally consistent). Approving A
    with B's hash must refuse: that hash was never ingested for A."""
    queue = make_queue(tmp_path)
    _, a_id, _ = ingest_example(queue, "ghostbridge-request.json")
    _, b_id, b_hash = ingest_example(queue, "ghostguard-request.json")
    b_record = json.loads(_record_path(queue, b_id).read_text())
    b_record["id"] = a_id
    _record_path(queue, a_id).write_text(json.dumps(b_record, indent=2))
    proc = decide(queue, "approve", a_id, b_hash)
    assert proc.returncode != 0, (
        "a swapped record must not be decidable against a hash that "
        "was never ingested under this id")
    assert status_of(queue, a_id) == "pending"
    events = history_events(queue)
    assert [e.get("event") for e in events] == ["ingested", "ingested"]


def test_record_inner_id_mismatch_fails_cleanly(tmp_path):
    queue = make_queue(tmp_path)
    _, req_id, req_hash = ingest_example(queue, "ghostbridge-request.json")
    record = json.loads(_record_path(queue, req_id).read_text())
    record["id"] = "req-someone-else"
    _record_path(queue, req_id).write_text(json.dumps(record, indent=2))
    show = show_request(queue, req_id)
    assert show.returncode != 0
    assert "traceback" not in out_text(show).lower()
    proc = decide(queue, "approve", req_id, req_hash)
    assert proc.returncode != 0
    assert "traceback" not in out_text(proc).lower()


def test_ingest_refuses_on_torn_ledger_and_writes_nothing(tmp_path):
    """Simulate a crash mid-append (partial line, no newline). The
    next ingest must fail closed: ledger byte-identical, no orphan
    record file. After the operator removes the torn fragment, the
    store works again."""
    queue = make_queue(tmp_path)
    ingest_example(queue, "ghostbridge-request.json")
    ledger = Path(queue) / "ledger.jsonl"
    good_bytes = ledger.read_bytes()
    with open(ledger, "a", encoding="utf-8") as fh:
        fh.write('{"event": "ingested", "id": "req-torn", "ha')
    torn_bytes = ledger.read_bytes()
    records_before = sorted(p.name for p in (Path(queue) / "requests").glob("*"))

    proc = run_ga(queue, ["ingest",
                          str(REPO / "examples" / "ghostguard-request.json")])
    assert proc.returncode != 0, "ingest on a corrupt ledger must refuse"
    assert "traceback" not in out_text(proc).lower()
    assert ledger.read_bytes() == torn_bytes, "ledger must be untouched"
    assert sorted(p.name for p in (Path(queue) / "requests").glob("*")) \
        == records_before, "no orphan record may be written"

    ledger.write_bytes(good_bytes)  # operator repair of the torn tail
    proc = run_ga(queue, ["ingest",
                          str(REPO / "examples" / "ghostguard-request.json")])
    assert proc.returncode == 0, out_text(proc)


def test_append_ledger_never_merges_onto_torn_line(tmp_path):
    """Unit-level pin for the torn-tail guard in the one place ledger
    bytes are written: a new event is always its own line."""
    sys.path.insert(0, str(REPO / "src"))
    from ghostapprove.store import Store
    store = Store(tmp_path / "store")
    store._append_ledger({"event": "ingested", "id": "req-1", "hash": "a" * 64})
    with open(store.ledger_path, "a", encoding="utf-8") as fh:
        fh.write('{"event": "ingested", "id": "req-2", "ha')  # torn
    store._append_ledger({"event": "ingested", "id": "req-3", "hash": "b" * 64})
    lines = store.ledger_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["id"] == "req-1"
    assert json.loads(lines[2])["id"] == "req-3"


def test_invalid_utf8_record_fails_cleanly(tmp_path):
    queue = make_queue(tmp_path)
    _, req_id, req_hash = ingest_example(queue, "ghostbridge-request.json")
    _record_path(queue, req_id).write_bytes(b'{"id": 1, \xff\xfe}')
    show = show_request(queue, req_id)
    assert show.returncode != 0
    assert "traceback" not in out_text(show).lower()
    proc = decide(queue, "approve", req_id, req_hash)
    assert proc.returncode != 0
    assert "traceback" not in out_text(proc).lower()


def test_non_object_record_fails_cleanly_in_list_and_show(tmp_path):
    queue = make_queue(tmp_path)
    _, req_id, _ = ingest_example(queue, "ghostbridge-request.json")
    _record_path(queue, req_id).write_text('["not", "an", "object"]')
    lst = run_ga(queue, ["list", "--status", "all"])
    assert lst.returncode != 0
    assert "traceback" not in out_text(lst).lower()
    show = show_request(queue, req_id)
    assert show.returncode != 0
    assert "traceback" not in out_text(show).lower()


def test_age_shown_in_list_and_show(tmp_path):
    queue = make_queue(tmp_path)
    _, req_id, _ = ingest_example(queue, "ghostbridge-request.json")
    human_list = run_ga(queue, ["list"])
    assert human_list.returncode == 0, out_text(human_list)
    assert "age=" in out_text(human_list)
    human_show = run_ga(queue, ["show", req_id])
    assert human_show.returncode == 0, out_text(human_show)
    assert "age:" in out_text(human_show)


def test_history_tolerates_null_hash_line(tmp_path):
    queue = make_queue(tmp_path)
    ledger = Path(queue) / "ledger.jsonl"
    ledger.write_text(json.dumps(
        {"event": "noted", "id": "req-x", "hash": None,
         "at": "2026-10-14T00:00:00Z"}) + "\n", encoding="utf-8")
    proc = history(queue)
    assert proc.returncode == 0, out_text(proc)
    assert "traceback" not in out_text(proc).lower()


def test_no_new_flag_or_env_creates_a_decision(tmp_path):
    """The polish round added display-only surface (age). This test
    proves no flag or env var, existing or imagined, can decide:
    bypass-style flags are rejected, suggestive env vars are ignored,
    and the request stays pending with only its ingested event."""
    queue = make_queue(tmp_path)
    _, req_id, req_hash = ingest_example(queue, "ghostbridge-request.json")
    for flag in ("--force", "--skip-hash", "--auto", "--approve-all"):
        proc = run_ga(queue, ["approve", req_id, "--hash", req_hash, flag])
        assert proc.returncode != 0, f"{flag} must not be accepted"
        assert status_of(queue, req_id) == "pending"

    old = dict(os.environ)
    os.environ["GHOSTAPPROVE_AUTO_DECISION"] = "approve"
    os.environ["GHOSTAPPROVE_DEFAULT_DECISION"] = "approved"
    os.environ["GHOSTAPPROVE_SKIP_HASH"] = "1"
    os.environ["GHOSTAPPROVE_FORCE"] = "1"
    os.environ["GHOSTAPPROVE_DECIDE"] = "approve"
    try:
        list_requests(queue)
        show_request(queue, req_id)
        history(queue)
    finally:
        os.environ.clear()
        os.environ.update(old)
    assert status_of(queue, req_id) == "pending"
    events = history_events(queue)
    assert [e.get("event") for e in events] == ["ingested"]
    assert ledger_text(queue).count("\n") == 1
