"""AST pattern scanner for Python projects.

Static only: files are parsed with ast, never imported or executed.
Findings are (file, line, pattern id, description) - no source text is
quoted into reports, matching the Ghost family redaction-safe habit.

Matching is binding-aware: the scanner first records the file's import
bindings (``import x as y``, ``from m import n as z`` ...) and resolves
dotted names through them, so one pattern hits in every idiomatic form:

- ``from inspect import getargspec`` (the import line itself, even if
  the name is never used again: importing a removed name breaks too)
- ``import ssl as s`` followed by ``s.wrap_socket(...)``
- ``import collections`` followed by ``collections.Mapping``
- ``from inspect import getargspec as gas`` followed by ``gas(fn)``

Resolution is best-effort and static, like the rest of GhostPort: a
local name that shadows an import binding is still resolved as the
import, and dynamic access (getattr, globals(), importlib by string)
is not followed. Look-alikes stay safe because resolution is exact:
``collections.abc.Mapping`` resolves to itself, never to
``collections.Mapping``, and ``context.wrap_socket`` (an unrelated
object) never resolves to ``ssl.wrap_socket``.
"""
from __future__ import annotations

import ast
from pathlib import Path

from .patterns import Pack

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "dist",
             "build", ".tox", ".mypy_cache", ".ghostport", ".claude_context"}
LANG_BY_EXT = {".js": "javascript", ".ts": "typescript", ".go": "go",
               ".rs": "rust", ".java": "java", ".rb": "ruby", ".php": "php",
               ".cs": "csharp", ".kt": "kotlin", ".swift": "swift"}


def iter_project_files(project: Path):
    """Collect a project's files as ``(python_files, other_languages)``.

    ``other_languages`` maps a language name to its files, which the scan
    reports as not covered. Hidden, cache, and build directories in
    SKIP_DIRS are skipped.
    """
    project = Path(project)
    py_files, other_langs = [], {}
    for path in sorted(project.rglob("*")):
        if any(part in SKIP_DIRS for part in path.relative_to(project).parts):
            continue
        if not path.is_file():
            continue
        if path.suffix == ".py":
            py_files.append(path)
        elif path.suffix in LANG_BY_EXT:
            other_langs.setdefault(LANG_BY_EXT[path.suffix], []).append(
                path.relative_to(project).as_posix())
    return py_files, other_langs


def dotted_name(node) -> str | None:
    """Return the dotted name for an attribute chain (``a.b.c``), or None."""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def import_bindings(tree: ast.AST) -> dict[str, str]:
    """Map each locally bound name to the dotted path it was imported as.

    ``import collections.abc as abc`` -> {"abc": "collections.abc"}
    ``import asyncio as aio``         -> {"aio": "asyncio"}
    ``import collections``            -> {"collections": "collections"}
    ``from inspect import getargspec as gas`` -> {"gas": "inspect.getargspec"}
    Relative imports (level > 0) are skipped: their targets are project
    modules, never the stdlib paths the packs name.
    """
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bindings[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    bindings.setdefault(top, top)
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                bindings[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return bindings


def resolve_dotted(dotted: str, bindings: dict[str, str]) -> str:
    """Replace the first component of a dotted name via import bindings."""
    head, _, rest = dotted.partition(".")
    target = bindings.get(head)
    if target is None:
        return dotted
    return f"{target}.{rest}" if rest else target


def _imported_targets(node) -> list[str]:
    """Dotted paths an import statement brings in (absolute imports only)."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and not node.level and node.module:
        return [f"{node.module}.{alias.name}" for alias in node.names
                if alias.name != "*"]
    return []


def _matches(matcher: dict, tree: ast.AST) -> list[int]:
    """Return sorted line numbers in ``tree`` matched by one pattern matcher."""
    kind = matcher["kind"]
    names = set(matcher.get("names", []))
    bindings = import_bindings(tree)
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if kind == "import_module":
                mods = matcher.get("modules", [])
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in mods or any(alias.name.startswith(m + ".") for m in mods):
                            lines.add(node.lineno)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module in mods or any(node.module.startswith(m + ".") for m in mods):
                        lines.add(node.lineno)
            elif kind == "import_from":
                if isinstance(node, ast.ImportFrom) and node.module == matcher.get("module"):
                    imported = {a.name for a in node.names}
                    if imported & names:
                        lines.add(node.lineno)
            elif kind in ("attribute", "attribute_or_name"):
                # Importing a removed name is itself a hit, even if the
                # name is never used again in the file.
                for target in _imported_targets(node):
                    leaf = target.rpartition(".")[2]
                    if matcher.get("attr_only"):
                        hit = leaf in names
                    elif kind == "attribute":
                        hit = target in names
                    else:
                        hit = target in names or leaf in names
                    if hit:
                        lines.add(node.lineno)
        elif isinstance(node, ast.Attribute):
            full = dotted_name(node)
            if full is None:
                continue
            leaf = node.attr
            resolved = resolve_dotted(full, bindings)
            if kind == "import_from":
                module = matcher.get("module", "")
                if any(resolved == f"{module}.{n}" for n in names):
                    lines.add(node.lineno)
            elif kind == "attribute":
                if matcher.get("attr_only"):
                    hit = leaf in names
                else:
                    hit = full in names or resolved in names
                if hit:
                    lines.add(node.lineno)
            elif kind == "attribute_or_name":
                if full in names or resolved in names or leaf in names:
                    lines.add(node.lineno)
        elif isinstance(node, ast.Name):
            target = bindings.get(node.id)
            if kind == "attribute_or_name":
                if node.id in names:
                    lines.add(node.lineno)
                elif target is not None:
                    leaf = target.rpartition(".")[2]
                    if target in names or leaf in names:
                        lines.add(node.lineno)
            elif kind == "import_from" and target is not None:
                module = matcher.get("module", "")
                if any(target == f"{module}.{n}" for n in names):
                    lines.add(node.lineno)
            elif kind == "attribute" and target is not None and not matcher.get("attr_only"):
                if target in names:
                    lines.add(node.lineno)
    return sorted(lines)


def scan_file(path: Path, pack: Pack) -> tuple[list[dict], str | None]:
    """Scan one file against ``pack``; return ``(hits, parse_error)``.

    Exactly one of the two results is meaningful: a file that does not
    parse returns no hits and the parse error as a string.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], f"io error: {exc}"
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], f"syntax error: {exc.msg} (line {exc.lineno})"
    except (ValueError, RecursionError, MemoryError) as exc:
        # e.g. deeply chained expressions ("1+1+1+...") raise RecursionError
        # from ast.parse; one pathological file must not kill the whole scan.
        return [], f"parse error: {type(exc).__name__}: {exc}"
    hits = []
    for pattern in pack.patterns:
        for line in _matches(pattern.matcher, tree):
            hits.append({"file": None, "line": line, "pattern_id": pattern.id,
                         "description": pattern.description})
    return hits, None


def scan_project(project: Path, pack: Pack) -> dict:
    """Scan every Python file in ``project`` against ``pack``.

    Returns the scan dict used by both the CLI and the planner: hits,
    files scanned with and without hits, parse errors, languages not
    covered, and the honesty note that zero hits is not an upgrade
    clearance. Writes nothing.
    """
    project = Path(project)
    py_files, other_langs = iter_project_files(project)
    all_hits, parse_errors, clean_files = [], [], []
    for path in py_files:
        rel = path.relative_to(project).as_posix()
        hits, err = scan_file(path, pack)
        if err:
            parse_errors.append({"file": rel, "error": err})
        for hit in hits:
            hit["file"] = rel
            all_hits.append(hit)
        if not hits and not err:
            clean_files.append(rel)
    all_hits.sort(key=lambda h: (h["file"], h["line"], h["pattern_id"]))
    return {
        "project": str(project),
        "pack": {"id": pack.id, "version": pack.version, "date": pack.date,
                 "title": pack.title},
        "hits": all_hits,
        "files_scanned": [p.relative_to(project).as_posix() for p in py_files],
        "files_with_hits": sorted({h["file"] for h in all_hits}),
        "files_without_hits": clean_files,
        "parse_errors": parse_errors,
        "not_covered_languages": {lang: files for lang, files in sorted(other_langs.items())},
        "note": (f"Results are hits for pack {pack.id} version {pack.version} only. "
                 "Zero hits does NOT mean this project is ready to upgrade."),
    }
