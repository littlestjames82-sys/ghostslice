"""Dependents affected: a deliberately simple one-hop import scan.

For each changed file, find project files that import it and are not
themselves in the diff. This is NOT GhostScope's call graph and NOT
transitive blast radius: dynamic, runtime, and string-based
references are missed by design in v0.1.

Matching rules (polish, Oct 14, 2026; each pinned by a regression
test in tests/test_polish.py):
- Python candidates are FULL dotted module names. A changed file's
  full name is its path dotted (``pkg/helper.py`` -> ``pkg.helper``;
  ``pkg/__init__.py`` -> ``pkg``). An import matches when a candidate
  a source file actually references equals that full name:
  ``import pkg.helper``, ``import pkg`` (for ``__init__``),
  ``from pkg import helper`` (the imported name is tried as a
  submodule: ``pkg.helper``), comma imports (``import os, pricing``
  yields both), and relative imports resolved against the importing
  file's package (``from . import helper``, ``from .helper import
  thing``, ``from ..pkg import mod``).
- A bare stem (``import helper``) only matches a changed file in
  the SAME directory as the importer. A same-named module elsewhere
  in the tree is not claimed: no invented edges.
- JS/TS: relative imports in every static shape (``import ... from``,
  bare side-effect ``import './x'``, ``export ... from``,
  ``require(...)``, dynamic ``import(...)``) resolved against the
  importing file, trying the path as written plus the source
  suffixes .js/.ts/.tsx/.jsx/.mjs/.cjs and ``index`` files with
  those suffixes.
"""
from __future__ import annotations

import re
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules",
             ".tox", ".mypy_cache", "dist", "build", ".eggs"}
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
JS_SUFFIXES = (".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs")

_PY_IMPORT_LINE = re.compile(r"^\s*import\s+(.+)$", re.M)
_PY_FROM_LINE = re.compile(r"^\s*from\s+(\.*[\w\.]*)\s+import\s+(.+)$", re.M)
_JS_IMPORT = re.compile(
    r"(?:from\s+|require\(\s*|import\(\s*|import\s+)['\"](\.[^'\"]+)['\"]")


def _iter_sources(project: Path):
    """Yield reviewable source files under *project*, skipping caches,
    VCS, virtualenv, and vendored/generated trees (see ``SKIP_DIRS``)."""
    for p in sorted(project.rglob("*")):
        if p.is_dir() or p.suffix not in SOURCE_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(project).parts):
            continue
        if ".egg-info" in str(p):
            continue
        yield p


def _py_full_name(rel: str):
    """Full dotted module name for a Python file path."""
    parts = list(Path(rel).parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def _first_token(part: str):
    """First name in one comma-separated import part, or ``None``."""
    part = part.strip().strip("()").strip()
    if not part or part.startswith("#"):
        return None
    tok = part.split()[0].strip("()")
    return tok or None


def _py_candidates(text: str, importer_rel: str) -> set:
    """Full dotted module names a Python source file references."""
    out: set = set()
    for m in _PY_IMPORT_LINE.finditer(text):
        for part in m.group(1).split(","):
            tok = _first_token(part)
            if tok and re.fullmatch(r"[\w\.]+", tok):
                out.add(tok)
    # Package parts of the importing file, for relative imports.
    imp_parts = list(Path(importer_rel).parts[:-1])
    for m in _PY_FROM_LINE.finditer(text):
        base, names_part = m.group(1), m.group(2)
        names = []
        for part in names_part.split(","):
            tok = _first_token(part)
            if tok and re.fullmatch(r"\w+", tok):
                names.append(tok)
        if base.startswith("."):
            level = len(base) - len(base.lstrip("."))
            rest = base[level:]
            pkg = imp_parts[:len(imp_parts) - (level - 1)] \
                if level - 1 <= len(imp_parts) else []
            resolved = pkg + ([rest] if rest else [])
            base_name = ".".join(p for p in resolved if p)
        else:
            base_name = base
        if base_name:
            out.add(base_name)
            for n in names:
                out.add(f"{base_name}.{n}")
        elif names and base.startswith("."):
            for n in names:
                out.add(n)
    return out


def _js_targets(importer: Path, project: Path):
    """Project-relative paths a JS/TS file's relative imports may resolve to."""
    try:
        text = importer.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    out = set()
    for m in _JS_IMPORT.finditer(text):
        target = (importer.parent / m.group(1)).resolve()
        cands = [target]
        cands += [target.with_suffix(s) for s in JS_SUFFIXES]
        cands += [target / f"index{s}" for s in JS_SUFFIXES]
        for cand in cands:
            try:
                rel = cand.relative_to(project.resolve())
            except ValueError:
                continue
            out.add(str(rel))
    return out


def find_dependents(project, changed_paths: set, diff_paths: set) -> dict:
    """{changed_path: {dependents: [rel...], method: str}}"""
    project = Path(project)
    result = {p: {"dependents": [], "method": "import-scan-one-hop"}
              for p in sorted(changed_paths)}
    if not changed_paths:
        return result
    py_changed = {p for p in changed_paths if p.endswith(".py")}
    js_changed = {p for p in changed_paths
                    if Path(p).suffix in SOURCE_SUFFIXES - {".py"}}
    if not py_changed and not js_changed:
        return result
    full_to_path: dict = {}
    for p in py_changed:
        full = _py_full_name(p)
        if full:
            full_to_path[full] = p
    for src in _iter_sources(project):
        rel = str(src.relative_to(project))
        if rel in diff_paths:
            continue
        if src.suffix == ".py" and py_changed:
            try:
                text = src.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for cand in _py_candidates(text, rel):
                target = full_to_path.get(cand)
                if target is None and "." not in cand:
                    # Bare stem: claim only a same-directory sibling.
                    sib = str(Path(rel).parent / f"{cand}.py") \
                        if Path(rel).parent != Path(".") else f"{cand}.py"
                    if sib in py_changed:
                        target = sib
                if target and rel not in result[target]["dependents"]:
                    result[target]["dependents"].append(rel)
        elif js_changed and src.suffix != ".py":
            for target in _js_targets(src, project):
                if target in js_changed and \
                        rel not in result[target]["dependents"]:
                    result[target]["dependents"].append(rel)
    for entry in result.values():
        entry["dependents"].sort()
    return result
