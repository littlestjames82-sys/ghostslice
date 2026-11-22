"""Ledger audit: re-check a booked ledger against its own rules.

``ghostledger verify`` reads the ledger file line by line (not via
``load_entries``, which silently skips malformed lines - an audit
must count them) and re-derives everything that can be re-derived
from the booked fields alone:

- the content-hash ``id`` from the entry's core fields,
- ``day`` from ``at``, ``total_tokens`` from input + output,
- ``ratio`` and the 3x ``loop_warning`` from total vs estimate
  (estimates and actuals are compared, never blended or rewritten),
- ``cost_estimate_usd`` from the local dated price table - but only
  for entries booked under the *same* price-table date. An entry
  booked under a different date is counted as not re-checked and
  listed as such, never silently passed and never repriced: the
  booked books stay exactly as booked,
- duplicate ids, missing fields, negative or non-integer token
  counts, and any credential-named field (ledger files contain no
  API keys by construction; verify proves it for files already on
  disk, naming the offending key only, never its value).

Verify writes nothing and modifies nothing. It reports problems;
acting on them stays with the human.
"""
from __future__ import annotations
import json
from pathlib import Path

from . import LOOP_THRESHOLD
from .ledger import entry_id, is_secret_key
from .prices import estimate_cost_usd

# The fields make_entry hashes into the id, in make_entry's shape.
CORE_FIELDS = ("at", "project", "model", "agent", "source", "kind", "task",
               "input_tokens", "output_tokens", "total_tokens",
               "estimated_tokens", "source_ref")
# Every field a booked entry carries (see README entry format).
REQUIRED_FIELDS = CORE_FIELDS + ("id", "day", "ratio", "loop_warning",
                                 "loop_threshold", "cost_estimate_usd",
                                 "price_table_as_of", "note")
_TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens")


def _secret_keys(obj, found=None):
    found = [] if found is None else found
    if isinstance(obj, dict):
        for k, v in obj.items():
            if is_secret_key(str(k)):
                found.append(str(k))
            else:
                _secret_keys(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _secret_keys(v, found)
    return found


def _is_count(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def verify_lines(lines, table) -> dict:
    """Audit raw ledger lines against ``table``; returns a result dict."""
    problems = []

    def flag(line_no, entry, check, detail):
        problems.append({"line": line_no,
                         "id": entry.get("id") if isinstance(entry, dict) else None,
                         "check": check, "detail": detail})

    entries = 0
    cost_checked = 0
    cost_unchecked = 0
    seen_ids = {}
    n_lines = 0
    for line_no, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        n_lines += 1
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            flag(line_no, None, "malformed_line", f"not valid JSON ({exc.msg})")
            continue
        if not isinstance(entry, dict):
            flag(line_no, None, "not_an_object", "line is JSON but not an object")
            continue
        entries += 1

        secrets = _secret_keys(entry)
        if secrets:
            flag(line_no, entry, "secret_field",
                 f"credential-named field(s) present: {', '.join(sorted(secrets))} "
                 "(values never shown)")

        missing = [f for f in REQUIRED_FIELDS if f not in entry]
        if missing:
            flag(line_no, entry, "missing_field",
                 f"missing field(s): {', '.join(missing)}")

        eid = entry.get("id")
        if isinstance(eid, str):
            if eid in seen_ids:
                flag(line_no, entry, "duplicate_id",
                     f"id already booked on line {seen_ids[eid]}")
            else:
                seen_ids[eid] = line_no

        # Token counts: counts, so non-integer or negative is invalid.
        tokens_ok = True
        for f in _TOKEN_FIELDS:
            if f in entry and not _is_count(entry[f]):
                flag(line_no, entry, "bad_token_count",
                     f"{f}={entry[f]!r} is not a non-negative integer count")
                tokens_ok = False
        est = entry.get("estimated_tokens")
        if "estimated_tokens" in entry and est is not None and not _is_count(est):
            flag(line_no, entry, "bad_token_count",
                 f"estimated_tokens={est!r} is not null or a non-negative integer count")
            tokens_ok = False

        if tokens_ok and all(f in entry for f in _TOKEN_FIELDS):
            if entry["total_tokens"] != entry["input_tokens"] + entry["output_tokens"]:
                flag(line_no, entry, "total_mismatch",
                     f"total_tokens {entry['total_tokens']} != input "
                     f"{entry['input_tokens']} + output {entry['output_tokens']}")

        at = entry.get("at")
        if "at" in entry and not (isinstance(at, str) and len(at) >= 10):
            flag(line_no, entry, "bad_at", f"at={at!r} is not an ISO timestamp")
        elif isinstance(at, str) and "day" in entry and entry["day"] != at[:10]:
            flag(line_no, entry, "day_mismatch",
                 f"day {entry['day']!r} != day of at ({at[:10]!r})")

        if all(f in entry for f in CORE_FIELDS) and isinstance(eid, str):
            expected_id = entry_id({k: entry[k] for k in CORE_FIELDS})
            if eid != expected_id:
                flag(line_no, entry, "id_mismatch",
                     "id does not match the content hash of the entry's core fields")

        if tokens_ok and "estimated_tokens" in entry:
            total = entry.get("total_tokens")
            expected_ratio = round(total / est, 4) if est else None
            if "ratio" in entry and entry["ratio"] != expected_ratio:
                flag(line_no, entry, "ratio_mismatch",
                     f"ratio {entry['ratio']!r} != total/estimated ({expected_ratio!r})")
            expected_loop = bool(est and total > LOOP_THRESHOLD * est)
            if "loop_warning" in entry and entry["loop_warning"] is not expected_loop:
                flag(line_no, entry, "loop_warning_mismatch",
                     f"loop_warning {entry['loop_warning']!r} != {expected_loop!r} "
                     f"for total {total} vs estimate {est} at {LOOP_THRESHOLD}x")
        if "loop_threshold" in entry and entry["loop_threshold"] != LOOP_THRESHOLD:
            flag(line_no, entry, "loop_threshold_mismatch",
                 f"loop_threshold {entry['loop_threshold']!r} != {LOOP_THRESHOLD!r}")

        # Cost: re-derive only when the entry was booked under the
        # same dated table. A different date is stated, not guessed.
        if "price_table_as_of" in entry:
            if entry["price_table_as_of"] == table.get("as_of"):
                if tokens_ok:
                    expected_cost = estimate_cost_usd(
                        entry.get("input_tokens") or 0,
                        entry.get("output_tokens") or 0,
                        entry.get("model"), table)
                    cost_checked += 1
                    if ("cost_estimate_usd" in entry
                            and entry["cost_estimate_usd"] != expected_cost):
                        flag(line_no, entry, "cost_mismatch",
                             f"cost_estimate_usd {entry['cost_estimate_usd']!r} != "
                             f"{expected_cost!r} recomputed from the price table "
                             f"as of {table.get('as_of')} (estimates, never billed amounts)")
            else:
                cost_unchecked += 1

    return {
        "tool": "ghostledger",
        "lines": n_lines,
        "entries": entries,
        "problems": problems,
        "problem_count": len(problems),
        "cost_checked": cost_checked,
        "cost_unchecked": cost_unchecked,
        "price_table_as_of": table.get("as_of"),
        "ok": not problems,
    }


def verify_ledger(path, table) -> dict:
    """Audit the ledger file at ``path``; the file is only read."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    result = verify_lines(text.splitlines(), table)
    result["ledger"] = str(path)
    return result
