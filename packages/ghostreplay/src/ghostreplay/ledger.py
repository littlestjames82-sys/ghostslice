"""Trend ledger: .ghostreplay-history.jsonl in the project root.

One JSON object per analysed session (append-only, like
GhostSlice's savings ledger). Records are stamped with the run
time - the ledger is a history, so unlike replay-report.json it
is NOT expected to be byte-identical across re-runs; analysing
the same session twice appends twice, and trend says so via the
record count. Secret-shaped strings never enter a record: only
ids, hashes, counts, and estimates are stored.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

LEDGER_NAME = ".ghostreplay-history.jsonl"


def append_record(project: str | Path, report: dict) -> Path:
    """Append one summary record for ``report``; return the ledger path."""
    path = Path(project) / LEDGER_NAME
    t = report["totals"]
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": "ghostreplay",
        "version": "0.1.0",
        "session_id": report["session_id"],
        "transcript_sha256": report.get("transcript_sha256"),
        "bundle_manifest_sha256": (report["bundle"] or {}).get(
            "manifest_sha256"),
        "turn_count": report["turn_count"],
        "sent_sliced_estimated_tokens": t["sent_sliced_estimated_tokens"],
        "estimated_waste_tokens": t["estimated_waste_tokens"],
        "estimated_waste_percent": t["estimated_waste_percent_of_sent"],
        "reread_waste_estimated_tokens": t["reread_waste_estimated_tokens"],
        "not_referenced_estimated_tokens":
            t["not_referenced_estimated_tokens"],
        "reported_input_tokens": report["reported_input_tokens"],
        "reported_output_tokens": report["reported_output_tokens"],
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return path


def read_records(project: str | Path) -> list[dict]:
    """Read all ledger records (empty list if there is no ledger yet).

    Malformed lines are skipped rather than failing the trend view:
    the ledger is an append-only history, not a validated input.
    """
    path = Path(project) / LEDGER_NAME
    if not path.is_file():
        return []
    records = []
    # errors="replace": one corrupt byte in an append-only ledger
    # must not crash `trend` for every later, valid record.
    for line in path.read_text(
            encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


def _num(value) -> float:
    """Numeric ledger fields only; a hand-edited or corrupt record
    carrying a string/bool must degrade to 0, not crash trend with
    a TypeError when summed."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return value


def trend_summary(records: list[dict]) -> dict:
    """Summarise ledger records into one trend row per session."""
    if not records:
        return {"records": 0, "sessions": 0}
    # One row per session for the trend: the LATEST record per
    # session_id (re-analysis should not double-count a session).
    latest: dict[str, dict] = {}
    for rec in records:
        sid = rec.get("session_id") or "unknown"
        latest[sid] = rec
    rows = sorted(latest.values(), key=lambda r: r.get("ts") or "")
    wastes = [_num(r.get("estimated_waste_percent", 0.0)) for r in rows]
    return {
        "records": len(records),
        "sessions": len(rows),
        "rows": rows,
        "first_waste_percent": wastes[0] if wastes else 0.0,
        "last_waste_percent": wastes[-1] if wastes else 0.0,
        "mean_waste_percent": round(sum(wastes) / len(wastes), 1)
        if wastes else 0.0,
        "total_estimated_waste_tokens": sum(
            _num(r.get("estimated_waste_tokens", 0)) for r in rows),
        "total_reread_waste_estimated_tokens": sum(
            _num(r.get("reread_waste_estimated_tokens", 0))
            for r in rows),
        "total_sent_sliced_estimated_tokens": sum(
            _num(r.get("sent_sliced_estimated_tokens", 0)) for r in rows),
    }
