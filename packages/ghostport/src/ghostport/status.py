"""Resumption view: plan + ledger -> status."""
from __future__ import annotations

import json
from pathlib import Path

from .ledger import read_records, unit_states


def build_status(project: Path, plan: dict | None = None) -> dict:
    """Combine the written plan and the ledger into a status dict.

    Uses ``<project>/port-plan.json`` when ``plan`` is not supplied.
    A unit with no ledger record is reported as planned-by-plan; the
    verified count only ever counts units with a verified record.
    """
    project = Path(project)
    plan_path = project / "port-plan.json"
    if plan is None and plan_path.is_file():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8", errors="replace"))
        except ValueError as exc:
            raise ValueError(f"port-plan.json: cannot parse ({exc})") from exc
    if plan is not None and not isinstance(plan, dict):
        raise ValueError("port-plan.json: top level is not an object")
    units = plan.get("units", []) if plan else []
    if not isinstance(units, list):
        raise ValueError("port-plan.json: 'units' is not a list")
    for entry in units:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise ValueError("port-plan.json: malformed unit entry (missing 'id')")
    states = unit_states(project)
    rows, remaining = [], 0
    counts = {"planned": 0, "bundled": 0, "ported-claimed": 0, "verified": 0, "unrecorded": 0}
    next_unit = None
    for u in units:
        state = states.get(u["id"])
        # Missing/odd plan fields default instead of KeyError-crashing status
        # (older or hand-trimmed plans may lack order/token estimates).
        try:
            tokens = int(u.get("estimated_tokens") or 0)
        except (TypeError, ValueError):
            tokens = 0
        order = u.get("order", 0)
        if state is None:
            # a unit in a written plan counts as planned-by-plan, unrecorded in ledger
            state_label = "planned (in plan, no ledger record)"
            counts["unrecorded"] += 1
        else:
            state_label = state
            counts[state] = counts.get(state, 0) + 1
        verified = state_label == "verified"
        if not verified:
            remaining += tokens
            if next_unit is None and state != "ported-claimed":
                next_unit = u["id"]
        rows.append({"unit": u["id"], "order": order, "state": state_label,
                     "estimated_tokens": tokens})
    return {"project": str(project), "units": rows, "counts": counts,
            "estimated_tokens_remaining": remaining,
            "verified_units": counts.get("verified", 0),
            "next_unit": next_unit,
            "ledger_records": len(read_records(project)),
            "note": "verified is only ever recorded from a GhostVerify post report."}
