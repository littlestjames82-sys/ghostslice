"""Savings ledger: append-only `.ghostslice-history.jsonl` in the project.

Every export (and explicit slice run through the CLI task command) appends
one JSON line: timestamp, kind, bundle path, before/after estimated tokens.
The dashboard summary reads it back and totals the savings across runs on
that project. Local only; the file is scanner-ignored.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

LEDGER_NAME = ".ghostslice-history.jsonl"


def ledger_path(root: str | Path) -> Path:
    return Path(root) / LEDGER_NAME


def append_record(root: str | Path, kind: str, before: int, after: int,
                  bundle: str | None = None) -> Path | None:
    root_p = Path(root)
    if not root_p.is_dir():
        return None
    rec = {
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "bundle": bundle,
        "before_tokens": int(before),
        "after_tokens": int(after),
        "saved_tokens": int(before) - int(after),
    }
    path = ledger_path(root_p)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return path


def read_records(root: str | Path) -> list[dict]:
    path = ledger_path(root)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def summary(root: str | Path) -> dict:
    records = read_records(root)
    return {
        "runs": len(records),
        "total_before_tokens": sum(r.get("before_tokens", 0) for r in records),
        "total_after_tokens": sum(r.get("after_tokens", 0) for r in records),
        "total_saved_tokens": sum(r.get("saved_tokens", 0) for r in records),
        "records": records,
    }
