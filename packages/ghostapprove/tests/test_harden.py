"""Hardening round (Oct 18, 2026) regression tests.

Every test pins a defect first demonstrated against the v0.1 core:

  * a request file that is not valid UTF-8 crashed ingest with a
    UnicodeDecodeError traceback (it is a ValueError, not the OSError
    the ingest path caught)
  * a damaged ledger line carrying a list as its ``id`` crashed
    list / show / decide with ``TypeError: unhashable type``
  * a ledger path that is a directory (or a store path that is a
    file) leaked a raw OSError traceback instead of exit 2
  * a payload containing NaN / Infinity was accepted and written
    into a record file as non-standard JSON other tools cannot read
  * a pathologically nested request file raised RecursionError as a
    traceback instead of a clean exit 2

These run in-process (cli.main / Store) so they stay fast; the
behavioural subprocess suite already covers the CLI end to end.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ghostapprove import cli  # noqa: E402
from ghostapprove.model import RequestError  # noqa: E402
from ghostapprove.store import Store, StoreError  # noqa: E402


def _ingest_ok(store_dir, req_id="req-1"):
    store = Store(store_dir)
    return store.ingest({"action": "do a thing", "summary": "because",
                         "id": req_id})


def test_ingest_invalid_utf8_request_file_exits_2_cleanly(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_bytes(b'{"action": "x", \xff}')
    rc = cli.main(["--store", str(tmp_path / "s"), "ingest", str(bad)])
    assert rc == 2
    assert "traceback" not in capsys.readouterr().err.lower()


def test_ledger_line_with_unhashable_id_fails_closed(tmp_path, capsys):
    store_dir = tmp_path / "s"
    _ingest_ok(store_dir)
    store = Store(store_dir)
    with open(store.ledger_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "approved", "id": ["evil"],
                             "hash": "x" * 64}) + "\n")
    with pytest.raises(StoreError):
        store.list_requests(status="all")
    rc = cli.main(["--store", str(store_dir), "list", "--status", "all"])
    assert rc == 2
    assert "traceback" not in capsys.readouterr().err.lower()
    # Defensive path: events handed straight to status_of (bypassing
    # read_ledger validation) must not crash on an unhashable id.
    assert store.status_of(
        "req-1", events=[{"event": "approved", "id": ["evil"]}]) == \
        {"status": "pending", "decision": None}


def test_ledger_as_directory_fails_cleanly(tmp_path, capsys):
    store_dir = tmp_path / "s"
    store_dir.mkdir()
    (store_dir / "ledger.jsonl").mkdir()
    with pytest.raises(StoreError):
        Store(store_dir).read_ledger()
    rc = cli.main(["--store", str(store_dir), "history"])
    assert rc == 2
    assert "traceback" not in capsys.readouterr().err.lower()


def test_store_path_that_is_a_file_fails_cleanly(tmp_path, capsys):
    blocker = tmp_path / "afile"
    blocker.write_text("not a directory")
    req = tmp_path / "ok.json"
    req.write_text('{"action": "a", "summary": "b"}')
    rc = cli.main(["--store", str(blocker), "ingest", str(req)])
    assert rc == 2
    assert "traceback" not in capsys.readouterr().err.lower()


def test_nonfinite_payload_is_rejected_and_writes_no_record(tmp_path):
    for token in ("NaN", "Infinity", "-Infinity",
                  '{"x": Infinity}', "[1, NaN]"):
        req = tmp_path / "nan.json"
        req.write_text('{"action": "a", "summary": "b", '
                       '"id": "req-nan", "payload": ' + token + "}")
        rc = cli.main(["--store", str(tmp_path / "s"), "ingest", str(req)])
        assert rc == 2, f"payload {token} must be refused"
    requests_dir = tmp_path / "s" / "requests"
    assert not requests_dir.exists() or not list(requests_dir.glob("*"))
    # Direct API callers get the same refusal, as a RequestError.
    with pytest.raises(RequestError):
        Store(tmp_path / "s2").ingest(
            {"action": "a", "summary": "b",
             "payload": {"v": float("inf")}})


def test_deeply_nested_request_file_exits_2_cleanly(tmp_path, capsys):
    deep = tmp_path / "deep.json"
    deep.write_text('{"action": "a", "summary": "b", "payload": '
                    + "[" * 5000 + "]" * 5000 + "}")
    rc = cli.main(["--store", str(tmp_path / "s"), "ingest", str(deep)])
    assert rc == 2
    assert "traceback" not in capsys.readouterr().err.lower()
    requests_dir = tmp_path / "s" / "requests"
    assert not requests_dir.exists() or not list(requests_dir.glob("*.json"))
