"""Pre-flight cost estimator backed by a local, dated prices.json.

Prices are never fetched and never claimed live. Edit prices.json to
update them; the file carries its own `as_of` date.
"""
from __future__ import annotations

import json
from pathlib import Path

_PACKAGE_PRICES = Path(__file__).with_name("prices.json")


def find_prices_file(explicit: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path.cwd() / "prices.json")
    # project root when running from a source checkout: src/ghostslice -> ../../
    candidates.append(Path(__file__).resolve().parents[2] / "prices.json")
    candidates.append(_PACKAGE_PRICES)
    for c in candidates:
        if c.is_file():
            return c
    return _PACKAGE_PRICES


def load_prices(explicit: str | Path | None = None) -> dict:
    path = find_prices_file(explicit)
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    data["_path"] = str(path)
    return data


def models(prices: dict) -> list[dict]:
    return list(prices.get("models", []))


def get_model(prices: dict, model_id: str) -> dict:
    for m in prices.get("models", []):
        if m.get("id") == model_id:
            return m
    raise KeyError(f"unknown model id: {model_id}")


def estimate_cost(tokens: int, model: dict) -> float:
    """Cost in USD for `tokens` of INPUT (context ingestion)."""
    if tokens <= 0:
        return 0.0
    return tokens / 1_000_000 * float(model["input_per_mtok_usd"])


def preflight(before_tokens: int, after_tokens: int, model: dict, prices: dict) -> dict:
    before = estimate_cost(before_tokens, model)
    after = estimate_cost(after_tokens, model)
    return {
        "model_id": model["id"],
        "model_name": model.get("name", model["id"]),
        "prices_as_of": prices.get("as_of", "unknown"),
        "prices_note": "Local prices.json, not live. Verify before relying on these rates.",
        "before_tokens": before_tokens,
        "after_tokens": after_tokens,
        "saved_tokens": before_tokens - after_tokens,
        "before_cost_usd": round(before, 4),
        "after_cost_usd": round(after, 4),
        "saved_cost_usd": round(before - after, 4),
    }
