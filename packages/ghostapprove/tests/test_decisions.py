"""Decisions: approve, deny, and the adversarial cases.

Adversarial coverage required by the task:
  * tampered / mismatched hash refuses (argument tamper AND stored
    payload tamper)
  * double decision refuses (approve-after-approve, deny-after-approve,
    approve-after-deny)
  * deny path records a denial and never an approval
Plus the v0.1 scope guards: no hash = no decision, no auto-approval,
and approving NEVER executes the queued action.
"""
from pathlib import Path

from conftest import (EXAMPLES, decide, history, ingest, ingest_example,
                      load_example, make_queue, out_text, queue_text,
                      status_of)


def test_approve_happy_path_records_decision(tmp_path):
    queue = make_queue(tmp_path)
    _, req_id, req_hash = ingest_example(queue, "ghostbridge-request.json")
    proc = decide(queue, "approve", req_id, req_hash, note="ok to post")
    assert proc.returncode == 0, out_text(proc)
    assert status_of(queue, req_id) in ("approved", "approve")
    hist = history(queue)
    assert "approve" in out_text(hist).lower()
    assert req_id in out_text(hist)


def test_deny_path_records_denial_not_approval(tmp_path):
    queue = make_queue(tmp_path)
    _, req_id, req_hash = ingest_example(queue, "seatbelt-request.json")
    proc = decide(queue, "deny", req_id, req_hash, note="too risky")
    assert proc.returncode == 0, out_text(proc)
    status = status_of(queue, req_id)
    assert status in ("denied", "rejected", "deny")
    hist_text = out_text(history(queue)).lower()
    assert req_id in hist_text and ("den" in hist_text or "reject" in hist_text)


def test_tampered_hash_argument_refuses_and_stays_pending(tmp_path):
    queue = make_queue(tmp_path)
    _, req_id, req_hash = ingest_example(queue, "ghostdeploy-request.json")
    bogus = ("0" if req_hash[0] != "0" else "1") + req_hash[1:]
    assert bogus != req_hash
    for verb in ("approve", "deny"):
        proc = decide(queue, verb, req_id, bogus)
        assert proc.returncode != 0, (
            f"{verb} with a tampered hash must refuse")
        assert status_of(queue, req_id) == "pending", (
            f"{verb} with a tampered hash must record no decision")
    # The real hash still works afterwards: refusal is not a lockout.
    proc = decide(queue, "approve", req_id, req_hash)
    assert proc.returncode == 0, out_text(proc)


def test_tampered_stored_payload_refuses_decision(tmp_path):
    """Edit the queued record after ingest; the original hash must
    no longer authorise a decision (decision time recomputes the hash
    from the stored canonical content - PLAN tamper test)."""
    queue = make_queue(tmp_path)
    _, req_id, req_hash = ingest_example(queue, "ghostbridge-request.json")
    record = queue / "requests" / f"{req_id}.json"
    assert record.is_file(), "expected a per-request record file"
    text = record.read_text()
    _, data = load_example("ghostbridge-request.json")
    marker = data["summary"][:20]
    assert marker in text
    record.write_text(text.replace(marker, "CHANGED SUMMARY!", 1))
    proc = decide(queue, "approve", req_id, req_hash)
    assert proc.returncode != 0, (
        "deciding a request whose stored record was tampered with "
        "must refuse: the recomputed hash no longer matches")
    assert status_of(queue, req_id) == "pending"


def test_ingested_tampered_hash_field_is_not_trusted(tmp_path):
    from conftest import FIXTURES
    queue = make_queue(tmp_path)
    proc = ingest(queue, FIXTURES / "tampered-hash-request.json")
    if proc.returncode == 0:
        # Core ignored the supplied hash and computed its own: the
        # stored/shown hash must not be the bogus all-zero value.
        from conftest import show_request, get_hash, parse_json_maybe
        show = show_request(queue, "req-tampered-001")
        parsed = parse_json_maybe(show.stdout)
        shown = get_hash(parsed if parsed is not None else show.stdout,
                         "req-tampered-001")
        assert shown != "0" * 64
    # else: ingest refused the tampered hash outright - also correct.


def test_double_decision_refuses_in_all_orders(tmp_path):
    queue = make_queue(tmp_path)
    _, a_id, a_hash = ingest_example(queue, "ghostbridge-request.json")
    _, b_id, b_hash = ingest_example(queue, "ghostguard-request.json")
    assert decide(queue, "approve", a_id, a_hash).returncode == 0
    assert decide(queue, "approve", a_id, a_hash).returncode != 0, \
        "approve after approve must refuse"
    assert decide(queue, "deny", a_id, a_hash).returncode != 0, \
        "deny after approve must refuse"
    assert status_of(queue, a_id) in ("approved", "approve")

    assert decide(queue, "deny", b_id, b_hash).returncode == 0
    assert decide(queue, "approve", b_id, b_hash).returncode != 0, \
        "approve after deny must refuse"
    assert decide(queue, "deny", b_id, b_hash).returncode != 0, \
        "deny after deny must refuse"
    assert status_of(queue, b_id) in ("denied", "rejected", "deny")


def test_decision_without_hash_refuses(tmp_path):
    queue = make_queue(tmp_path)
    _, req_id, _ = ingest_example(queue, "ghostbridge-request.json")
    proc = decide(queue, "approve", req_id, None)
    assert proc.returncode != 0, (
        "a decision with no hash must refuse: the hash is the proof "
        "the decider saw this exact request")
    assert status_of(queue, req_id) == "pending"


def test_decision_for_unknown_id_refuses(tmp_path):
    queue = make_queue(tmp_path)
    proc = decide(queue, "approve", "req-nope-999", "a" * 64)
    assert proc.returncode != 0
    assert "traceback" not in out_text(proc).lower()


def test_approval_never_executes_the_action(tmp_path):
    """Queue only in v0.1: the seatbelt example names a side-effect
    file in its details; approving must NOT create it (or run anything).
    """
    queue = make_queue(tmp_path)
    _, req_id, req_hash = ingest_example(queue, "seatbelt-request.json")
    sentinel = EXAMPLES / "SHOULD_NOT_EXIST_seatbelt.txt"
    repo_sentinel = Path(__file__).resolve().parents[1] / \
        "examples" / "SHOULD_NOT_EXIST_seatbelt.txt"
    assert not sentinel.exists() and not repo_sentinel.exists()
    proc = decide(queue, "approve", req_id, req_hash)
    assert proc.returncode == 0, out_text(proc)
    assert not sentinel.exists() and not repo_sentinel.exists(), (
        "approving created a side-effect file: GhostApprove must "
        "record decisions only, never execute actions in v0.1")
    assert not list(tmp_path.rglob("SHOULD_NOT_EXIST*"))


def test_no_auto_approval_after_time_or_listing(tmp_path):
    """Listing/showing/history repeatedly must never flip a status:
    there is no auto-approval path of any kind."""
    from conftest import list_requests, show_request
    queue = make_queue(tmp_path)
    _, req_id, _ = ingest_example(queue, "ghostdeploy-request.json")
    for _ in range(3):
        list_requests(queue)
        show_request(queue, req_id)
        history(queue)
    assert status_of(queue, req_id) == "pending"
