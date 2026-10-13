"""Auto-fit: downgrade slice modes until a bundle fits a token budget.

Used by `ghostslice export --fit N` (and `task --fit N`). The starting
point is the mode each file would get anyway (explicit selections,
profile modes, CLI default, built-in defaults). While the total sliced
token estimate is over the fit budget, one file at a time is moved one
rung down the downgrade ladder:

    full -> signatures -> interfaces -> exclude

`strip-tests` and `headings` sit at the interfaces rung (they are
already reductions), so their next rung is `exclude`. A step that would
not actually save tokens for a file (e.g. `interfaces` on a JSON file
returns the full text) is skipped over: the file jumps straight to the
first rung that does save.

Which file goes next (deterministic): lowest value density first,
operationalised as
  1. files with no importers in the import graph before files with
     importers,
  2. then the largest current sliced size first,
  3. then path ascending.
A file can be downgraded repeatedly, one effective rung per pick,
until it reaches `exclude`.

Never auto-excluded: entry points (profile `entry_points`, else the
graph name heuristic) — they may be downgraded to `interfaces` but no
further. Never downgraded at all: files with an explicit mode (a
caller-supplied selection the caller asked to protect, or any mode set
by the project's `.ghostslice.json` profile — the profile is the
project owner's explicit instruction).

If even every downgradable file at `exclude`/`interfaces` cannot reach
the budget, the result reports `fitted: False` with the best achievable
total; the caller still writes the bundle and says so honestly.
"""
from __future__ import annotations

from pathlib import Path

from .graph import build_graph, find_entry_points, importers_of
from .slicer import slice_text
from .textio import read_text as _gs_read_text

_LADDER = ["full", "signatures", "interfaces", "exclude"]
_RUNG = {"full": 0, "signatures": 1, "interfaces": 2, "strip-tests": 2,
         "headings": 2, "structure": 2, "exclude": 3}


def _next_rung(mode: str) -> str | None:
    rung = _RUNG[mode]
    if rung >= 3:
        return None
    return _LADDER[rung + 1]


def fit_modes(scan_result, modes: dict[str, str], fit_tokens: int,
              profile=None, protected: set[str] | None = None,
              slice_fn=None) -> tuple[dict[str, str], dict]:
    """Return (final modes dict, fit report dict).

    `modes` maps every scanned path to its starting mode. `protected`
    holds paths the caller explicitly moded and wants left untouched;
    profile-moded paths are protected automatically.

    `slice_fn` (v0.20): optional drop-in for slicer.slice_text —
    build_bundle passes its cache-aware wrapper so ladder probes hit
    the content cache; the default is the plain slicer.
    """
    slice_text_fn = slice_fn or slice_text
    protected = set(protected or ())
    if profile is not None:
        for entry in scan_result.files:
            if profile.mode_for(entry.path) is not None:
                protected.add(entry.path)
    graph = build_graph(scan_result)
    rev = importers_of(graph)
    entry_points = set(find_entry_points(scan_result, profile))
    by_path = {e.path: e for e in scan_result.files}

    token_cache: dict[tuple[str, str], int] = {}

    def sliced_tokens(entry, mode: str) -> int:
        key = (entry.path, mode)
        if key not in token_cache:
            if mode == "full":
                token_cache[key] = entry.tokens
            elif mode == "exclude":
                token_cache[key] = 0
            else:
                source = _gs_read_text(entry.abspath)
                token_cache[key] = slice_text_fn(entry.path, source, mode).sliced_tokens
        return token_cache[key]

    current = dict(modes)
    totals = {p: sliced_tokens(by_path[p], m) for p, m in current.items()}
    before = sum(totals.values())
    total = before
    steps: dict[str, int] = {}
    downgraded: list[dict] = []

    def effective_next(path: str) -> tuple[str, int] | None:
        """First rung below the current mode that actually saves tokens."""
        mode = current[path]
        entry = by_path[path]
        nxt = _next_rung(mode)
        while nxt is not None:
            if path in entry_points and nxt == "exclude":
                return None  # entry points are never auto-excluded
            t = sliced_tokens(entry, nxt)
            if t < totals[path]:
                return nxt, t
            nxt = _next_rung(nxt)
        return None

    while total > fit_tokens:
        best: tuple[tuple, str, str, int] | None = None
        for path in current:
            if path in protected or current[path] == "exclude":
                continue
            nxt = effective_next(path)
            if nxt is None:
                continue
            nxt_mode, nxt_tokens = nxt
            key = (1 if rev.get(path) else 0, -totals[path], path)
            if best is None or key < best[0]:
                best = (key, path, nxt_mode, nxt_tokens)
        if best is None:
            break
        _key, path, nxt_mode, nxt_tokens = best
        transition = f"{current[path]}->{nxt_mode}"
        steps[transition] = steps.get(transition, 0) + 1
        downgraded.append({
            "path": path, "from": current[path], "to": nxt_mode,
            "saved": totals[path] - nxt_tokens,
        })
        total -= totals[path] - nxt_tokens
        totals[path] = nxt_tokens
        current[path] = nxt_mode

    report = {
        "fit_tokens": fit_tokens,
        "before_tokens": before,
        "after_tokens": total,
        "fitted": total <= fit_tokens,
        "steps": steps,
        "downgraded": downgraded,
    }
    return current, report
