"""Ingest / list / show behaviour, including refusal of bad input."""
from conftest import (FIXTURES, ingest, ingest_example, list_requests,
                      load_example, out_text, parse_json_maybe,
                      queue_text, show_request, status_of)


def test_ingest_makes_request_pending_never_approved(tmp_path):
    from conftest import history_events, make_queue
    queue = make_queue(tmp_path)
    _, req_id, _ = ingest_example(queue, "ghostbridge-request.json")
    assert status_of(queue, req_id) == "pending"
    # No decision may exist yet: ingest records exactly one event,
    # the `ingested` event. Nothing is approved by ingest itself.
    events = history_events(queue)
    assert [e.get("event") for e in events] == ["ingested"]
    assert events[0].get("id") == req_id


def test_list_shows_pending_with_hash_and_risk(tmp_path):
    from conftest import make_queue
    queue = make_queue(tmp_path)
    _, req_id, req_hash = ingest_example(queue, "seatbelt-request.json")
    proc = list_requests(queue)
    assert proc.returncode == 0, out_text(proc)
    text = out_text(proc)
    assert req_id in text
    assert req_hash in text.lower(), "list must show the hash"
    assert "high" in text.lower(), "list must show the risk level"


def test_show_displays_hash_risk_source_and_action(tmp_path):
    from conftest import make_queue
    queue = make_queue(tmp_path)
    _, req_id, req_hash = ingest_example(queue, "ghostdeploy-request.json")
    proc = show_request(queue, req_id)
    assert proc.returncode == 0, out_text(proc)
    text = out_text(proc)
    low = text.lower()
    assert req_hash in low
    assert "high" in low and "ghostdeploy" in low
    _, data = load_example("ghostdeploy-request.json")
    assert data["action"] in text or "deploy" in low


def test_list_pending_filter_excludes_decided(tmp_path):
    from conftest import decide, make_queue
    queue = make_queue(tmp_path)
    _, keep_id, _ = ingest_example(queue, "ghostbridge-request.json")
    _, done_id, done_hash = ingest_example(
        queue, "ghostguard-request.json")
    proc = decide(queue, "deny", done_id, done_hash)
    assert proc.returncode == 0, out_text(proc)
    pending = list_requests(queue, status="pending")
    text = out_text(pending)
    assert keep_id in text
    assert done_id not in text


def test_ingest_rejects_invalid_json(tmp_path):
    from conftest import make_queue
    queue = make_queue(tmp_path)
    proc = ingest(queue, FIXTURES / "not-json-request.json")
    assert proc.returncode != 0, "invalid JSON must be refused"
    assert "req-broken-001" not in queue_text(queue)


def test_ingest_rejects_missing_fields(tmp_path):
    from conftest import make_queue
    queue = make_queue(tmp_path)
    proc = ingest(queue, FIXTURES / "missing-fields-request.json")
    assert proc.returncode != 0, (
        "a request without source/risk/action must be refused, not "
        "queued half-formed")


def test_ingest_same_id_twice_is_refused_not_duplicated(tmp_path):
    from conftest import make_queue
    queue = make_queue(tmp_path)
    path, data = load_example("ghostbridge-request.json")
    first = ingest(queue, path)
    assert first.returncode == 0, out_text(first)
    second = ingest(queue, path)
    assert second.returncode != 0, (
        "re-using an existing request id must be refused (PLAN: no "
        "silent de-duplication, no silent overwrite)")
    assert status_of(queue, data["id"]) == "pending"
    records = list((queue / "requests").glob("*.json"))
    assert len(records) == 1, "exactly one record file may exist"


def test_show_unknown_id_fails_cleanly(tmp_path):
    from conftest import make_queue
    queue = make_queue(tmp_path)
    proc = show_request(queue, "req-does-not-exist-999")
    assert proc.returncode != 0
    assert "traceback" not in out_text(proc).lower()
