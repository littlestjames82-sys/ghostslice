"""Code slicing for the starter pack.

Modes reuse GhostSlice names: full, signatures, outline, head.
Python is sliced with the real `ast` module (exact). JS/TS use a
parser-lite regex outline/signature pass and are labelled parser-lite.
Other text languages get a head excerpt and are labelled head.
Every result carries a confidence label for the manifest.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path


def _doc_first_line(node) -> str | None:
    try:
        doc = ast.get_docstring(node)
    except Exception:
        return None
    if doc:
        first = doc.strip().splitlines()[0].strip()
        return first
    return None


def _format_signature(node) -> str:
    try:
        args = ast.unparse(node.args)
    except Exception:
        args = "..."
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    returns = ""
    if node.returns is not None:
        try:
            returns = f" -> {ast.unparse(node.returns)}"
        except Exception:
            returns = ""
    return f"{prefix}def {node.name}({args}){returns}:"


def _decorators(node) -> list[str]:
    out = []
    for dec in getattr(node, "decorator_list", []):
        try:
            out.append("@" + ast.unparse(dec))
        except Exception:
            pass
    return out


def _python_signatures(source: str) -> str:
    """Signature-depth slice of a Python module (real ``ast``).

    Keeps imports, function and class signatures, docstring first
    lines, and UPPER_CASE assignments; bodies become ``...``.
    """
    tree = ast.parse(source)
    lines: list[str] = []
    module_doc = _doc_first_line(tree)
    if module_doc:
        lines.append(f'""" {module_doc} """')
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            try:
                lines.append(ast.unparse(node))
            except Exception:
                pass
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines.extend(_decorators(node))
            lines.append(_format_signature(node))
            doc = _doc_first_line(node)
            if doc:
                lines.append(f"    # {doc}")
            lines.append("    ...")
        elif isinstance(node, ast.ClassDef):
            lines.extend(_decorators(node))
            bases = ""
            if node.bases:
                try:
                    bases = "(" + ", ".join(ast.unparse(b) for b in node.bases) + ")"
                except Exception:
                    bases = ""
            lines.append(f"class {node.name}{bases}:")
            doc = _doc_first_line(node)
            if doc:
                lines.append(f"    # {doc}")
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    lines.extend("    " + d for d in _decorators(sub))
                    lines.append("    " + _format_signature(sub))
                    sdoc = _doc_first_line(sub)
                    if sdoc:
                        lines.append(f"        # {sdoc}")
                    lines.append("        ...")
                elif isinstance(sub, ast.ClassDef):
                    lines.append(f"    class {sub.name}:")
                    lines.append("        ...")
            lines.append("")
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    lines.append(f"{target.id} = ...")
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id.isupper():
                lines.append(f"{node.target.id} = ...")
    return "\n".join(lines).strip() + "\n"


def _python_outline(source: str) -> str:
    """Outline-depth slice of a Python module: top-level names only,
    with a class's method names in parentheses."""
    tree = ast.parse(source)
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(node.name)
        elif isinstance(node, ast.ClassDef):
            methods = [s.name for s in node.body
                       if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))]
            names.append(node.name + ("(" + ", ".join(methods) + ")" if methods else ""))
    return "\n".join(names) + ("\n" if names else "")


_JS_SIG = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:function\s+[\w$]+|class\s+[\w$]+|const\s+[\w$]+\s*=\s*(?:async\s*)?\()")


def _js_slice(source: str, outline_only: bool) -> str:
    """Parser-lite JS/TS slice: import/export lines and declaration
    lines; signature mode adds a ``...`` body marker, outline does not."""
    out = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "export {", "export type")):
            out.append(stripped)
        elif _JS_SIG.match(line):
            out.append(line.rstrip())
            if not outline_only:
                out.append("    ...")
    return "\n".join(out).strip() + ("\n" if out else "")


def slice_source(rel: str, source: str, mode: str) -> tuple[str, str]:
    """Return (sliced_text, confidence) for the requested mode.

    Modes: "full", "signatures", "outline" (bundle building also
    relies on the head fallback inside this function for languages
    without a slicer). Confidence is "ast" for Python, "parser-lite"
    for JS/TS, and "head" / "head-fallback" for excerpted text, and
    is recorded verbatim in the manifest.
    """
    ext = Path(rel).suffix.lower()
    if mode == "full":
        return source, "full"
    if ext == ".py":
        try:
            if mode == "signatures":
                return _python_signatures(source), "ast"
            if mode == "outline":
                return _python_outline(source), "ast"
        except SyntaxError:
            return "\n".join(source.splitlines()[:40]) + "\n", "head-fallback"
    if ext in (".js", ".ts", ".tsx", ".jsx", ".mjs"):
        return _js_slice(source, outline_only=(mode == "outline")), "parser-lite"
    if mode == "outline":
        return "\n".join(source.splitlines()[:10]) + "\n", "head"
    return "\n".join(source.splitlines()[:40]) + "\n", "head"
