"""Slicing to GhostSlice modes: full / signatures / interfaces /
strip-tests / exclude.

Python uses stdlib ast line spans. Other slicable languages use a
parser-lite line approach (imports kept, declaration lines kept,
interface/type blocks kept in full for interfaces mode). Text-like
files only support full/exclude; signatures/interfaces degrade to
full for them and the caller records that.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from .scanner import language_for
from .tokens import estimate_tokens

MODES = ("full", "signatures", "interfaces", "strip-tests", "exclude", "headings")

SLICABLE = {"python", "typescript", "javascript", "go", "rust", "java",
            "csharp", "php", "ruby", "kotlin", "swift", "c", "cpp", "scala"}


@dataclass
class SliceResult:
    path: str
    mode: str
    language: str
    original_tokens: int
    sliced_tokens: int
    text: str


def _doc_first_line(node) -> str | None:
    try:
        doc = ast.get_docstring(node)
    except Exception:
        doc = None
    if doc:
        return doc.splitlines()[0]
    return None


def _py_signature_lines(node, lines: list[str]) -> list[str]:
    start = node.lineno - 1
    # the signature runs from the def/class line to the line ending
    # with ':' at paren depth 0; ast gives us body start instead.
    body_start = node.body[0].lineno - 1 if node.body else node.end_lineno
    sig: list[str] = []
    for i in range(start, min(body_start, len(lines))):
        sig.append(lines[i])
        if lines[i].rstrip().endswith(":") and not any(
                d.lineno - 1 == i for d in getattr(node, "decorator_list", [])):
            break
    else:
        sig = [lines[start]] if start < len(lines) else []
    doc = _doc_first_line(node)
    indent = " " * (node.col_offset + 4)
    if doc:
        sig.append(f'{indent}"""{doc}"""')
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        sig.append(f"{indent}...")
    return sig


def _py_slice(source: str, mode: str) -> str:
    if mode == "full":
        return source
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source if mode != "exclude" else ""
    lines = source.splitlines()

    if mode == "strip-tests":
        drop: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name
                if name.startswith("test_") or name.startswith("Test"):
                    for i in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                        drop.add(i)
        kept = [ln for i, ln in enumerate(lines, 1) if i not in drop]
        return "\n".join(kept) + ("\n" if kept else "")

    if mode == "interfaces":
        out: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                out.extend(_py_signature_lines(node, lines))
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        out.extend("    " + ln if ln else ln
                                   for ln in _py_signature_lines(child, lines))
                out.append("")
            elif isinstance(node, ast.Assign) and node.targets and \
                    isinstance(node.targets[0], ast.Name) and \
                    node.targets[0].id[:1].isupper():
                for i in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                    out.append(lines[i - 1])
        return "\n".join(out) + ("\n" if out else "")

    # signatures
    out = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign)):
            for i in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                out.append(lines[i - 1])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in node.decorator_list:
                out.append(lines[d.lineno - 1])
            out.extend(_py_signature_lines(node, lines))
            out.append("")
        elif isinstance(node, ast.ClassDef):
            for d in node.decorator_list:
                out.append(lines[d.lineno - 1])
            out.extend(_py_signature_lines(node, lines))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.extend(_py_signature_lines(child, lines))
                elif isinstance(child, ast.Assign):
                    for i in range(child.lineno,
                                   (child.end_lineno or child.lineno) + 1):
                        out.append(lines[i - 1])
            out.append("")
    return "\n".join(out) + ("\n" if out else "")


_LITE_IMPORT = re.compile(r"^\s*(import|from|require\(|#include|using|package)\b")
_LITE_DECL = re.compile(
    r"^\s*(export\s+)?(default\s+)?(async\s+)?(function|class|interface|type|enum|"
    r"const\s+\w+\s*=\s*(async\s*)?\(|func|def|fn|pub\s+fn|public|private|protected)")
_LITE_TYPE_START = re.compile(r"^\s*(export\s+)?(interface|type|enum)\b")


def _lite_slice(source: str, mode: str) -> str:
    if mode == "full":
        return source
    lines = source.splitlines()
    if mode == "strip-tests":
        return source  # test-block stripping for lite languages is out of scope
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _LITE_IMPORT.match(line):
            out.append(line)
            i += 1
            continue
        if mode == "interfaces" and _LITE_TYPE_START.match(line):
            depth = 0
            while i < len(lines):
                out.append(lines[i])
                depth += lines[i].count("{") - lines[i].count("}")
                i += 1
                if depth <= 0:
                    break
            out.append("")
            continue
        if mode == "interfaces":
            if _LITE_CLASS_HEAD.match(line):
                out.append(line)
            i += 1
            continue
        if _LITE_DECL.match(line):
            out.append(line.rstrip() + ("" if line.rstrip().endswith(("{", ":", ";")) else ""))
            i += 1
            continue
        i += 1
    return "\n".join(out) + ("\n" if out else "")


_LITE_CLASS_HEAD = re.compile(r"^\s*(export\s+)?(default\s+)?(abstract\s+)?class\s+\w+")


def _md_headings(source: str) -> str:
    out: list[str] = []
    para_taken = False
    for line in source.splitlines():
        if line.lstrip().startswith("#"):
            out.append(line)
            para_taken = False
        elif line.strip() and not para_taken:
            out.append(line)
            para_taken = True
    return "\n".join(out) + ("\n" if out else "")


def slice_source(source: str, language: str, mode: str) -> str:
    if mode == "exclude":
        return ""
    if mode == "full":
        return source
    if language == "markdown" and mode in ("headings", "signatures", "interfaces"):
        return _md_headings(source)
    if mode == "headings":
        return source
    if language == "python":
        return _py_slice(source, mode)
    if language in SLICABLE:
        return _lite_slice(source, mode)
    return source


def slice_text(path: str, source: str, mode: str) -> SliceResult:
    lang = language_for(path)
    sliced = slice_source(source, lang, mode)
    return SliceResult(
        path=path, mode=mode, language=lang,
        original_tokens=estimate_tokens(source, lang),
        sliced_tokens=estimate_tokens(sliced, lang),
        text=sliced,
    )
