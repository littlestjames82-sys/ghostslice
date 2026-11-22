"""File + symbol graphs over outlines.

File edges come from imports and from calls to symbols defined in
another file. Symbol edges are caller -> callee by resolved name
(same-file first, then imported files, then a unique project-wide
name match; ambiguous name matches are not resolved, they are
counted as unresolved rather than guessed).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .outline import FileOutline, build_outline, resolve_imports
from .scanner import ScanResult, read_text

TRANSITIVE_DEPTH_CAP = 3


@dataclass
class ProjectGraph:
    outlines: dict[str, FileOutline] = field(default_factory=dict)
    file_edges: dict[str, set[str]] = field(default_factory=dict)   # file -> files it depends on
    file_callers: dict[str, set[str]] = field(default_factory=dict)  # file -> files depending on it
    symbol_callers: dict[str, set[str]] = field(default_factory=dict)  # qualified callee -> qualified callers
    symbol_callees: dict[str, set[str]] = field(default_factory=dict)
    symbols_by_name: dict[str, list[str]] = field(default_factory=dict)  # name -> qualified
    unresolved_calls: int = 0

    def distances_from(self, seeds: set[str]) -> dict[str, int]:
        """Undirected BFS distance from the changed-file set."""
        dist: dict[str, int] = {s: 0 for s in seeds}
        frontier = list(seeds)
        depth = 0
        while frontier and depth < 2:
            nxt: list[str] = []
            for f in frontier:
                neighbours = self.file_edges.get(f, set()) | self.file_callers.get(f, set())
                for n in neighbours:
                    if n not in dist:
                        dist[n] = depth + 1
                        nxt.append(n)
            frontier = nxt
            depth += 1
        return dist

    def direct_symbol_callers(self, qualified: str) -> list[str]:
        return sorted(self.symbol_callers.get(qualified, set()))

    def transitive_symbol_callers(self, qualified: str,
                                  cap: int = TRANSITIVE_DEPTH_CAP) -> list[str]:
        seen: set[str] = set()
        frontier = set(self.symbol_callers.get(qualified, set()))
        seen |= frontier
        depth = 1
        while frontier and depth < cap:
            nxt: set[str] = set()
            for q in frontier:
                nxt |= self.symbol_callers.get(q, set())
            nxt -= seen
            seen |= nxt
            frontier = nxt
            depth += 1
        return sorted(seen)


def build_project_graph(scan_result: ScanResult) -> ProjectGraph:
    graph = ProjectGraph()
    root_files = {f.path for f in scan_result.files}
    for entry in scan_result.files:
        try:
            source = read_text(entry.abspath)
        except OSError:
            source = ""
        outline = build_outline(entry.path, source, entry.language)
        resolve_imports(outline, root_files)
        graph.outlines[entry.path] = outline
        graph.file_edges[entry.path] = set(outline.imports)
        graph.file_callers.setdefault(entry.path, set())
        for qual, sym in outline.symbols.items():
            full = f"{entry.path}:{qual}"
            graph.symbols_by_name.setdefault(sym.name, []).append(full)
    # import edges into caller map
    for src, dsts in graph.file_edges.items():
        for d in dsts:
            graph.file_callers.setdefault(d, set()).add(src)
    # symbol call resolution + call-derived file edges
    for entry in scan_result.files:
        outline = graph.outlines[entry.path]
        local = {s.name: f"{entry.path}:{q}" for q, s in outline.symbols.items()}
        imported_files = set(outline.imports)
        for qual, sym in outline.symbols.items():
            caller_full = f"{entry.path}:{qual}"
            for raw in sym.calls:
                name = raw.split(".")[-1]
                target = None
                if raw in outline.symbols:
                    target = f"{entry.path}:{raw}"
                elif name in local:
                    target = local[name]
                else:
                    candidates = [q for q in graph.symbols_by_name.get(name, [])
                                  if q.split(":")[0] in imported_files]
                    if not candidates:
                        candidates = graph.symbols_by_name.get(name, [])
                    if len(candidates) == 1:
                        target = candidates[0]
                    elif len(candidates) > 1:
                        graph.unresolved_calls += 1
                if target and target != caller_full:
                    graph.symbol_callers.setdefault(target, set()).add(caller_full)
                    graph.symbol_callees.setdefault(caller_full, set()).add(target)
                    tfile = target.split(":")[0]
                    if tfile != entry.path:
                        graph.file_edges[entry.path].add(tfile)
                        graph.file_callers.setdefault(tfile, set()).add(entry.path)
    return graph


def module_hint_for(path: str) -> str:
    p = Path(path)
    return p.stem


def outline_cover(outline: FileOutline, changed_path: str,
                  changed_symbols: list[str]) -> dict:
    """Does one file's outline cover a changed file/symbol set?

    Single source of the covering semantics, shared by
    covering_tests (head side) and by lost-coverage detection in
    pack.py (base side, for test files the diff deleted or edited).
    Returns file-level ``reasons`` (import, call, or the parser-lite
    heuristic) plus the precise ``symbols`` the file calls: a bare
    import proves file-level cover only, so symbol-level claims are
    made from call hits alone and never guessed from an import.
    """
    reasons: list[str] = []
    if changed_path in outline.imports:
        reasons.append(f"imports {changed_path}")
    called_names = set()
    for sym in outline.symbols.values():
        for c in sym.calls:
            called_names.add(c.split(".")[-1])
    hit_syms = sorted(s for s in changed_symbols if s in called_names)
    if hit_syms:
        reasons.append("calls " + ", ".join(hit_syms))
    if outline.method != "ast" and not reasons:
        # parser-lite: fall back to a name mention in imports/text
        stem = module_hint_for(changed_path)
        if stem and any(stem in ext for ext in outline.external):
            reasons.append(f"mentions module {stem} in imports (heuristic)")
    method = "python-ast" if outline.method == "ast" else \
        "parser-lite heuristic (name/import based)"
    return {"reasons": reasons, "symbols": hit_syms, "method": method}


def covering_tests(scan_result: ScanResult, graph: ProjectGraph,
                   changed_path: str, changed_symbols: list[str]) -> list[dict]:
    """Test files covering a changed file/symbol set.

    Method is labelled per file: python-ast when the test file's
    AST outline calls a changed symbol or imports the changed
    module; parser-lite heuristic (name/import mention) otherwise.
    """
    out: list[dict] = []
    for entry in scan_result.files:
        if not entry.is_test or entry.path == changed_path:
            continue
        outline = graph.outlines.get(entry.path)
        if outline is None:
            continue
        cover = outline_cover(outline, changed_path, changed_symbols)
        if cover["reasons"]:
            out.append({"path": entry.path, "reasons": cover["reasons"],
                        "method": cover["method"]})
    return out
