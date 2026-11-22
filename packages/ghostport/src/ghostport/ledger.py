"""Local ledger: <project>/.ghostport-history.jsonl

States: planned, bundled, ported-claimed, verified.
HARD RULE (PLAN): `verified` may only be recorded from a GhostVerify post
report: a JSON file whose shape includes a bundle/project identity and a
passing verdict. There is deliberately no CLI flag to set verified by
hand; the only writer of a verified record is record_verified(), which
validates the report file first.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

LEDGER_NAME = ".ghostport-history.jsonl"
STATES = ("planned", "bundled", "ported-claimed", "verified")


def ledger_path(project: Path) -> Path:
    """Return the path of the project's ledger file."""
    return Path(project) / LEDGER_NAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_record(project: Path, record: dict) -> dict:
    """Append ``record`` to the ledger with a UTC timestamp; return it."""
    record = {"ts": _now(), **record}
    path = ledger_path(project)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def read_records(project: Path) -> list[dict]:
    """Return all ledger records in file order ([] when there is none)."""
    path = ledger_path(project)
    if not path.is_file():
        return []
    try:
        # errors="replace": one corrupt byte/line must not kill the whole
        # ledger (previously UnicodeDecodeError crashed `status` outright).
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            # Only JSON objects are records; a bare `123` / `"x"` / `[...]`
            # line used to crash unit_states() with a TypeError.
            if isinstance(rec, dict):
                out.append(rec)
    return out


def record_state(project: Path, unit_id: str, state: str, **extra) -> dict:
    """Record a state change for a unit, with any extra fields merged in.

    Refuses the ``verified`` state: use :func:`record_verified`, which
    requires a GhostVerify post report.
    """
    if state == "verified":
        raise ValueError("verified state cannot be set directly; "
                         "use record_verified() with a GhostVerify report")
    if state not in STATES:
        raise ValueError(f"unknown state: {state}")
    label = "claim" if state == "ported-claimed" else "event"
    return append_record(project, {"unit": unit_id, "state": state,
                                   "state_kind": label, **extra})


PASSING_VERDICTS = ("pass", "passed", "sufficient", "sufficient_after_expand", "ok")
IDENTITY_KEYS = ("project", "bundle", "unit", "subject", "bundle_manifest_sha256")


def validate_verify_report(report_path: Path) -> dict:
    """Load and validate a GhostVerify post report; return its data.

    Accepts a JSON object with ok/verdict pass. Accepted shapes:
    {"ok": true, ...} or {"verdict": "pass"/"sufficient"} plus a subject
    (bundle or project or unit). Raises ValueError when the file is
    missing, is not JSON, or does not carry the required identity and
    passing-verdict fields. Anything else is refused.

    Hardening: the subject/identity requirement is now actually enforced
    (a bare {"ok": true} from any file used to verify any unit); the real
    GhostVerify post verdict "ok" (run_post sets verdict="ok", exit 0) is
    accepted (it used to be refused); and contradictory reports such as
    {"ok": true, "verdict": "failed"} or {"ok": false, "verdict": "pass"}
    are refused instead of passing on whichever field matched first.
    """
    try:
        data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"verify report: cannot parse ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError("verify report: not a JSON object")
    if not any(isinstance(data.get(k), str) and data[k].strip() for k in IDENTITY_KEYS):
        raise ValueError("verify report: no subject identity "
                         f"(need one of {', '.join(IDENTITY_KEYS)})")
    verdict = str(data["verdict"]).lower() if "verdict" in data else None
    ok = data.get("ok")
    if ok is False or (verdict is not None and verdict not in PASSING_VERDICTS):
        raise ValueError("verify report: does not record a passing verdict")
    passed = ok is True or verdict in PASSING_VERDICTS
    if not passed:
        raise ValueError("verify report: does not record a passing verdict")
    return data


def record_verified(project: Path, unit_id: str, report_path: Path) -> dict:
    """Record ``verified`` for a unit from a validated Verify report.

    The report is validated first and its SHA-256 is stored in the
    ledger record, so a verified entry always names its evidence.
    """
    report = validate_verify_report(Path(report_path))
    digest = hashlib.sha256(Path(report_path).read_bytes()).hexdigest()
    return append_record(project, {
        "unit": unit_id, "state": "verified", "state_kind": "verified",
        "verify_report": str(report_path), "verify_report_sha256": digest,
        "verify_verdict": report.get("verdict", "ok")})


def unit_states(project: Path) -> dict[str, str]:
    """Return the latest recorded state per unit id from the ledger.

    Latest state per unit, in ledger order.

    Hardening: unknown states are ignored (a hand-edited ``bogus-state``
    record used to flow straight into status counts), and a ``verified``
    record only counts as verified when it rests on a GhostVerify report,
    i.e. it carries the ``verify_report`` path and ``verify_report_sha256``
    that record_verified() writes. A hand-forged ``{"state": "verified"}``
    line with no report is, at best, a claim, so it is downgraded to
    ``ported-claimed`` - the hard rule is enforced on read, not just on
    the one writer.
    """
    states = {}
    for rec in read_records(project):
        unit, state = rec.get("unit"), rec.get("state")
        if not isinstance(unit, str) or state not in STATES:
            continue
        if state == "verified" and not (rec.get("verify_report")
                                         and rec.get("verify_report_sha256")):
            state = "ported-claimed"
        states[unit] = state
    return states
