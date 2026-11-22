"""Start-here reading order and dead zones, from AtlasData facts."""
from __future__ import annotations

from .data import READ_MIN_PER_1K_TOKENS

DOC_NAMES = {"readme.md", "readme", "readme.txt", "contributing.md",
             "changelog.md", "architecture.md", "docs.md"}


def reading_minutes(tokens: int) -> float:
    """Estimated reading time, in minutes, for ``tokens`` tokens.

    Uses the single documented rate in
    ``ghostatlas.data.READ_MIN_PER_1K_TOKENS`` (0.5 minutes per
    1,000 estimated tokens), rounded to one decimal with a 0.1
    minute floor for any non-empty file. It is a planning estimate
    shown next to the token estimate, not a second size metric.
    """
    if not tokens:
        return 0.0
    return max(0.1, round(tokens / 1000.0 * READ_MIN_PER_1K_TOKENS, 1))


def reading_order(data, top_n: int = 10) -> list:
    """Entry points first (Slice entry evidence, ranked), then the
    most depended-on modules, then README/docs. Each item carries a
    factual reason and its estimated reading cost."""
    by_path = data.by_path()
    out, seen = [], set()

    def add(path, reason, evidence=None):
        if path in seen or path not in by_path:
            return
        f = by_path[path]
        seen.add(path)
        out.append({
            "path": path,
            "reason": reason,
            "evidence": list(evidence or []),
            "tokens": f.get("tokens", 0),
            "reading_minutes": reading_minutes(f.get("tokens", 0)),
            "doc": f.get("doc", ""),
            "importer_count": f.get("importer_count", 0),
        })

    for cand in data.entries:
        path = cand.get("path")
        signals = cand.get("signals", [])
        reason = ("Entry point: " + signals[0]) if signals else "Entry point"
        add(path, reason, signals)
        if len(out) >= top_n:
            return out[:top_n]

    ranked = sorted(
        (f for f in data.files
         if f.get("importer_count", 0) > 0 and not f.get("is_test")),
        key=lambda f: (-f["importer_count"], -f.get("tokens", 0), f["path"]))
    for f in ranked:
        add(f["path"],
            f"Depended on by {f['importer_count']} file(s) in the import graph")
        if len(out) >= top_n:
            return out[:top_n]

    docs = sorted(
        (f for f in data.files if f.get("language") == "markdown"),
        key=lambda f: (f["path"].rsplit("/", 1)[-1].lower() not in DOC_NAMES,
                       f["path"]))
    for f in docs:
        add(f["path"], "Documentation file included by GhostSlice for this project")
        if len(out) >= top_n:
            break
    return out[:top_n]


def dead_zones(data) -> dict:
    """Observations for a human to judge. Framed as 'worth asking
    about' - never as delete instructions."""
    by_path = data.by_path()
    dead_files = []
    seen = set()
    for d in data.dead_candidates:
        p = d.get("path")
        if p and p not in seen:
            seen.add(p)
            tokens = d.get("tokens")
            if not isinstance(tokens, (int, float)):
                tokens = by_path.get(p, {}).get("tokens", 0)
            # A present-but-None reason/tokens (upstream payloads do
            # this) used to crash the HTML renderer via html.escape.
            dead_files.append({"path": p, "reason": d.get("reason") or "",
                               "tokens": tokens})
    if not dead_files:
        # Fallback shape: code files nothing imports and that are not
        # entry points, labelled as graph observations only.
        entry_paths = {e.get("path") for e in data.entries}
        for f in data.files:
            if (f.get("language") in ("python", "typescript", "javascript")
                    and not f.get("is_test") and not f.get("is_vendored")
                    and f.get("importer_count", 0) == 0
                    and f["path"] not in entry_paths):
                dead_files.append({
                    "path": f["path"],
                    "reason": "no importers found in the static import graph",
                    "tokens": f.get("tokens", 0)})

    unreferenced_docs = []
    for f in data.files:
        if f.get("language") == "markdown" and f.get("importer_count", 0) == 0:
            name = f["path"].rsplit("/", 1)[-1].lower()
            if name not in DOC_NAMES:
                unreferenced_docs.append({"path": f["path"],
                                          "tokens": f.get("tokens", 0)})

    dup_clusters = []
    for group in data.duplicates.get("exact", []) or []:
        dup_clusters.append({"kind": "exact", "files": group.get("files", []),
                             "tokens_each": group.get("tokens_each", 0)})
    for pair in data.duplicates.get("near", []) or []:
        files = pair.get("files") or [pair.get("a"), pair.get("b")]
        dup_clusters.append({"kind": "near", "files": [f for f in files if f],
                             "similarity": pair.get("similarity")})
    return {"dead_files": dead_files,
            "unreferenced_docs": unreferenced_docs,
            "duplicate_clusters": dup_clusters}
