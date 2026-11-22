"""Partition an inventory into surface / context / out / conflict.

Every inventory file gets exactly one decision. Reason codes record which
rule fired. Conflicts (surface match + user pin-out) are never resolved
silently: the decision is 'conflict' until a human changes a pin or uses
an explicit, recorded override at export time.
"""
import ast
import fnmatch
import re

from .inventory import estimate_tokens

# Cap on line numbers stored per pattern hit per file. The total line
# count and occurrence count are always recorded in full; only the
# stored list is capped so exposure.json stays bounded on large files.
MAX_EVIDENCE_LINES = 50


def _pin_list(value):
    """Normalise a pin setting to a list of glob strings.

    A single string is ONE glob: ``list("auth/**")`` would split it
    into single characters, and the ``*`` character is a glob that
    matches every file, silently pinning the whole tree in or out.
    Non-string entries and non-list values are ignored rather than
    crashing the glob matching later."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [v for v in value if isinstance(v, str)]
    return []


def load_profile_pins(project):
    """Read the ``exposure`` pins from a project's ``.ghostslice.json``.

    Returns a dict with ``pinned_in`` and ``pinned_out`` glob lists and
    ``surface`` (the pack id named in the profile, or None). Both
    ``pinned_in``/``pinned_out`` and ``pin_in``/``pin_out`` spellings
    are accepted. A missing or unreadable profile yields empty pins;
    it never raises.
    """
    import json
    from pathlib import Path
    pins = {"pinned_in": [], "pinned_out": [], "surface": None}
    prof = Path(project) / ".ghostslice.json"
    if prof.exists():
        try:
            data = json.loads(prof.read_text(encoding="utf-8"))
        except Exception:
            return pins
        if not isinstance(data, dict):
            return pins
        exp = data.get("exposure") or {}
        if isinstance(exp, dict):
            # Accept both pinned_in/pinned_out and pin_in/pin_out spellings.
            pins["pinned_in"] = _pin_list(
                exp.get("pinned_in") or exp.get("pin_in"))
            pins["pinned_out"] = _pin_list(
                exp.get("pinned_out") or exp.get("pin_out"))
            surface = exp.get("surface")
            pins["surface"] = surface if isinstance(surface, str) else None
    return pins


def _glob_hit(rel, pat):
    """Return True when ``pat`` matches relative path ``rel``.

    Matches the full path, the path with ``pat`` in a subdirectory, or
    the file name alone, so a bare name or suffix pattern in a pack or
    pin list applies at any depth.
    """
    return (fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, "*/" + pat)
            or fnmatch.fnmatch(rel.rsplit("/", 1)[-1], pat))


def _text_pattern_evidence(text, needle):
    """Line-level evidence for a text pattern against ``text``.

    Returns (lines, line_count, occurrences, truncated) where ``lines``
    is the 1-indexed list of lines containing a match, capped at
    MAX_EVIDENCE_LINES, ``line_count`` is the full number of matching
    lines, and ``occurrences`` is the full number of matches. This is
    recorded evidence only: it records where the pattern fired, in the
    sender's source text, so a receiver can spot-check the recorded
    reasons without re-running the scan. It makes no statement about
    the contents of non-matching lines.
    """
    lines = []
    occurrences = 0
    try:
        rx = re.compile(needle)
    except re.error:
        rx = None
    for lineno, line in enumerate(text.splitlines(), 1):
        if rx is not None:
            count = len(rx.findall(line))
            # findall with groups returns tuples; count via finditer
            # for an accurate occurrence count either way.
            if count:
                occurrences += sum(1 for _ in rx.finditer(line))
                lines.append(lineno)
        elif needle in line:
            occurrences += line.count(needle)
            lines.append(lineno)
    truncated = len(lines) > MAX_EVIDENCE_LINES
    return lines[:MAX_EVIDENCE_LINES], len(lines), occurrences, truncated


def _pattern_hits(entry, pack):
    """Return the pack patterns that fire for one inventory entry.

    Each hit is a dict with ``code`` (the pattern kind), ``pattern_id``,
    and ``reason``. ``glob`` patterns match the path; ``symbol``,
    ``import``, and ``data`` patterns are searched in the file text as
    regular expressions, falling back to a plain substring search when
    the pattern is not a valid regex. Binary entries (no text) can
    only fire ``glob`` patterns.
    """
    hits = []
    text = entry.get("text") or ""
    for pat in pack["patterns"]:
        kind, needle = pat["kind"], pat["pattern"]
        fired = False
        lines, line_count, occurrences, truncated = [], 0, 0, False
        if kind == "glob":
            fired = _glob_hit(entry["path"], needle)
        elif kind in ("symbol", "import", "data"):
            if text:
                lines, line_count, occurrences, truncated = (
                    _text_pattern_evidence(text, needle))
                fired = line_count > 0
        if fired:
            hits.append({"code": kind, "pattern_id": pat["id"],
                         "reason": pat["reason"],
                         "lines": lines, "line_count": line_count,
                         "occurrences": occurrences,
                         "lines_truncated": truncated})
    return hits


def pattern_coverage(partition, pack):
    """Aggregate recorded evidence per surface-pack pattern.

    Returns one record per pattern in ``pack`` (in pack order),
    including patterns that matched no file. Each record lists the
    files the pattern was recorded as matching in ``partition``, the
    file count, and the summed line/occurrence evidence from those
    records. Patterns with no matches are recorded with an empty
    ``matched_files`` list and zero counts: that records a pattern
    outcome, not a statement about the tree's contents in general.
    Tolerates older partition records that lack the line-evidence
    fields (their lines are counted from the ``lines`` list if any).
    """
    coverage = []
    for pat in pack.get("patterns", []):
        matched_files = []
        total_lines = 0
        total_occurrences = 0
        for entry in partition:
            for reason in entry.get("reasons", []):
                if not isinstance(reason, dict):
                    continue
                if reason.get("pattern_id") != pat["id"]:
                    continue
                matched_files.append(entry["path"])
                total_lines += reason.get(
                    "line_count", len(reason.get("lines") or []))
                total_occurrences += reason.get("occurrences", 0)
        coverage.append({
            "pattern_id": pat["id"], "kind": pat["kind"],
            "pattern": pat["pattern"], "reason": pat["reason"],
            "matched_files": matched_files,
            "matched_file_count": len(matched_files),
            "total_line_hits": total_lines,
            "total_occurrences": total_occurrences,
        })
    return coverage


def _imports_of(entry):
    """Module names a file references (Python ast, else regex import lines)."""
    text = entry.get("text") or ""
    mods = set()
    if entry["path"].endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        mods.add(a.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        mods.add(node.module)
                        for a in node.names:
                            mods.add(f"{node.module}.{a.name}")
            return mods
    for m in re.finditer(r"(?m)^\s*(?:import|from)\s+([\w\.]+)", text):
        mods.add(m.group(1))
    for m in re.finditer(r"""(?:require\(|from\s+)['"]([^'"]+)['"]""", text):
        mods.add(m.group(1))
    return mods


def _module_to_paths(entries):
    """Map importable module names to inventory paths.

    Python files are keyed by dotted module path and by bare module
    name; other files are keyed by file stem. Used to resolve which
    inventory file an import refers to.
    """
    mapping = {}
    for e in entries:
        p = e["path"]
        if p.endswith(".py"):
            mod = p[:-3].replace("/", ".")
            if mod.endswith(".__init__"):
                mod = mod[:-9]
            mapping[mod] = p
            mapping[p.rsplit("/", 1)[-1][:-3]] = p
        elif p.rsplit("/", 1)[-1].count(".") >= 1:
            mapping[p.rsplit("/", 1)[-1].rsplit(".", 1)[0]] = p
    return mapping


def build_partition(entries, pack, pins):
    """Partition inventory ``entries`` against ``pack`` and ``pins``.

    Returns one dict per entry, sorted by path, with keys ``path``,
    ``decision`` (``surface``, ``context``, ``out``, or ``conflict``),
    ``reasons`` (a list of ``code``/``pattern_id``/``reason`` dicts),
    ``sha256``, ``size``, and ``estimated_tokens``. Every entry gets
    exactly one decision.

    Decision order: a surface match plus a pin-out is a ``conflict``;
    otherwise a surface match or a pin-in is ``surface``; otherwise
    ``out``. A second pass then promotes ``out`` files that import a
    surface file to ``context`` (reason ``graph-neighbour``), unless
    they were pinned out.
    """
    by_path = {e["path"]: e for e in entries}
    # First pass: surface matches and pins
    prelim = {}
    for e in entries:
        rel = e["path"]
        hits = _pattern_hits(e, pack)
        pin_in = any(_glob_hit(rel, g) for g in pins.get("pinned_in", []))
        pin_out = any(_glob_hit(rel, g) for g in pins.get("pinned_out", []))
        reasons = list(hits)
        if pin_in:
            reasons.append({"code": "user-pinned-in", "pattern_id": None,
                            "reason": "Pinned in by user profile.",
                            "lines": [], "line_count": 0, "occurrences": 0,
                            "lines_truncated": False})
        if pin_out:
            reasons.append({"code": "user-pinned-out", "pattern_id": None,
                            "reason": "Pinned out by user profile.",
                            "lines": [], "line_count": 0, "occurrences": 0,
                            "lines_truncated": False})
        if hits and pin_out:
            decision = "conflict"
        elif hits or pin_in:
            decision = "surface"
        elif pin_out:
            decision = "out"
        else:
            decision = "out"
        prelim[rel] = {"path": rel, "decision": decision, "reasons": reasons,
                       "sha256": e["sha256"], "size": e["size"],
                       "estimated_tokens": estimate_tokens(e.get("text"),
                                                         e["path"])}
    # Second pass: graph context = files that call into the surface
    # (distance-1 callers: they import a surface file). Files the surface
    # itself imports are not pulled in by this rule; a surface file's own
    # imports do not by themselves put a helper in the bundle.
    surface_paths = {p for p, d in prelim.items() if d["decision"] == "surface"}
    if surface_paths:
        modmap = _module_to_paths(entries)
        for e in entries:
            rel = e["path"]
            if rel in surface_paths or prelim[rel]["decision"] == "conflict":
                continue
            imports_surface = any(
                (modmap.get(m) or modmap.get(m.split(".")[-1])) in surface_paths
                for m in _imports_of(e))
            if imports_surface:
                if prelim[rel]["decision"] == "out" and not any(
                        r["code"] == "user-pinned-out"
                        for r in prelim[rel]["reasons"]):
                    prelim[rel]["decision"] = "context"
                    prelim[rel]["reasons"].append({
                        "code": "graph-neighbour", "pattern_id": None,
                        "reason": "Calls into a surface file (imports it), "
                                  "distance-1 graph context.",
                        "lines": [], "line_count": 0, "occurrences": 0,
                        "lines_truncated": False})
    return [prelim[p] for p in sorted(prelim)]


def partition_counts(partition):
    """Count a partition by decision.

    Returns a dict with ``surface``, ``context``, ``out``,
    ``conflict``, and ``total`` counts. ``total`` always equals the
    number of partition entries.
    """
    counts = {"surface": 0, "context": 0, "out": 0, "conflict": 0, "total": 0}
    for d in partition:
        counts[d["decision"]] = counts.get(d["decision"], 0) + 1
        counts["total"] += 1
    return counts
