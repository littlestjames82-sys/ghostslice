"""Request ledger + report roll-up (GhostBench-shaped).

One JSON object per line. An entry NEVER contains: request or response
bodies (unless the process was explicitly run with log_bodies opt-in, and
even then bodies are not written here -- the ledger schema has no body
field at all), auth headers, API keys, or secret values. Transform-map
entries carry paths, modes, reasons, token estimates, and secret finding
TYPES only. A defensive scrub drops any key whose name looks credential-
bearing before a record is written, as a second line of defence.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .tokens import ESTIMATOR, ESTIMATOR_VERSION

_FORBIDDEN_KEY = re.compile(
    r"(api[_-]?key|authorization|authentication|oauth|password|passwd|"
    r"credentials?|bearer|cookies?|secrets?|private[_-]?key)",
    re.IGNORECASE)
# "auth" only counts as a whole key token: a bare substring match also
# dropped innocent keys such as "author" and "authority".
_FORBIDDEN_AUTH_TOKEN = re.compile(r"(?:^|[_\-\s])auth(?:[_\-\s]|$)",
                                   re.IGNORECASE)
# Keys that merely *mention* secrets without holding a value. The
# transform map's "secret_types" carries finding TYPES only (never a
# value) and the README promises it in the ledger ("path + finding
# type only"); the old substring scrub silently deleted it.
_SCRUB_ALLOWLIST = {"secret_types"}


def _is_forbidden_key(key) -> bool:
    name = str(key)
    if name.lower() in _SCRUB_ALLOWLIST:
        return False
    return bool(_FORBIDDEN_KEY.search(name)
                or _FORBIDDEN_AUTH_TOKEN.search(name))


def _scrub(obj):
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items()
                if not _is_forbidden_key(k)}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def _as_int(value) -> int:
    """Ledger fields are ints when we write them, but a hand-edited or
    older ledger must not crash reporting: unparseable values count 0."""
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def make_entry(*, project: str, method: str, path: str, status: int,
               transform: dict | None, latency_ms: float,
               fallback: bool = False, fallback_reason: str = "") -> dict:
    t = transform or {}
    # Headline tokens_in/out are the CONTEXT totals (the recognisable
    # project-file blocks): those are the numbers that must agree with a
    # manual GhostSlice export of the same files, which is the parity
    # GhostBench checks. Whole-request estimates ride along separately.
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "method": method,
        "path": path,
        "status": int(status),
        "tokens_in": t.get("context_tokens_in", t.get("tokens_in", 0)),
        "tokens_out": t.get("context_tokens_out", t.get("tokens_out", 0)),
        "context_tokens_in": t.get("context_tokens_in", 0),
        "context_tokens_out": t.get("context_tokens_out", 0),
        "total_request_tokens_in": t.get("tokens_in", 0),
        "total_request_tokens_out": t.get("tokens_out", 0),
        "files_seen": t.get("files_seen", []),
        "files_sliced": t.get("files_sliced", []),
        "files_dropped": t.get("files_dropped", []),
        "transform_map": t.get("transform_map", []),
        "latency_ms": round(float(latency_ms), 2),
        "fallback": bool(fallback or t.get("fallback", False)),
        "fallback_reason": fallback_reason or t.get("fallback_reason", ""),
        "estimator": ESTIMATOR,
        "estimator_version": ESTIMATOR_VERSION,
    }
    return _scrub(entry)


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, entry: dict) -> None:
        clean = _scrub(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(clean, sort_keys=True) + "\n")

    def entries(self) -> list[dict]:
        if not self.path.is_file():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue  # a corrupt line must not break reporting
        return out

    def writable(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8"):
                pass
            return True
        except Exception:
            return False


def build_report(entries: list[dict]) -> dict:
    """Aggregate ledger entries into the Bench-consumable report shape."""
    total_in = sum(_as_int(e.get("tokens_in", 0)) for e in entries)
    total_out = sum(_as_int(e.get("tokens_out", 0)) for e in entries)
    ctx_in = sum(_as_int(e.get("context_tokens_in", 0)) for e in entries)
    ctx_out = sum(_as_int(e.get("context_tokens_out", 0)) for e in entries)
    fallbacks = sum(1 for e in entries if e.get("fallback"))
    saved = total_in - total_out
    return {
        "tool": "ghostproxy",
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requests": len(entries),
        "tokens_in": total_in,
        "tokens_out": total_out,
        "tokens_saved_estimate": saved,
        "saving_pct_estimate": (round(100.0 * saved / total_in, 2)
                                if total_in else 0.0),
        # Honest split required by the plan: slicable context vs total.
        "context_tokens_in": ctx_in,
        "context_tokens_out": ctx_out,
        "fallback_count": fallbacks,
        "estimator": ESTIMATOR,
        "estimator_version": ESTIMATOR_VERSION,
        "entries": entries,
    }


def render_report_md(report: dict) -> str:
    lines = [
        "# GhostProxy report",
        "",
        f"Requests: {report['requests']}",
        f"Estimated tokens in: {report['tokens_in']}",
        f"Estimated tokens out: {report['tokens_out']}",
        f"Estimated saved: {report['tokens_saved_estimate']} "
        f"({report['saving_pct_estimate']}%)",
        f"Slicable context in/out: {report['context_tokens_in']} / "
        f"{report['context_tokens_out']}",
        f"Fallback (fail-open, original forwarded) count: "
        f"{report['fallback_count']}",
        f"Estimator: {report['estimator']} v{report['estimator_version']} "
        "(estimates, not exact tokenizer counts)",
        "",
        "Token figures are estimates from the local estimator. No request",
        "bodies, API keys, or secret values are stored in the ledger.",
    ]
    return "\n".join(lines) + "\n"
