"""Whole-store integrity audit: `verify` (alias `audit`).

Before this, GhostApprove's hash checks ran only at decision time for
the single id being decided. A tampered record for a request nobody
tried to decide yet, an orphan ledger event, or a second decision
forged by hand was invisible until (or unless) that id came up.

`verify` applies the same checks to the entire store, read-only:
every record recomputes to its stored hash, every record has exactly
one matching ``ingested`` event, every decision names a recorded and
ingested request with the exact hash and is the only decision for
its id, and the ledger itself is readable. It writes nothing, decides
nothing, and creates nothing for a store that does not exist.
"""
import json
import sys
from pathlib import Path

from conftest import (REPO, decide, ingest_example, make_queue, out_text,
                      parse_json_maybe, run_ga)

sys.path.insert(0, str(REPO / "src"))
from ghostapprove.store import Store  # noqa: E402

REQ = {"source": "seatbelt", "action": "run a consequential action",
       "summary": "verify test request", "risk": "high"}


def _store(tmp_path):
    return Store(tmp_path / "store")


def _ingest(store, req_id, **overrides):
    raw = dict(REQ, id=req_id, **overrides)
    return store.ingest(raw)


def _snapshot(root):
    root = Path(root)
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _checks(report):
    return {(p["id"], p["check"]) for p in report["problems"]}


# ------------------------------------------------------------- clean store

def test_verify_clean_store_with_all_statuses(tmp_path):
    store = _store(tmp_path)
    a = _ingest(store, "req-a")
    b = _ingest(store, "req-b")
    _ingest(store, "req-c")
    store.decide("req-a", "approved", a["hash"], by="ryan")
    store.decide("req-b", "denied", b["hash"], by="ryan")
    report = store.verify()
    assert report["ok"] is True
    assert report["problems"] == []
    assert report["checked"] == {"records": 3, "ledger_events": 5,
                                  "pending": 1, "approved": 1,
                                  "denied": 1}


def test_verify_empty_and_missing_store_creates_nothing(tmp_path):
    root = tmp_path / "no-such-store"
    report = Store(root).verify()
    assert report["ok"] is True
    assert report["checked"]["records"] == 0
    assert report["checked"]["ledger_events"] == 0
    assert not root.exists(), "verify is read-only: no store may appear"


def test_verify_is_read_only_on_a_clean_store(tmp_path):
    store = _store(tmp_path)
    a = _ingest(store, "req-a")
    store.decide("req-a", "approved", a["hash"], by="ryan")
    before = _snapshot(store.root)
    store.verify()
    store.verify()
    assert _snapshot(store.root) == before


# ------------------------------------------------------------- tampering

def test_verify_detects_edited_record_content(tmp_path):
    store = _store(tmp_path)
    entry = _ingest(store, "req-a")
    path = store.requests_dir / "req-a.json"
    record = json.loads(path.read_text())
    record["content"]["summary"] = "quietly rewritten after review"
    path.write_text(json.dumps(record, indent=2))
    before = _snapshot(store.root)
    report = store.verify()
    assert report["ok"] is False
    assert ("req-a", "content-hash") in _checks(report)
    # Finding the problem changed nothing and decided nothing.
    assert _snapshot(store.root) == before
    assert store.status_of("req-a")["status"] == "pending"
    assert entry["hash"] in path.read_text()  # stored hash untouched


def test_verify_detects_wholesale_record_replacement(tmp_path):
    """Internally consistent replacement (content + hash swapped) is
    caught by the ingested-event hash, same as at decision time."""
    store = _store(tmp_path)
    _ingest(store, "req-a")
    b = _ingest(store, "req-b", summary="a different request entirely")
    assert b["hash"]
    b_record = json.loads((store.requests_dir / "req-b.json").read_text())
    b_record["id"] = "req-a"
    (store.requests_dir / "req-a.json").write_text(json.dumps(b_record))
    report = store.verify()
    assert report["ok"] is False
    assert ("req-a", "ingested-hash") in _checks(report)
    assert ("req-a", "content-hash") not in _checks(report)


def test_verify_detects_malformed_record_and_still_audits_the_rest(tmp_path):
    store = _store(tmp_path)
    _ingest(store, "req-a")
    _ingest(store, "req-b")
    (store.requests_dir / "req-b.json").write_text('["not", "an", "object"]')
    report = store.verify()
    assert report["ok"] is False
    assert ("req-b", "record-parse") in _checks(report)
    assert ("req-a", "content-hash") not in _checks(report)
    assert report["checked"]["records"] == 1


def test_verify_reports_corrupt_ledger_instead_of_raising(tmp_path):
    store = _store(tmp_path)
    _ingest(store, "req-a")
    with open(store.ledger_path, "a", encoding="utf-8") as fh:
        fh.write('{"event": "ingested", "id": "req-torn", "ha')
    before = _snapshot(store.root)
    report = store.verify()  # must not raise StoreError past the audit
    assert report["ok"] is False
    assert (None, "ledger-readable") in _checks(report)
    assert _snapshot(store.root) == before


# ------------------------------------------------------------- ledger shape

def test_verify_detects_record_without_ingested_event(tmp_path):
    store = _store(tmp_path)
    _ingest(store, "req-a")
    # Operator damage: drop the ingested event, keep the record.
    store.ledger_path.write_text("", encoding="utf-8")
    report = store.verify()
    assert report["ok"] is False
    assert ("req-a", "ingested-event") in _checks(report)


def test_verify_detects_orphan_ingested_event(tmp_path):
    store = _store(tmp_path)
    _ingest(store, "req-a")
    store._append_ledger({"event": "ingested", "id": "req-ghost",
                          "hash": "a" * 64, "at": "2026-10-18T00:00:00Z"})
    report = store.verify()
    assert ("req-ghost", "orphan-ingested-event") in _checks(report)


def test_verify_detects_orphan_and_uningested_decisions(tmp_path):
    store = _store(tmp_path)
    a = _ingest(store, "req-a")
    # Decision for an id with no record at all.
    store._append_ledger({"event": "approved", "id": "req-ghost",
                          "hash": "b" * 64, "by": "mallory",
                          "executed": False, "at": "2026-10-18T00:00:00Z"})
    # Second decision for req-a forged by hand (decide() would refuse).
    store.decide("req-a", "approved", a["hash"], by="ryan")
    store._append_ledger({"event": "denied", "id": "req-a",
                          "hash": a["hash"], "by": "mallory",
                          "executed": False, "at": "2026-10-18T00:01:00Z"})
    report = store.verify()
    assert ("req-ghost", "orphan-decision-event") in _checks(report)
    assert ("req-a", "duplicate-decision") in _checks(report)
    # The audit recorded no decision of its own.
    assert store.status_of("req-a")["decision"]["by"] == "ryan"


def test_verify_detects_decision_with_wrong_hash(tmp_path):
    store = _store(tmp_path)
    _ingest(store, "req-a")
    store._append_ledger({"event": "approved", "id": "req-a",
                          "hash": "c" * 64, "by": "mallory",
                          "executed": False, "at": "2026-10-18T00:00:00Z"})
    report = store.verify()
    assert ("req-a", "decision-hash") in _checks(report)


def test_verify_detects_decision_without_ingest(tmp_path):
    store = _store(tmp_path)
    entry = _ingest(store, "req-a")
    # Keep the record and a correctly-hashed decision, lose only the
    # ingested event: record-before-decision was not honoured.
    kept = [ln for ln in store.ledger_path.read_text().splitlines()
            if '"ingested"' not in ln]
    store.ledger_path.write_text("\n".join(kept) + "\n")
    store._append_ledger({"event": "approved", "id": "req-a",
                          "hash": entry["hash"], "by": "ryan",
                          "executed": False, "at": "2026-10-18T00:00:00Z"})
    checks = _checks(store.verify())
    assert ("req-a", "ingested-event") in checks
    assert ("req-a", "decision-without-ingest") in checks


# ------------------------------------------------------------- CLI surface

def test_cli_verify_clean_store_exit_0_and_json(tmp_path):
    queue = make_queue(tmp_path)
    _, req_id, req_hash = ingest_example(queue, "ghostbridge-request.json")
    decide(queue, "approve", req_id, req_hash)
    human = run_ga(queue, ["verify"])
    assert human.returncode == 0, out_text(human)
    assert "verify: OK" in out_text(human)
    as_json = run_ga(queue, ["verify", "--json"])
    assert as_json.returncode == 0, out_text(as_json)
    parsed = parse_json_maybe(as_json.stdout)
    assert parsed["ok"] is True
    assert parsed["checked"]["approved"] == 1


def test_cli_verify_tampered_store_exit_1_and_alias(tmp_path):
    queue = make_queue(tmp_path)
    _, req_id, _ = ingest_example(queue, "ghostbridge-request.json")
    path = Path(queue) / "requests" / f"{req_id}.json"
    record = json.loads(path.read_text())
    record["content"]["action"] = "rewritten after review"
    path.write_text(json.dumps(record, indent=2))
    proc = run_ga(queue, ["verify"])
    assert proc.returncode == 1, out_text(proc)
    assert "FAILED" in out_text(proc)
    assert "content-hash" in out_text(proc)
    alias = run_ga(queue, ["audit", "--json"])
    assert alias.returncode == 1, out_text(alias)
    parsed = parse_json_maybe(alias.stdout)
    assert parsed["ok"] is False
    assert any(p["check"] == "content-hash" for p in parsed["problems"])
