"""Savings ledger: append-only `.ghostslice-history.jsonl` in the project.

Every export (and explicit slice run through the CLI task command) appends
one JSON line: timestamp, kind, bundle path, before/after estimated tokens,
and (from v0.14) an `estimator` stamp naming the token-estimator version
that produced the totals ("v2" = the calibrated method; see tokens.py).
The dashboard summary reads it back and totals the savings across runs on
that project. Local only; the file is scanner-ignored.

History analytics (v0.14) build on the same records: per-run trend with
deltas, estimated dollars saved at a model's INPUT rate (ledger tokens
are context, i.e. input tokens — the same side preflight() prices), and
aggregates. Estimator honesty rule: records written before v0.14 carry
no stamp, and a pre-v0.10 record (estimator v1) cannot be told apart
from a v0.10-v0.13 record (v2) — so any history that is not uniformly
one stamped version is flagged `mixed` with a warning instead of being
trended as if its totals were directly comparable.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from .tokens import METHOD_VERSION

LEDGER_NAME = ".ghostslice-history.jsonl"

UNSTAMPED = "unstamped"


def ledger_path(root: str | Path) -> Path:
    return Path(root) / LEDGER_NAME


def append_record(root: str | Path, kind: str, before: int, after: int,
                  bundle: str | None = None,
                  extra: dict | None = None) -> Path | None:
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
        "estimator": f"v{METHOD_VERSION}",
    }
    if extra:
        # Additive annotations (e.g. {"redactions": n} from a v0.17
        # redacted export). Readers ignore keys they do not know.
        rec.update(extra)
    path = ledger_path(root_p)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return path


def _coerce_int(value) -> int | None:
    """Ledger token fields must be ints (or losslessly int-shaped).
    Anything else marks the line corrupt rather than poisoning sums."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _parse_file(root: str | Path) -> tuple[list[dict], int]:
    """(records, corrupt_line_count). A line is corrupt when it is not
    JSON, not a JSON object, or its before/after token fields are not
    int-shaped. Corrupt lines are skipped, never fatal."""
    path = ledger_path(root)
    if not path.is_file():
        return [], 0
    out: list[dict] = []
    corrupt = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            corrupt += 1
            continue
        if not isinstance(rec, dict):
            corrupt += 1
            continue
        before = _coerce_int(rec.get("before_tokens"))
        after = _coerce_int(rec.get("after_tokens"))
        if before is None or after is None:
            corrupt += 1
            continue
        rec = dict(rec)
        rec["before_tokens"] = before
        rec["after_tokens"] = after
        saved = _coerce_int(rec.get("saved_tokens"))
        rec["saved_tokens"] = saved if saved is not None else before - after
        out.append(rec)
    return out, corrupt


def read_records(root: str | Path) -> list[dict]:
    records, _corrupt = _parse_file(root)
    return records


def estimator_of(record: dict) -> str:
    stamp = record.get("estimator")
    return stamp if isinstance(stamp, str) and stamp else UNSTAMPED


def estimator_mix(records: list[dict]) -> dict:
    """Is this history uniformly one stamped estimator version?

    mixed=True (with a warning) when any record is unstamped — those
    predate v0.14 stamping, so v1-era and v2-era totals cannot be told
    apart — or when stamped records disagree on the version."""
    stamped_versions = sorted({estimator_of(r) for r in records
                               if estimator_of(r) != UNSTAMPED})
    unstamped = sum(1 for r in records if estimator_of(r) == UNSTAMPED)
    mixed = bool(records) and (unstamped > 0 or len(stamped_versions) > 1)
    warning = None
    if mixed:
        parts = []
        if unstamped:
            parts.append(
                f"{unstamped} record(s) predate estimator stamping "
                "(written before v0.14; v1-era and v2-era totals among "
                "them cannot be told apart)")
        if len(stamped_versions) > 1:
            parts.append("stamped versions present: "
                         + ", ".join(stamped_versions))
        warning = ("Estimator mix: " + "; ".join(parts)
                   + ". Totals across estimator versions are not "
                     "directly comparable — treat the trend as "
                     "approximate.")
    return {
        "stamped_versions": stamped_versions,
        "unstamped_records": unstamped,
        "current_version": f"v{METHOD_VERSION}",
        "mixed": mixed,
        "warning": warning,
    }


def summary(root: str | Path) -> dict:
    records, corrupt = _parse_file(root)
    return {
        "runs": len(records),
        "total_before_tokens": sum(r["before_tokens"] for r in records),
        "total_after_tokens": sum(r["after_tokens"] for r in records),
        "total_saved_tokens": sum(r["saved_tokens"] for r in records),
        "corrupt_lines": corrupt,
        "records": records,
    }


_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float], width: int = 60) -> str:
    """One-line block-char chart. Series longer than `width` are
    downsampled by bucket means (the buckets are consecutive, so the
    shape stays chronological). Zero variance renders mid-height."""
    vals = [float(v) for v in values]
    if not vals:
        return ""
    if len(vals) > width:
        buckets = []
        per = len(vals) / width
        for i in range(width):
            chunk = vals[int(i * per):int((i + 1) * per)] or vals[-1:]
            buckets.append(sum(chunk) / len(chunk))
        vals = buckets
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return _BLOCKS[3] * len(vals)
    span = hi - lo
    return "".join(
        _BLOCKS[min(7, max(0, int((v - lo) / span * 7 + 0.5)))] for v in vals)


def _parse_ts(raw) -> float | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _input_cost(tokens: int, model: dict) -> float:
    """USD for `tokens` of context at the model's INPUT rate, rounded
    for display. Unlike pricing.estimate_cost this does not clamp at
    zero: a history whose slices grew the context honestly totals a
    negative saving. (Per-run $ in analytics accumulates the raw
    rate inline so cumulative and total agree exactly — see G09 F1;
    this helper prices the aggregate total.)"""
    return round(tokens / 1_000_000 * float(model["input_per_mtok_usd"]), 4)


def analytics(root: str | Path, model: dict | None = None,
              prices: dict | None = None) -> dict:
    """Summary keys (unchanged) + trend/aggregate analytics (additive).

    `model`/`prices` follow pricing.py shapes; when a model is given,
    per-run and total estimated dollars saved are computed at its
    input rate and the payload names the price snapshot date."""
    base = summary(root)
    records = base["records"]
    mix = estimator_mix(records)

    runs_detail: list[dict] = []
    cum_saved = 0
    cum_cost_raw = 0.0
    prev_after: int | None = None
    for i, rec in enumerate(records):
        before, after = rec["before_tokens"], rec["after_tokens"]
        saved = rec["saved_tokens"]
        cum_saved += saved
        entry = {
            "index": i,
            "at": rec.get("at"),
            "timestamp": _parse_ts(rec.get("at")),
            "kind": rec.get("kind"),
            "bundle": rec.get("bundle"),
            "estimator": estimator_of(rec),
            "before_tokens": before,
            "after_tokens": after,
            "saved_tokens": saved,
            "saved_pct": round(100.0 * saved / before, 2) if before > 0 else 0.0,
            "delta_after_tokens": None if prev_after is None else after - prev_after,
            "cumulative_saved_tokens": cum_saved,
        }
        if model is not None:
            # Accumulate RAW cost; round only for display. Summing the
            # rounded per-run values drifts from the total computed off
            # total_saved_tokens (audit G09 F1) — raw accumulation makes
            # the final cumulative equal the aggregate total exactly.
            raw_cost = saved / 1_000_000 * float(model["input_per_mtok_usd"])
            cum_cost_raw += raw_cost
            entry["saved_cost_usd"] = round(raw_cost, 4)
            entry["cumulative_saved_cost_usd"] = round(cum_cost_raw, 4)
        prev_after = after
        runs_detail.append(entry)

    aggregates: dict = {
        "mean_saved_pct": None,
        "median_saved_pct": None,
        "best_run": None,
        "worst_run": None,
        "first_after_tokens": None,
        "last_after_tokens": None,
        "after_change_tokens": None,
        "after_change_pct": None,
        "first_at": None,
        "last_at": None,
        "span_days": None,
        "runs_per_week": None,
    }
    if runs_detail:
        pcts = [r["saved_pct"] for r in runs_detail]
        aggregates["mean_saved_pct"] = round(statistics.fmean(pcts), 2)
        aggregates["median_saved_pct"] = round(statistics.median(pcts), 2)
        best = max(runs_detail, key=lambda r: (r["saved_tokens"], -r["index"]))
        worst = min(runs_detail, key=lambda r: (r["saved_tokens"], r["index"]))
        for key, run in (("best_run", best), ("worst_run", worst)):
            aggregates[key] = {
                "index": run["index"], "at": run["at"],
                "saved_tokens": run["saved_tokens"],
                "saved_pct": run["saved_pct"],
            }
        first, last = runs_detail[0], runs_detail[-1]
        aggregates["first_after_tokens"] = first["after_tokens"]
        aggregates["last_after_tokens"] = last["after_tokens"]
        change = last["after_tokens"] - first["after_tokens"]
        aggregates["after_change_tokens"] = change
        aggregates["after_change_pct"] = (
            round(100.0 * change / first["after_tokens"], 2)
            if first["after_tokens"] > 0 else None)
        aggregates["first_at"] = first["at"]
        aggregates["last_at"] = last["at"]
        stamps = [r["timestamp"] for r in runs_detail if r["timestamp"] is not None]
        if len(stamps) >= 2:
            span_days = (max(stamps) - min(stamps)) / 86400.0
            aggregates["span_days"] = round(span_days, 2)
            # A weekly rate extrapolated from a sub-day span is noise
            # (3 runs in 22 minutes -> "1388.6/week"); report it only
            # once the history actually spans a day or more (G09 F2).
            if span_days >= 1:
                aggregates["runs_per_week"] = round(len(runs_detail) / (span_days / 7.0), 2)
        if model is not None:
            aggregates["total_saved_cost_usd"] = _input_cost(base["total_saved_tokens"], model)

    out = dict(base)
    out["estimator"] = mix
    out["runs_detail"] = runs_detail
    out["aggregates"] = aggregates
    out["charts"] = {
        "saved_tokens_sparkline": sparkline([r["saved_tokens"] for r in runs_detail]),
        "after_tokens_sparkline": sparkline([r["after_tokens"] for r in runs_detail]),
    }
    if model is not None:
        out["model"] = {
            "id": model.get("id"),
            "name": model.get("name", model.get("id")),
            "prices_as_of": (prices or {}).get("as_of", "unknown"),
            "prices_note": ("prices as of {} from local prices.json, "
                            "not live; input rates (context is input "
                            "tokens)").format((prices or {}).get("as_of", "unknown")),
        }
    return out
