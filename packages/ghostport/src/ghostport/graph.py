"""Project import graph + unit formation + dependency-order sequencing.

Units: one unit per file that has pattern hits (unit id from the file path).
Sequencing: leaves first - a unit is ordered after every touched unit it
imports. Cycles among touched units (strongly connected components with
more than one member, or a self-import) are combined into one unit and
named as a blocker in the plan, per PLAN.md.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path


def module_name(project: Path, path: Path) -> str:
    """Return the dotted module name for ``path`` inside ``project``.

    A leading ``src/`` component is dropped and ``__init__.py`` maps to
    its package, so ``src/pkg/mod.py`` becomes ``pkg.mod``.
    """
    rel = path.relative_to(project)
    parts = list(rel.parts)
    if len(parts) > 1 and parts[0] == "src":
        parts = parts[1:]
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def build_module_map(project: Path, py_files: list[Path]) -> dict[str, str]:
    """Map each file's dotted module name to its project-relative path."""
    out = {}
    for path in py_files:
        out[module_name(project, path)] = path.relative_to(project).as_posix()
    return out


def imports_of(path: Path, mod: str, module_map: dict[str, str]) -> set[str]:
    """Project-internal files this file imports (best-effort, static)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError, RecursionError, MemoryError, OSError):
        return set()
    deps = set()
    pkg_parts = mod.split(".")[:-1] if "__init__" not in path.name else mod.split(".")
    for node in ast.walk(tree):
        candidates = []
        if isinstance(node, ast.Import):
            candidates = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg_parts[: len(pkg_parts) - node.level + 1] if node.level <= len(pkg_parts) else []
                root = ".".join(base + ([node.module] if node.module else []))
                candidates = [root] + [f"{root}.{a.name}" for a in node.names]
            elif node.module:
                candidates = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        for cand in candidates:
            if cand == mod:
                continue  # a file importing itself is not a dependency
            if cand in module_map:
                # Old check compared the target's project-relative path to
                # path.name (basename), so a nested file's self-import was
                # never filtered here; identity is by module, above.
                deps.add(module_map[cand])
            else:
                # longest project-module prefix wins
                parts = cand.split(".")
                for i in range(len(parts) - 1, 0, -1):
                    prefix = ".".join(parts[:i])
                    if prefix == mod:
                        break  # prefix is this file's own module (package __init__)
                    if prefix in module_map:
                        deps.add(module_map[prefix])
                        break
    # remove self-reference by file path identity is handled by caller
    return deps


def unit_id_for(rel_path: str) -> str:
    """Return the stable unit id for a project-relative file path."""
    stem = rel_path[:-3] if rel_path.endswith(".py") else rel_path
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", stem).strip("-").lower()
    return f"unit-{slug}"


def _scc(nodes: list[str], edges: dict[str, set[str]]) -> list[list[str]]:
    """Return the strongly connected components of a directed graph (Tarjan, iterative)."""
    index, low, onstack, stack, result = {}, {}, set(), [], []
    counter = [0]

    def strongconnect(start):
        work = [(start, iter(sorted(edges.get(start, ()))))]
        index[start] = low[start] = counter[0]; counter[0] += 1
        stack.append(start); onstack.add(start)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter[0]; counter[0] += 1
                    stack.append(nxt); onstack.add(nxt)
                    work.append((nxt, iter(sorted(edges.get(nxt, ())))))
                    advanced = True
                    break
                elif nxt in onstack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    member = stack.pop(); onstack.discard(member)
                    comp.append(member)
                    if member == node:
                        break
                result.append(sorted(comp))

    for n in nodes:
        if n not in index:
            strongconnect(n)
    return result


def form_units(project: Path, scan: dict, profile: dict | None = None) -> dict:
    """Form units from a scan result and order them leaves-first.

    One unit per file with hits, merged or reordered only as the profile
    asks; units in a dependency cycle are combined into one unit and
    also reported in the returned ``blockers`` list. Returns a dict with
    ``units``, ``blockers``, token totals, and the import maps used.
    """
    project = Path(project)
    profile = profile or {}
    from .scanner import iter_project_files
    py_files, _ = iter_project_files(project)
    module_map = build_module_map(project, py_files)
    # Per-file module names computed directly. The old reverse lookup
    # (next(m for m, f in module_map.items() if f == rel)) raised
    # StopIteration whenever two files collapsed to one module name in the
    # map (e.g. foo.py and src/foo.py), crashing the whole plan.
    mod_by_rel = {path.relative_to(project).as_posix(): module_name(project, path)
                  for path in py_files}
    file_imports = {}
    for path in py_files:
        rel = path.relative_to(project).as_posix()
        mod = mod_by_rel[rel]
        deps = imports_of(path, mod, module_map)
        deps.discard(rel)
        file_imports[rel] = deps

    hits_by_file: dict[str, list[dict]] = {}
    for hit in scan["hits"]:
        hits_by_file.setdefault(hit["file"], []).append(hit)

    touched = sorted(hits_by_file)
    # edges between touched units only: unit -> touched units it depends on
    edges = {f: {d for d in file_imports.get(f, set()) if d in hits_by_file}
             for f in touched}
    comps = _scc(touched, edges)
    cycles = [c for c in comps if len(c) > 1]
    cycle_of = {}
    for cyc in cycles:
        cid = "unit-cycle-" + "-".join(sorted(unit_id_for(f)[5:] for f in cyc))[:60]
        for f in cyc:
            cycle_of[f] = cid

    # base units keyed by id
    units: dict[str, dict] = {}
    for f in touched:
        uid = cycle_of.get(f) or unit_id_for(f)
        unit = units.setdefault(uid, {"id": uid, "files": [], "hits": [],
                                      "combined_from_cycle": uid in cycle_of.values() and len([x for x in cycle_of if cycle_of[x] == uid]) > 1,
                                      "cycle_files": []})
        unit["files"].append(f)
        unit["hits"].extend(hits_by_file[f])
        if uid.startswith("unit-cycle-"):
            unit["combined_from_cycle"] = True
            unit["cycle_files"] = sorted(x for x in cycle_of if cycle_of[x] == uid)
    # manual merge override
    for group in profile.get("merge") or []:
        members = [u for u in (unit_id_for(g) if g.endswith(".py") else g for g in group) if u in units]
        if len(members) > 1:
            merged_id = members[0]
            merged = units[members[0]]
            for other in members[1:]:
                merged["files"].extend(units[other]["files"])
                merged["hits"].extend(units[other]["hits"])
                del units[other]
            merged["merged_by_profile"] = members

    # unit-level dependency edges (dependency units come first)
    unit_files = {uid: set(u["files"]) for uid, u in units.items()}
    file_to_unit = {f: uid for uid, files in unit_files.items() for f in files}
    unit_deps: dict[str, set[str]] = {uid: set() for uid in units}
    unit_callers: dict[str, set[str]] = {uid: set() for uid in units}
    for uid, u in units.items():
        for f in u["files"]:
            for dep_file in file_imports.get(f, set()):
                dep_uid = file_to_unit.get(dep_file)
                if dep_uid and dep_uid != uid:
                    unit_deps[uid].add(dep_uid)
                    unit_callers[dep_uid].add(uid)
    # covering tests: test files (not touched units) importing a unit file
    tests_for: dict[str, list[str]] = {uid: [] for uid in units}
    for path in py_files:
        rel = path.relative_to(project).as_posix()
        name = Path(rel).name
        if not (name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{rel}"):
            continue
        mod = mod_by_rel[rel]
        for dep in imports_of(path, mod, module_map):
            uid = file_to_unit.get(dep)
            if uid:
                tests_for[uid].append(rel)

    # leaves-first topological order; pin_first and order are tie-breakers only
    pin = list(profile.get("pin_first") or []) + list(profile.get("order") or [])
    rank_hint = {uid: i for i, uid in enumerate(pin)}
    ordered, done, remaining = [], set(), set(units)
    while remaining:
        ready = [u for u in remaining if unit_deps[u] <= done]
        if not ready:  # should not happen after SCC combining, but never hang
            ready = sorted(remaining)
        ready.sort(key=lambda u: (rank_hint.get(u, 10000), u))
        nxt = ready[0]
        ordered.append(nxt); done.add(nxt); remaining.discard(nxt)

    from .tokens import estimate_tokens
    out_units = []
    for idx, uid in enumerate(ordered, 1):
        u = units[uid]
        tokens = 0
        for f in u["files"]:
            tokens += estimate_tokens((project / f).read_text(encoding="utf-8", errors="replace"))
        out_units.append({
            "id": uid, "order": idx, "files": sorted(set(u["files"])),
            "hits": sorted(u["hits"], key=lambda h: (h["file"], h["line"])),
            "hit_count": len(u["hits"]),
            "pattern_ids": sorted({h["pattern_id"] for h in u["hits"]}),
            "depends_on_units": sorted(unit_deps[uid]),
            "caller_units": sorted(unit_callers[uid]),
            "covering_tests": sorted(set(tests_for[uid])),
            "covering_test_method": "import-graph (test file imports a unit file)" if tests_for[uid] else "none found",
            "combined_from_cycle": bool(u.get("combined_from_cycle")),
            "cycle_files": u.get("cycle_files", []),
            "estimated_tokens": tokens,
        })
    blockers = [{"type": "cycle-combined", "unit": u["id"], "files": u["cycle_files"]}
                for u in out_units if u["combined_from_cycle"]]
    return {"units": out_units, "blockers": blockers,
            "total_estimated_tokens": sum(u["estimated_tokens"] for u in out_units),
            "file_imports": {k: sorted(v) for k, v in file_imports.items()},
            "unit_callers": {k: sorted(v) for k, v in unit_callers.items()},
            "unit_deps": {k: sorted(v) for k, v in unit_deps.items()}}
