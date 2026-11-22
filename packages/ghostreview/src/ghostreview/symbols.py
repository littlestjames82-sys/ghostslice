"""Symbols touched by a change.

Python: exact via ast on the current file on disk (symbols whose body
range contains an added line, plus definitions in added lines), and
definition patterns over deleted line texts for removed symbols.
Other languages: parser-lite definition-line patterns matched against
added/deleted line texts only. The method is returned per file and
labelled in every report; parser-lite results are never presented as
complete.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

# Parser-lite definition patterns (name in group 1).
_LITE_PATTERNS = [
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("),
    re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"),
    re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\("),          # Go
    re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)\s*[<(]"),                 # Rust
    re.compile(r"^\s*(?:public|private|protected|static|final|\s)+[\w<>\[\]]+\s+([A-Za-z_]\w*)\s*\([^)]*\)\s*\{?\s*$"),  # Java-ish
]
_PY_DEF = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(|^\s*class\s+([A-Za-z_]\w*)")


def _lite_defs(texts):
    """Definition names matched by the parser-lite patterns in *texts*."""
    names = []
    for _no, text in texts:
        for pat in _LITE_PATTERNS:
            m = pat.match(text)
            if m:
                names.append(m.group(1))
                break
    return names


def _py_defs_from_lines(texts):
    """Python ``def``/``class`` names found in raw diff line *texts*."""
    names = []
    for _no, text in texts:
        m = _PY_DEF.match(text)
        if m:
            names.append(m.group(1) or m.group(2))
    return names


def _py_symbols_on_disk(project: Path, rel: str, added_nos: set):
    """Return (defined_names_with_ranges) for a Python file on disk."""
    path = project / rel
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return None
    out = []

    def walk(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = prefix + child.name
                end = getattr(child, "end_lineno", child.lineno) or child.lineno
                out.append((qual, child.lineno, end))
                walk(child, qual + ".")
            else:
                walk(child, prefix)
    walk(tree)
    return out


def symbols_for_change(project, change) -> dict:
    """{added, removed, modified, touched, method} for one FileChange."""
    path = change.path or ""
    added = change.added
    deleted = change.deleted
    is_py = path.endswith(".py")
    method = "python-ast" if is_py else "parser-lite-line-patterns"
    added_names: list = []
    removed_names: list = []
    modified_names: list = []

    if is_py:
        added_names = _py_defs_from_lines(added)
        removed_names = _py_defs_from_lines(deleted)
        if change.status != "deleted" and added:
            on_disk = _py_symbols_on_disk(Path(project), path, {n for n, _ in added})
            if on_disk is not None:
                added_nos = {n for n, _ in added}
                for qual, start, end in on_disk:
                    if any(start <= n <= end for n in added_nos):
                        base = qual.rsplit(".", 1)[-1]
                        if base not in added_names and base not in removed_names:
                            modified_names.append(qual)
            else:
                method = "parser-lite-line-patterns"
    else:
        added_names = _lite_defs(added)
        removed_names = _lite_defs(deleted)

    # A name defined on both sides is a modified (re-defined) symbol.
    both = [n for n in added_names if n in removed_names]
    for n in both:
        added_names.remove(n)
        removed_names.remove(n)
        if n not in modified_names:
            modified_names.append(n)

    touched = sorted(set(added_names + removed_names + modified_names))
    return {
        "added": sorted(set(added_names)),
        "removed": sorted(set(removed_names)),
        "modified": sorted(set(modified_names)),
        "touched": touched,
        "method": method,
    }
