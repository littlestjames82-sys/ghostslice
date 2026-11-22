"""Local store for GhostApprove: request records + append-only ledger.

Layout under the store directory:

    requests/<id>.json   one immutable record per request
    ledger.jsonl         append-only events, one JSON object per line

Invariants enforced here:

- Record-before-decision: ingest writes the record AND appends the
  ``ingested`` ledger event before returning. Nothing can be decided
  that has no ``ingested`` event.
- Append-only ledger: code here only ever opens the ledger in append
  mode. No command edits, truncates, or deletes ledger lines or
  request records.
- Hash at decision time: a decision recomputes the hash from the
  stored canonical content and requires stored == recomputed ==
  supplied, and the request still pending, or it refuses and appends
  nothing.
- No execution, no auto-approval: this module records decisions only.
  There is deliberately no executor, no approval rule, and no code
  path that writes a decision event except :meth:`Store.decide`,
  which a human CLI command calls explicitly with an exact hash.
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .model import (RequestError, content_hash, normalise_request,
                    validate_id)


class StoreError(Exception):
    """Store / IO problem; CLI maps it to exit 2."""


class RefusedError(Exception):
    """A decision was refused; CLI maps it to exit 1, nothing appended."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z")


class Store:
    """One approval store on disk: a directory holding a ``requests``
    folder of immutable record files and an append-only
    ``ledger.jsonl``. All reads and writes for the queue go through
    this class; constructing it touches nothing on disk."""

    def __init__(self, root) -> None:
        self.root = Path(root)
        self.requests_dir = self.root / "requests"
        self.ledger_path = self.root / "ledger.jsonl"

    # -- low level ----------------------------------------------------

    def _ensure(self) -> None:
        """Create the store layout on first write (reads never do)."""
        try:
            self.requests_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StoreError(
                f"cannot create store directory {self.requests_dir}: "
                f"{exc}") from exc

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        """Best-effort fsync of a directory so a rename / new file in
        it survives a crash. Ignored where the platform refuses."""
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    def _append_ledger(self, event: dict) -> None:
        """The ONLY way the ledger is ever written: append one line."""
        self._ensure()
        line = json.dumps(event, sort_keys=True, ensure_ascii=False)
        try:
            existed = self.ledger_path.exists()
            with open(self.ledger_path, "a", encoding="utf-8") as fh:
                # Torn-tail guard: if a crash left a partial final line
                # (no trailing newline), terminate it first so the new
                # event is its own line and never merges into the torn
                # fragment. The fragment stays corrupt on purpose: reads
                # keep failing closed until an operator repairs it.
                if existed and self.ledger_path.stat().st_size > 0:
                    with open(self.ledger_path, "rb") as tail:
                        tail.seek(-1, os.SEEK_END)
                        if tail.read(1) != b"\n":
                            fh.write("\n")
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            raise StoreError(
                f"cannot append to ledger {self.ledger_path}: {exc}"
            ) from exc
        if not existed:
            self._fsync_dir(self.root)

    def read_ledger(self) -> list[dict]:
        """Return every ledger event in append order.

        A missing ledger simply means an empty store. A ledger that
        cannot be read back exactly (invalid UTF-8, a corrupt line, a
        line that is not a JSON object) raises StoreError: history is
        never guessed at and damaged lines are never skipped."""
        if not self.ledger_path.exists():
            return []
        events = []
        try:
            lines = self.ledger_path.read_text(
                encoding="utf-8", errors="strict").splitlines()
        except UnicodeDecodeError as exc:
            raise StoreError(
                f"ledger is not valid UTF-8 ({exc}); refusing rather "
                "than guessing history") from exc
        except OSError as exc:
            raise StoreError(
                f"cannot read ledger {self.ledger_path} ({exc}); "
                "refusing rather than guessing history") from exc
        for i, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except (json.JSONDecodeError, RecursionError) as exc:
                raise StoreError(
                    f"ledger line {i} is corrupt ({exc}); refusing rather "
                    "than guessing history") from exc
            if not isinstance(ev, dict):
                raise StoreError(f"ledger line {i} is not a JSON object")
            # Fields later code trusts must have the shapes ingest
            # writes. A damaged line carrying, say, a list as its id
            # used to crash list / show / decide with a TypeError
            # when the id was hashed into the decisions map; fail
            # closed here instead. A null hash stays tolerated: the
            # history view renders it as empty by design.
            for field in ("id", "event"):
                if field in ev and ev[field] is not None \
                        and not isinstance(ev[field], str):
                    raise StoreError(
                        f"ledger line {i} has a non-string {field!r}; "
                        "refusing rather than guessing history")
            if "hash" in ev and ev["hash"] is not None \
                    and not isinstance(ev["hash"], str):
                raise StoreError(
                    f"ledger line {i} has a non-string 'hash'; "
                    "refusing rather than guessing history")
            events.append(ev)
        return events

    def _record_path(self, req_id: str) -> Path:
        validate_id(req_id)  # raises; path traversal guard
        return self.requests_dir / f"{req_id}.json"

    @staticmethod
    def _parse_record(path: Path, req_id: str) -> dict:
        """Parse and structurally validate one record file.

        A record is only trusted when it is a JSON object whose inner
        id matches the id it was loaded by, whose content is a JSON
        object, and whose hash is a string. Anything else is a store
        error (exit 2), never a traceback and never a silent guess.
        """
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError,
                RecursionError) as exc:
            raise StoreError(f"cannot read request record {req_id}: {exc}") from exc
        if not isinstance(record, dict) or "content" not in record \
                or "hash" not in record:
            raise StoreError(f"request record {req_id} is malformed")
        if record.get("id") != req_id:
            raise StoreError(
                f"request record {req_id} is malformed: inner id "
                f"{record.get('id')!r} does not match its file name")
        if not isinstance(record["content"], dict) \
                or not isinstance(record["hash"], str):
            raise StoreError(f"request record {req_id} is malformed")
        return record

    def load_record(self, req_id: str) -> dict:
        """Load and structurally validate one request record.

        Raises RefusedError when no record exists under ``req_id``
        and StoreError when the record on disk is malformed."""
        path = self._record_path(req_id)
        if not path.exists():
            raise RefusedError(f"no such request: {req_id}")
        return self._parse_record(path, req_id)

    # -- derived state --------------------------------------------------

    def _decisions(self, events: list[dict]) -> dict[str, dict]:
        """id -> decision event (first wins; duplicates are a defect the
        decide path prevents, and any second one is ignored here only
        for display, never created by this code)."""
        out: dict[str, dict] = {}
        for ev in events:
            # Callers may hand in events that never passed through
            # read_ledger validation; skip a malformed id instead of
            # crashing on an unhashable key.
            if not isinstance(ev.get("id"), str):
                continue
            if ev.get("event") in ("approved", "denied") and ev.get("id") not in out:
                out[ev["id"]] = ev
        return out

    def status_of(self, req_id: str, events: list[dict] | None = None) -> dict:
        """Current status of one request, derived from the ledger:
        ``{"status": "pending", "decision": None}`` until a decision
        event exists, then the decision event itself. Status is never
        stored on the record, so it cannot be edited into existence."""
        events = self.read_ledger() if events is None else events
        dec = self._decisions(events).get(req_id)
        if dec is None:
            return {"status": "pending", "decision": None}
        return {"status": dec["event"], "decision": dec}

    def list_requests(self, status: str = "pending",
                      source: str | None = None) -> list[dict]:
        """Queue entries for display, oldest ingested first.

        ``status`` filters by derived status (``pending``,
        ``approved``, ``denied``, or ``all``) and ``source`` by the
        exact producer name. A malformed record anywhere in the
        store raises StoreError rather than being skipped."""
        events = self.read_ledger()
        decisions = self._decisions(events)
        entries = []
        if self.requests_dir.exists():
            for path in sorted(self.requests_dir.glob("*.json")):
                record = self._parse_record(path, path.stem)
                content = record.get("content", {})
                dec = decisions.get(record.get("id"))
                st = dec["event"] if dec else "pending"
                if status != "all" and st != status:
                    continue
                if source and content.get("source") != source:
                    continue
                entries.append(self._entry(record, st, dec))
        # Queue order: oldest ingested first.
        entries.sort(key=lambda e: (e.get("ingested_at") or "", e["id"]))
        return entries

    @staticmethod
    def _entry(record: dict, status: str, decision: dict | None) -> dict:
        content = record.get("content", {})
        return {
            "id": record.get("id"),
            "hash": record.get("hash"),
            "source": content.get("source"),
            "risk": content.get("risk"),
            "action": content.get("action"),
            "summary": content.get("summary"),
            "requested_by": content.get("requested_by"),
            "ingested_at": record.get("ingested_at"),
            "status": status,
            "decision": decision,
            "content": content,
        }

    def get_entry(self, req_id: str) -> dict:
        """One queue entry (record plus derived status and decision),
        in the same shape ``list_requests`` returns."""
        record = self.load_record(req_id)
        st = self.status_of(req_id)
        return self._entry(record, st["status"], st["decision"])

    # -- writes ---------------------------------------------------------

    def ingest(self, raw) -> dict:
        """Normalise, record, and ledger a request. Record first.

        ``raw`` is the parsed JSON document a producer wrote. On
        success the new queue entry is returned with status
        ``pending``. RefusedError is raised for a duplicate id and
        RequestError (from normalisation) for an invalid request; a
        damaged ledger refuses the ingest before anything is written.
        """
        content, requested_id = normalise_request(raw)
        try:
            full = content_hash(content)
        except RecursionError as exc:
            raise RequestError(
                "request content is nested too deeply to hash") from exc
        self._ensure()
        # Fail closed on a damaged ledger BEFORE writing anything: a
        # corrupt history must never gain an orphan record whose
        # ingested event lands in a ledger nobody can read back.
        self.read_ledger()
        if requested_id is not None:
            req_id = requested_id
            if self._record_path(req_id).exists():
                raise RefusedError(
                    f"request id already exists: {req_id}; refusing to "
                    "overwrite an existing record")
        else:
            req_id = f"req-{full[:8]}-{secrets.token_hex(3)}"
            while self._record_path(req_id).exists():
                req_id = f"req-{full[:8]}-{secrets.token_hex(3)}"
        record = {
            "id": req_id,
            "hash": full,
            "ingested_at": _utcnow(),
            "content": content,
        }
        # Record-before-decision: atomic record write first, then the
        # ingested ledger event, before this call returns success.
        # The record bytes are fsynced before the rename and the
        # directory after it, so a crash cannot leave a truncated
        # record standing where a complete one was acknowledged.
        path = self._record_path(req_id)
        tmp = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(record, indent=2, sort_keys=True,
                                    ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except OSError as exc:
            raise StoreError(
                f"cannot write request record {req_id}: {exc}") from exc
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        self._fsync_dir(self.requests_dir)
        self._append_ledger({
            "event": "ingested",
            "id": req_id,
            "hash": full,
            "source": content["source"],
            "risk": content["risk"],
            "at": record["ingested_at"],
        })
        return self._entry(record, "pending", None)

    def decide(self, req_id: str, decision: str, supplied_hash: str,
               by: str = "local-operator", note: str | None = None) -> dict:
        """Record one human decision against the exact hash.

        Refuses (raises RefusedError, appends nothing) when: the id was
        never ingested, the supplied hash differs from the stored hash,
        the recomputed hash differs from the stored hash (record was
        edited after ingest), the ``ingested`` ledger event for this
        id carries a different hash (record was replaced wholesale
        after ingest), or the request is already decided.
        Never executes anything.
        """
        if decision not in ("approved", "denied"):
            raise StoreError(f"invalid decision: {decision!r}")
        record = self.load_record(req_id)  # RefusedError if never ingested
        events = self.read_ledger()
        stored = record["hash"]
        # Record-before-decision: the ingested event must exist AND
        # must carry this record's exact hash. Without the hash check,
        # a record file swapped wholesale for a different (internally
        # consistent) request could be decided against a hash that was
        # never ingested under this id.
        ingested = [ev for ev in events
                    if ev.get("event") == "ingested" and ev.get("id") == req_id]
        if not ingested:
            raise RefusedError(
                f"request {req_id} has no 'ingested' ledger event; "
                "refusing to decide an unrecorded request")
        if any(ev.get("hash") != stored for ev in ingested):
            raise RefusedError(
                f"request {req_id} does not match its 'ingested' ledger "
                "event hash; the record was replaced after ingest, "
                "decision refused, nothing recorded")
        supplied = (supplied_hash or "").strip().lower()
        if supplied != stored.lower():
            raise RefusedError(
                "hash mismatch: supplied --hash does not equal the exact "
                f"hash on record ({stored}); decision refused, nothing recorded")
        try:
            recomputed = content_hash(record["content"])
        except RecursionError as exc:
            raise StoreError(
                f"request record {req_id} is nested too deeply to "
                "verify its hash; refusing rather than guessing") from exc
        if recomputed != stored:
            raise RefusedError(
                "hash mismatch: stored record content no longer hashes to "
                f"the exact hash on record ({stored} != recomputed "
                f"{recomputed}); the record was edited after ingest, "
                "decision refused, nothing recorded")
        existing = self._decisions(events).get(req_id)
        if existing is not None:
            raise RefusedError(
                f"request {req_id} is already {existing['event']}; "
                "a second decision is refused, nothing recorded")
        event = {
            "event": decision,
            "id": req_id,
            "hash": stored,
            "by": by or "local-operator",
            "note": note,
            "executed": False,
            "at": _utcnow(),
        }
        self._append_ledger(event)
        return event

    def history(self, req_id: str | None = None) -> list[dict]:
        """Ledger events in append order, optionally only those for
        one request id. This is the audit view: what was ingested and
        what was decided, with the exact hash on every event."""
        events = self.read_ledger()
        if req_id is not None:
            events = [ev for ev in events if ev.get("id") == req_id]
        return events

    # -- integrity audit (read-only) -----------------------------------

    def verify(self) -> dict:
        """Audit the whole store for integrity, writing nothing.

        Until now the hash checks only ran at decision time, for the
        single id being decided: a tampered record for a request nobody
        tried to decide yet was invisible. ``verify`` runs the same
        class of checks over EVERY record and ledger event, so an
        operator can prove (or disprove) that the store on disk still
        agrees with itself before trusting any status it shows:

        - every record file parses, its inner id matches its file
          name, and its content recomputes to its stored hash;
        - every record has an ``ingested`` ledger event, and that
          event carries the record's exact stored hash;
        - every decision event names a recorded, ingested request,
          carries that request's exact stored hash, and is the only
          decision for its id;
        - every ``ingested`` event names a record that exists;
        - the ledger itself is readable (a corrupt ledger is
          reported as a problem, never raised past the audit and
          never guessed around).

        Read-only by construction: this method opens nothing for
        writing, never calls :meth:`_ensure` or
        :meth:`_append_ledger`, records no decision, and creates no
        store directory for a store that does not exist. A problem
        found here changes nothing; decisions remain the only writes
        and still require an explicit command with the exact hash.

        Returns a report dict: ``ok`` (True only when ``problems`` is
        empty), ``checked`` counts (records, ledger_events, and the
        per-status counts a reader would derive), and ``problems``,
        a list of ``{"id", "check", "detail"}`` dicts in scan order.
        """
        problems: list[dict] = []

        def flag(req_id, check: str, detail: str) -> None:
            problems.append({"id": req_id, "check": check,
                             "detail": detail})

        events: list[dict] = []
        ledger_ok = True
        try:
            events = self.read_ledger()
        except StoreError as exc:
            ledger_ok = False
            flag(None, "ledger-readable", str(exc))

        records: dict[str, dict] = {}
        if self.requests_dir.exists():
            for path in sorted(self.requests_dir.glob("*.json")):
                try:
                    record = self._parse_record(path, path.stem)
                except StoreError as exc:
                    flag(path.stem, "record-parse", str(exc))
                    continue
                records[record["id"]] = record

        ingested: dict[str, list[dict]] = {}
        decisions: dict[str, list[dict]] = {}
        if ledger_ok:
            for ev in events:
                ev_id = ev.get("id")
                if not isinstance(ev_id, str):
                    continue
                if ev.get("event") == "ingested":
                    ingested.setdefault(ev_id, []).append(ev)
                elif ev.get("event") in ("approved", "denied"):
                    decisions.setdefault(ev_id, []).append(ev)

        for req_id in sorted(records):
            record = records[req_id]
            stored = record["hash"]
            recomputed = content_hash(record["content"])
            if recomputed != stored:
                flag(req_id, "content-hash",
                     f"record content recomputes to {recomputed}, not "
                     f"the stored hash {stored}; the record was edited "
                     "after ingest")
            if not ledger_ok:
                continue
            ing = ingested.get(req_id, [])
            if not ing:
                flag(req_id, "ingested-event",
                     "record has no 'ingested' ledger event; it was "
                     "never recorded and must not be decided")
            else:
                if len(ing) > 1:
                    flag(req_id, "ingested-event",
                         f"ledger holds {len(ing)} 'ingested' events "
                         "for this id; exactly one is expected")
                if any(ev.get("hash") != stored for ev in ing):
                    flag(req_id, "ingested-hash",
                         "an 'ingested' ledger event for this id "
                         "carries a different hash than the record; "
                         "the record was replaced after ingest")
            decs = decisions.get(req_id, [])
            if len(decs) > 1:
                flag(req_id, "duplicate-decision",
                     f"ledger holds {len(decs)} decision events for "
                     "this id; a request can be decided only once")
            for dec in decs:
                if dec.get("hash") != stored:
                    flag(req_id, "decision-hash",
                         f"the {dec.get('event')} decision event "
                         "carries a different hash than the record; "
                         "it was not recorded against this request")

        if ledger_ok:
            for ev_id in sorted(ingested):
                if ev_id not in records:
                    flag(ev_id, "orphan-ingested-event",
                         "'ingested' ledger event names a request "
                         "with no record file in the store")
            for ev_id in sorted(decisions):
                if ev_id not in records:
                    flag(ev_id, "orphan-decision-event",
                         "decision ledger event names a request with "
                         "no record file in the store")
                elif ev_id not in ingested:
                    flag(ev_id, "decision-without-ingest",
                         "decision ledger event exists for a request "
                         "with no 'ingested' event; record-before-"
                         "decision was not honoured")

        counts = {"pending": 0, "approved": 0, "denied": 0}
        for req_id in records:
            decs = decisions.get(req_id, [])
            if decs:
                counts[decs[0].get("event")] = \
                    counts.get(decs[0].get("event"), 0) + 1
            else:
                counts["pending"] += 1
        return {
            "ok": not problems,
            "checked": {
                "records": len(records),
                "ledger_events": len(events),
                "pending": counts["pending"],
                "approved": counts["approved"],
                "denied": counts["denied"],
            },
            "problems": problems,
        }


def default_store_path(explicit: str | None = None) -> Path:
    """Resolve which store directory to use, first match wins:

    1. an explicit path (the CLI ``--store`` / ``--queue`` flags),
    2. the first set environment variable among GHOSTAPPROVE_DIR,
       GHOSTAPPROVE_QUEUE, and GHOSTAPPROVE_HOME,
    3. ``.ghostapprove`` under the current working directory.
    """
    if explicit:
        return Path(explicit)
    # --store / --queue are aliases on the CLI; the environment
    # equivalents are checked in this order.
    for var in ("GHOSTAPPROVE_DIR", "GHOSTAPPROVE_QUEUE", "GHOSTAPPROVE_HOME"):
        env = os.environ.get(var)
        if env:
            return Path(env)
    return Path.cwd() / ".ghostapprove"
