"""Ledger entry model, IO, secret stripping, loop warning, filtering, grouping.

This module owns the ledger file itself: the entry shape (see
:func:`make_entry`), the append-only JSONL store with dedupe by
content-hash ``id``, and the aggregations behind ``summary`` and
``report``.

Hard rules that live here and must not be weakened:

* Token counts are counts: a negative count is invalid evidence and
  is never booked (:func:`make_entry` raises ``ValueError``).
* Estimates and actuals are never blended silently. The
  estimate-vs-actual ratio and delta compare only the entries that
  carry an estimate (``actual_tokens_with_estimate``).
* A loop warning (actual strictly greater than 3x the estimate) is
  a flag for a human to look at, not a verdict and not a block.
* Credential-named fields are dropped on sight by
  :func:`strip_secrets`; token *counts* (``*_tokens``,
  ``token_count``, ``tokens_in`` / ``tokens_out``) are numbers, not
  credentials, and are kept, while a singular ``*_token`` name is a
  credential and is dropped.
"""
from __future__ import annotations
import hashlib, json, math, os, re
from datetime import datetime, timezone
from pathlib import Path

from . import LOOP_THRESHOLD
from .prices import estimate_cost_usd, load_price_table

DEFAULT_LEDGER = ".ghostledger.jsonl"
# Credential-named keys are dropped on sight. *_tokens counts are kept:
# they are numbers, not credentials. Checked before the token rule.
_SECRET_RE = re.compile(r"(api[_-]?key|auth|secret|password|passwd|credential|bearer|session|cookie|private[_-]?key)", re.I)

def is_secret_key(key: str) -> bool:
    """Return True when a field name suggests a credential.

    Token *count* fields are explicitly *not* secrets: they are
    numbers, not credentials. That covers ``tokens``, ``token_count``,
    ``total_tokens``, ``estimated_tokens``, ``*_tokens``,
    ``*_token_count``, and ``tokens_in`` / ``tokens_out``; the check
    runs first, before the credential pattern. A singular ``*_token``
    name (``access_token``, ``refresh_token``, a bare ``token``) names
    a credential, not a count, and *is* a secret.
    """
    k = str(key).lower()
    # Token *count* keys are kept: they are numbers, not credentials.
    if (k in ("tokens", "token_count", "total_tokens", "estimated_tokens")
            or k.endswith("_tokens") or k.endswith("_token_count")
            or re.search(r"tokens?_(in|out)$", k)):
        return False
    # Singular *_token keys (access_token, refresh_token, csrf_token,
    # a bare token) name credentials, not counts: drop them on sight.
    # They used to survive stripping because the regex never named them.
    return bool(_SECRET_RE.search(k)) or "token" in k

def strip_secrets(obj):
    """Recursively drop credential-named fields from imported records.

    Applied to every imported record before an entry is built, so a
    ledger file never contains API keys by construction. Dicts and
    lists are walked; other values pass through unchanged.
    """
    if isinstance(obj, dict):
        return {k: strip_secrets(v) for k, v in obj.items() if not is_secret_key(str(k))}
    if isinstance(obj, list):
        return [strip_secrets(v) for v in obj]
    return obj

def default_ledger_path(explicit=None) -> Path:
    """Resolve the ledger path: explicit argument, else ``GHOSTLEDGER_FILE``, else ``./.ghostledger.jsonl``."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("GHOSTLEDGER_FILE")
    return Path(env) if env else Path(DEFAULT_LEDGER)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _day(at: str) -> str:
    return (at or "")[:10] or "unknown"

def entry_id(payload: dict) -> str:
    """Content hash of an entry's core fields; the dedupe key on import/add."""
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

def make_entry(*, project="unknown", model=None, agent=None, source="manual", kind="run",
               task="", at=None, input_tokens=0, output_tokens=0, total_tokens=None,
               estimated_tokens=None, note="", source_ref="", table=None) -> dict:
    """Build one ledger entry dict from booked counts and labels.

    Parameters:
        project, model, agent: grouping labels. Surrounding
            whitespace is stripped; a missing model/agent books as
            ``None`` and groups under ``unknown`` in reports.
        source: one of ``manual``, ``slice``, ``proxy``, ``bench``.
        kind, task: what the entry was and its short label.
        at: ISO timestamp; defaults to now (UTC). Its first 10
            characters are the entry's ``day`` grouping key. A
            non-string ``at`` (e.g. a numeric epoch in a foreign
            report) is treated as missing, never interpreted.
        input_tokens, output_tokens, total_tokens: booked counts.
            ``total_tokens`` defaults to input + output; when a
            total is given alone it is booked as input so totals
            reconcile. Any negative count raises ``ValueError``.
        estimated_tokens: the pre-run estimate the actual is
            compared against, or ``None`` for no estimate.
        note, source_ref: free text, and for imports the source
            file name plus line/task index (never a file body).
        table: a loaded price table; loaded on demand when omitted.

    Returns:
        The entry dict, including its content-hash ``id``, ``ratio``
        (``total / estimated`` or ``None``), ``loop_warning``
        (strictly greater than 3x), ``cost_estimate_usd`` (an
        estimate from the dated table, or ``None`` when the model
        is unknown, never a guessed $0), and ``price_table_as_of``.
    """
    # A non-string timestamp (e.g. a numeric epoch in a foreign report)
    # is not interpreted - guessing seconds vs milliseconds would
    # invent evidence. Treat it as missing, like no timestamp at all,
    # instead of crashing _day() on an unsubscriptable value.
    at = at if isinstance(at, str) and at else _now_iso()
    input_tokens = int(input_tokens or 0)
    output_tokens = int(output_tokens or 0)
    total = int(total_tokens) if total_tokens is not None else input_tokens + output_tokens
    estimated_raw = int(estimated_tokens) if estimated_tokens is not None else None
    # Token counts are counts: a negative value is invalid evidence,
    # never a bookable entry (it would book negative cost and could
    # trip the loop warning on nonsense). Callers that import count
    # such records as skipped; the CLI reports this as an error.
    for label, value in (("input_tokens", input_tokens), ("output_tokens", output_tokens),
                         ("total_tokens", total), ("estimated_tokens", estimated_raw)):
        if value is not None and value < 0:
            raise ValueError(f"{label} must not be negative (got {value})")
    # Labels are grouping keys: surrounding whitespace is never
    # meaningful and would split one model/project into two groups.
    if isinstance(model, str):
        model = model.strip() or None
    if isinstance(agent, str):
        agent = agent.strip() or None
    if isinstance(project, str):
        project = project.strip()
    # If only a total was given, book it as input so totals reconcile.
    if total_tokens is not None and not input_tokens and not output_tokens:
        input_tokens = total
    estimated = estimated_raw
    table = table or load_price_table()
    cost = estimate_cost_usd(input_tokens, output_tokens, model, table)
    ratio = round(total / estimated, 4) if estimated else None
    loop = bool(estimated and total > LOOP_THRESHOLD * estimated)
    core = {
        "at": at, "project": project or "unknown", "model": model, "agent": agent,
        "source": source, "kind": kind, "task": task or "",
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "total_tokens": total, "estimated_tokens": estimated,
        "source_ref": source_ref,
    }
    entry = dict(core)
    entry["id"] = entry_id(core)
    entry["day"] = _day(at)
    entry["ratio"] = ratio
    entry["loop_warning"] = loop
    entry["loop_threshold"] = LOOP_THRESHOLD
    entry["cost_estimate_usd"] = cost
    entry["price_table_as_of"] = table.get("as_of")
    entry["note"] = note or ""
    return entry

def load_entries(path) -> list:
    """Read a ledger file into a list of entry dicts.

    A missing file reads as an empty ledger; a path that exists but
    is not a file raises ``OSError`` (a configuration error, not an
    empty ledger). Blank lines and lines that are not JSON objects
    are skipped, so a hand-edited file with one bad line still loads
    its good entries.
    """
    p = Path(path)
    if p.exists() and not p.is_file():
        # A directory (or device, fifo, ...) at the ledger path is a
        # configuration error, not an empty ledger: say so instead of
        # silently reporting zero entries.
        raise OSError(f"ledger path is not a file: {p}")
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out

def append_entries(path, entries) -> int:
    """Append entries not already present by id; returns count added.

    Dedupe applies within the batch as well as against the file: a
    batch that carries the same id twice books it once.
    """
    existing = {e.get("id") for e in load_entries(path)}
    fresh, seen = [], set()
    for e in entries:
        eid = e.get("id")
        if eid in existing or eid in seen:
            continue
        seen.add(eid)
        fresh.append(e)
    if fresh:
        p = Path(path)
        if p.parent and str(p.parent) not in ("", "."):
            p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            for e in fresh:
                fh.write(json.dumps(e, sort_keys=True) + "\n")
    return len(fresh)

def append_entry(path, entry) -> bool:
    """Append a single entry; return True when it was newly booked (False = duplicate)."""
    return append_entries(path, [entry]) == 1

def filter_entries(entries, since=None, until=None, project=None):
    """Filter entries by inclusive day range (``since`` / ``until``, ``YYYY-MM-DD``) and/or one project."""
    out = []
    for e in entries:
        day = e.get("day") or _day(e.get("at", ""))
        if since and day < since:
            continue
        if until and day > until:
            continue
        if project and e.get("project") != project:
            continue
        out.append(e)
    return out

def _blank():
    return {"entries": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            "estimated_tokens": 0, "entries_with_estimate": 0,
            "actual_tokens_with_estimate": 0,
            "cost_estimate_usd": 0.0, "entries_with_cost": 0, "loop_warnings": 0}

def _safe_int(v) -> int:
    """Best-effort count from a ledger row being summarised.

    Ledger files are hand-editable JSONL and load_entries already
    skips malformed lines tolerantly; a row whose count is a numeric
    string, a float, or unparseable text must not crash the whole
    report with a ValueError traceback. Unparseable / non-finite /
    boolean values contribute 0.
    """
    if isinstance(v, bool):
        return 0
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):
        try:
            f = float(v)
        except (TypeError, ValueError, OverflowError):
            return 0
        return int(f) if math.isfinite(f) else 0

def _safe_cost(v):
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None

def _accumulate(bucket: dict, e: dict):
    bucket["entries"] += 1
    bucket["input_tokens"] += _safe_int(e.get("input_tokens"))
    bucket["output_tokens"] += _safe_int(e.get("output_tokens"))
    bucket["total_tokens"] += _safe_int(e.get("total_tokens"))
    if e.get("estimated_tokens") is not None:
        bucket["estimated_tokens"] += _safe_int(e["estimated_tokens"])
        bucket["entries_with_estimate"] += 1
        # The actual side of the estimate-vs-actual comparison: only
        # entries that carry an estimate belong in it. Entries with
        # no estimate still count in total_tokens, but including
        # their actuals in the ratio would blame the estimated
        # entries for tokens nobody estimated.
        bucket["actual_tokens_with_estimate"] += _safe_int(e.get("total_tokens"))
    cost = _safe_cost(e.get("cost_estimate_usd"))
    if cost is not None:
        bucket["cost_estimate_usd"] = round(bucket["cost_estimate_usd"] + cost, 6)
        bucket["entries_with_cost"] += 1
    if e.get("loop_warning"):
        bucket["loop_warnings"] += 1

def _finish(bucket: dict) -> dict:
    est = bucket["estimated_tokens"]
    actual = bucket["actual_tokens_with_estimate"]
    bucket["estimate_vs_actual_ratio"] = round(actual / est, 4) if est else None
    bucket["estimate_delta_tokens"] = actual - est if bucket["entries_with_estimate"] else None
    return bucket

def group_entries(entries, by: str) -> dict:
    """Group entries by ``project``, ``model``, ``agent``, or ``day`` and total each group.

    Missing labels group under ``unknown``. Keys are sorted so
    report output is stable. Raises ``ValueError`` for any other
    grouping name.
    """
    groups = {}
    for e in entries:
        if by == "day":
            key = e.get("day") or _day(e.get("at", ""))
        elif by in ("project", "model", "agent"):
            key = e.get(by) or "unknown"
        else:
            raise ValueError(f"unknown grouping: {by}")
        _accumulate(groups.setdefault(str(key), _blank()), e)
    return {k: _finish(v) for k, v in sorted(groups.items())}

def summarise(entries, table=None) -> dict:
    """Build the full report dict for a list of entries.

    Carries ``totals``, all four groupings (``by_project``,
    ``by_model``, ``by_agent``, ``by_day``), the full
    ``loop_warnings`` entries, ``unknown_models``, the price table
    date and source, and the ``cost_note`` labelling every dollar
    figure an estimate. This dict is exactly what
    ``ledger-report.json`` and the ``--json`` output contain.
    """
    table = table or load_price_table()
    bucket = _blank()
    for e in entries:
        _accumulate(bucket, e)
    _finish(bucket)
    unknown_models = sorted({str(e.get("model")) for e in entries
                             if e.get("model") and e.get("cost_estimate_usd") is None})
    warnings = [e for e in entries if e.get("loop_warning")]
    return {
        "tool": "ghostledger", "version": "0.1.0",
        "totals": bucket,
        "by_project": group_entries(entries, "project"),
        "by_model": group_entries(entries, "model"),
        "by_agent": group_entries(entries, "agent"),
        "by_day": group_entries(entries, "day"),
        "loop_warnings": warnings,
        "loop_threshold": LOOP_THRESHOLD,
        "unknown_models": unknown_models,
        "price_table_as_of": table.get("as_of"),
        "price_table_source": table.get("_source"),
        "cost_note": (f"Costs are ESTIMATES from a local dated price table "
                      f"(as of {table.get('as_of')}), never billed amounts."),
    }
