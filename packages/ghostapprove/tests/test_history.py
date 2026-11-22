"""History: append-only, ordered, and decision-complete.

Per Agent A's PLAN: the ledger records facts (ingested / approved /
denied), refused attempts are NOT written to the ledger, and a decision
is an appended event - never an edit to the request record.
"""
from conftest import (decide, history_events, ingest_example, ledger_text,
                      make_queue)


def test_history_records_ingest_and_decision_with_same_hash(tmp_path):
    queue = make_queue(tmp_path)
    _, req_id, req_hash = ingest_example(queue, "ghostbridge-request.json")
    decide(queue, "approve", req_id, req_hash, note="ship it")
    events = history_events(queue)
    assert [e.get("event") for e in events] == ["ingested", "approved"]
    assert all(e.get("id") == req_id for e in events)
    # Record-before-decision, hash-bound: the decision event carries
    # the same exact hash as the earlier ingested event.
    assert events[0].get("hash") == req_hash
    assert events[1].get("hash") == req_hash
    # A recorded decision is not an execution.
    assert events[1].get("executed") is False


def test_history_is_append_only_ledger_never_rewritten(tmp_path):
    queue = make_queue(tmp_path)
    _, first_id, first_hash = ingest_example(
        queue, "ghostbridge-request.json")
    decide(queue, "approve", first_id, first_hash)
    ledger_before = ledger_text(queue)
    assert ledger_before

    _, second_id, second_hash = ingest_example(
        queue, "ghostguard-request.json")
    decide(queue, "deny", second_id, second_hash)
    ledger_after = ledger_text(queue)

    # Pure append: the earlier ledger bytes are an exact prefix of the
    # later ledger. Nothing was edited, reordered, or truncated.
    assert ledger_after.startswith(ledger_before)
    assert len(ledger_after) > len(ledger_before)
    events = history_events(queue)
    assert [e.get("event") for e in events] == [
        "ingested", "approved", "ingested", "denied"]


def test_history_preserves_order_across_multiple_requests(tmp_path):
    queue = make_queue(tmp_path)
    _, a_id, a_hash = ingest_example(queue, "ghostbridge-request.json")
    _, b_id, b_hash = ingest_example(queue, "ghostguard-request.json")
    decide(queue, "approve", a_id, a_hash)
    decide(queue, "deny", b_id, b_hash)
    events = history_events(queue)
    sequence = [(e.get("event"), e.get("id")) for e in events]
    assert sequence == [
        ("ingested", a_id), ("ingested", b_id),
        ("approved", a_id), ("denied", b_id)]


def test_refused_decisions_append_nothing_to_ledger(tmp_path):
    queue = make_queue(tmp_path)
    _, req_id, _ = ingest_example(queue, "ghostdeploy-request.json")
    before = ledger_text(queue)
    proc = decide(queue, "approve", req_id, "f" * 64)
    assert proc.returncode != 0
    assert ledger_text(queue) == before, (
        "a refused decision must append nothing: the ledger records "
        "facts, not attempts (PLAN section 4)")
    events = history_events(queue)
    assert [e.get("event") for e in events] == ["ingested"]


def test_decided_record_file_is_never_modified(tmp_path):
    queue = make_queue(tmp_path)
    _, req_id, req_hash = ingest_example(queue, "ghostbridge-request.json")
    record = queue / "requests" / f"{req_id}.json"
    before = record.read_text()
    decide(queue, "approve", req_id, req_hash)
    assert record.read_text() == before, (
        "a decision is a ledger event only; the request record file "
        "must not be edited")
