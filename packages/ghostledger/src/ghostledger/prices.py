"""Local dated price table (estimates only, never live/billed).

Resolution order:
1. explicit path argument
2. GHOSTLEDGER_PRICES env var
3. sibling GhostSlice checkout prices.json
4. bundled snapshot prices.json next to this module
5. built-in minimal fallback
"""
from __future__ import annotations
import json, math, os

_FALLBACK = {
    "as_of": "2026-10-12",
    "models": [
        {"id": "claude-sonnet", "input_per_mtok_usd": 3.0, "output_per_mtok_usd": 15.0},
        {"id": "local", "input_per_mtok_usd": 0.0, "output_per_mtok_usd": 0.0},
    ],
    "note": "Built-in fallback snapshot, NOT live prices.",
    "_source": "builtin-fallback",
}

def load_price_table(explicit=None) -> dict:
    """Load a price table, in the module-docstring resolution order.

    An explicitly named table (``--prices PATH``) is strict: a
    missing, unreadable, malformed, or wrongly shaped file raises
    ``ValueError`` rather than silently falling back, because the
    user named that table. Without an explicit path, the fallback
    chain is tolerant: a candidate counts as usable only when it is
    a JSON object with a ``models`` list, and unreadable or malformed
    candidates are passed over. The winning path is recorded on the
    returned table as ``_source`` so reports can name where their
    rates came from. Falls back to a small built-in snapshot when no
    file is usable.
    """
    if explicit:
        # An explicitly named table (--prices PATH) is the user's
        # stated source: a missing, unreadable, or malformed file is
        # an error, never a silent fall-through to the bundled
        # snapshot (which would book costs from a table the user
        # did not choose, under the chosen table's expectation).
        try:
            with open(explicit, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not load price table {explicit}: {exc}") from exc
        if not (isinstance(data, dict) and isinstance(data.get("models"), list)):
            raise ValueError(f"could not load price table {explicit}: "
                             "expected a JSON object with a models list")
        data["_source"] = explicit
        return data
    candidates = []
    env = os.environ.get("GHOSTLEDGER_PRICES")
    if env:
        candidates.append(env)
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.normpath(os.path.join(here, "..", "..", "..", "ghostslice", "src", "ghostslice", "prices.json")))
    try:
        import ghostslice  # type: ignore
        candidates.append(os.path.join(os.path.dirname(ghostslice.__file__), "prices.json"))
    except Exception:
        pass
    candidates.append(os.path.join(here, "prices.json"))
    for cand in candidates:
        if cand and os.path.isfile(cand):
            try:
                with open(cand, encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict) and isinstance(data.get("models"), list):
                    data["_source"] = cand
                    return data
            except (OSError, json.JSONDecodeError):
                continue
    return dict(_FALLBACK)

def _rates_of(entry):
    if not isinstance(entry, dict):
        return None
    try:
        rates = (float(entry.get("input_per_mtok_usd")), float(entry.get("output_per_mtok_usd")))
    except (TypeError, ValueError):
        return None
    # A negative or non-finite rate (JSON NaN / Infinity parse as
    # floats) would book a negative or NaN cost as if it were an
    # estimate. Treat such an entry as no usable rate: the model
    # reports as unknown, never guessed.
    if not all(math.isfinite(r) and r >= 0 for r in rates):
        return None
    return rates

def model_rates(table: dict, model):
    """Return ``(input_per_mtok_usd, output_per_mtok_usd)`` for a model, or ``None``.

    ``None`` means the model is not in the table: the caller books
    the cost as unknown, never as a guessed rate and never as $0.
    Matching is exact first, then trimmed and case-folded, so a
    label like ``Claude-Sonnet`` still finds ``claude-sonnet``
    while a table that deliberately lists two ids differing only by
    case keeps its own meaning.
    """
    if not model:
        return None
    models = table.get("models") or []
    if not isinstance(models, list):
        return None
    entries = [e for e in models if isinstance(e, dict)]
    # Exact match first, so a table that deliberately lists two ids
    # differing only by case keeps its own meaning.
    for entry in entries:
        if entry.get("id") == model:
            return _rates_of(entry)
    # Then a normalised match: model labels arrive from other tools'
    # reports and hand-typed --model flags, and "Claude-Sonnet" or a
    # trailing space should not silently book as an unknown model.
    wanted = str(model).strip().casefold()
    for entry in entries:
        if str(entry.get("id") or "").strip().casefold() == wanted:
            return _rates_of(entry)
    return None

def estimate_cost_usd(input_tokens: int, output_tokens: int, model, table=None):
    """Estimated cost in USD for the given counts, or ``None`` when the model is unknown.

    The figure is an estimate from the local dated table only,
    rounded to 6 decimal places. It is never a billed amount and
    never a live price. A model listed at a zero rate (local
    models) returns a genuine ``0.0``, which is different from the
    ``None`` an unlisted model returns.
    """
    table = table or load_price_table()
    rates = model_rates(table, model)
    if rates is None:
        return None
    in_rate, out_rate = rates
    return round((input_tokens * in_rate + output_tokens * out_rate) / 1_000_000, 6)
