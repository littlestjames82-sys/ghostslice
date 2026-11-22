"""Local price-table access (estimates only, never live prices).

Resolution order:
1. GHOSTBENCH_PRICES env var (path to a prices.json)
2. A sibling GhostSlice checkout's packaged prices.json
   (../../ghostslice/src/ghostslice/prices.json relative to this
   package's repo), or an installed ghostslice package's file.
3. A small built-in snapshot table (dated, labelled as a snapshot).

Every figure derived from this table is an ESTIMATE in reports.
"""
from __future__ import annotations

import json
import os

_FALLBACK = {
    "as_of": "2026-10-12",
    "models": [
        {"id": "claude-sonnet", "input_per_mtok_usd": 3.0,
         "output_per_mtok_usd": 15.0},
        {"id": "local", "input_per_mtok_usd": 0.0,
         "output_per_mtok_usd": 0.0},
    ],
    "note": "Built-in snapshot in ghostbench/prices.py, NOT live prices.",
    "_source": "builtin-snapshot",
}


def load_price_table() -> dict:
    """Load the local price table (see the module docstring for the order).

    The returned dict carries a ``_source`` key naming where the table
    came from, so reports can stamp it. Falls back to the built-in
    dated snapshot when no file is found.
    """
    env = os.environ.get("GHOSTBENCH_PRICES")
    candidates = []
    if env:
        candidates.append(env)
    try:
        import ghostslice
        candidates.append(os.path.join(
            os.path.dirname(ghostslice.__file__), "prices.json"))
    except Exception:
        pass
    here = os.path.abspath(os.path.dirname(__file__))
    candidates.append(os.path.normpath(os.path.join(
        here, "..", "..", "..", "ghostslice", "src", "ghostslice",
        "prices.json")))
    for cand in candidates:
        if cand and os.path.isfile(cand):
            try:
                with open(cand, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                # Valid JSON, wrong shape (e.g. a list): not a price
                # table. Skip it instead of crashing on data[...].
                continue
            data["_source"] = cand
            return data
    return dict(_FALLBACK)


def price_table_date(table: dict | None = None) -> str | None:
    """Return the price table's ``as_of`` (or ``date``) stamp, or ``None``."""
    table = table or load_price_table()
    if not isinstance(table, dict):
        return None
    return table.get("as_of") or table.get("date")


def estimate_input_cost_usd(tokens: int, model: str | None,
                            table: dict | None = None) -> float | None:
    """Estimated INPUT cost for tokens at the model's table rate.
    None when the model is unknown: unknown is stated, not guessed."""
    if model is None:
        return None
    if isinstance(tokens, bool) or not isinstance(tokens, (int, float)) \
            or tokens < 0:
        return None
    table = table or load_price_table()
    if not isinstance(table, dict):
        return None
    models = table.get("models")
    if not isinstance(models, list):
        return None
    for entry in models:
        if not isinstance(entry, dict):
            continue
        if entry.get("id") == model:
            rate = entry.get("input_per_mtok_usd")
            if rate is None or isinstance(rate, bool):
                return None
            try:
                rate = float(rate)
            except (TypeError, ValueError):
                return None
            if rate < 0:
                return None
            return round(tokens * rate / 1_000_000, 6)
    return None
