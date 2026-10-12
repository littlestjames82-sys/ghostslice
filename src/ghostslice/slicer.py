"""AST slicer.

Modes: full, signatures, interfaces, strip-tests, exclude.

Python: real parsing with the stdlib `ast` module.
  - signatures: imports, module constants/type aliases, and every
    function/class signature (decorators + first docstring line),
    with bodies replaced by `...`. Class methods are included, indented.
  - interfaces: classes (header + member signatures + class-level
    assignments), type aliases and Protocol/ABC-style class defs.
    Plain top-level functions are dropped.
  - strip-tests: original source with `test_*` / `Test*` definitions
    removed by line range, everything else byte-identical.
  - If the file does not parse, signatures/interfaces fall back to
    keeping definition lines only (documented fallback).

TypeScript/JavaScript: "parser-lite".
  This is NOT a real parser. It is line scanning + regexes + brace
  matching that ignores braces inside strings/comments only
  approximately. It handles the common, conventional shapes:
  `function foo(...) {`, `export const foo = (...) => {`,
  `class Foo { method(...) { ... } }`, `interface Foo { ... }`,
  `type Foo = ...;`, `enum Foo { ... }`, and describe/it/test blocks.
  Exotic syntax (nested template literals with braces, decorators,
  generics spanning many lines) can slice imperfectly. The mode is
  labelled "lite" everywhere it surfaces for that reason.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from .scanner import is_test_file, language_for
from .tokens import estimate_tokens

MODES = ("full", "signatures", "interfaces", "strip-tests", "exclude")


@dataclass
class SliceResult:
    path: str
    mode: str
    language: str
    original_tokens: int
    sliced_tokens: int
    text: str

    @property
    def saved_tokens(self) -> int:
        return self.original_tokens - self.sliced_tokens

    def to_dict(self):
        return {
            "path": self.path, "mode": self.mode, "language": self.language,
            "original_tokens": self.original_tokens,
            "sliced_tokens": self.sliced_tokens,
            "saved_tokens": self.saved_tokens,
            "text": self.text,
        }


def slice_source(source: str, language: str, mode: str, path: str = "") -> str:
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode} (choose from {', '.join(MODES)})")
    if mode == "exclude":
        return ""
    if mode == "full":
        return source
    if mode == "strip-tests" and path and is_test_file(path):
        return ""
    if language == "python":
        return _slice_python(source, mode)
    if language in ("typescript", "javascript"):
        return _slice_ts(source, mode)
    # Other languages: only full / exclude / strip-tests (test files) apply.
    return source


def slice_text(path: str, source: str, mode: str) -> SliceResult:
    lang = language_for(path)
    sliced = slice_source(source, lang, mode, path=path)
    return SliceResult(
        path=path, mode=mode, language=lang,
        original_tokens=estimate_tokens(source),
        sliced_tokens=estimate_tokens(sliced),
        text=sliced,
    )


# ---------------------------------------------------------------------------
# Python (ast)
# ---------------------------------------------------------------------------

def _doc_first_line(node) -> str | None:
    try:
        doc = ast.get_docstring(node)
    except Exception:
        doc = None
    if doc:
        first = doc.strip().splitlines()[0].strip()
        return first
    return None


def _func_signature(node: ast.FunctionDef | ast.AsyncFunctionDef, indent: str = "") -> list[str]:
    out: list[str] = []
    for dec in node.decorator_list:
        out.append(f"{indent}@{ast.unparse(dec)}")
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    args = ast.unparse(node.args)
    ret = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    out.append(f"{indent}{prefix} {node.name}({args}){ret}: ...")
    doc = _doc_first_line(node)
    if doc:
        out[-1] = out[-1].replace(": ...", ":")
        out.append(f'{indent}    """{doc}"""')
        out.append(f"{indent}    ...")
    return out


def _class_signature(node: ast.ClassDef, indent: str = "") -> list[str]:
    out: list[str] = []
    for dec in node.decorator_list:
        out.append(f"{indent}@{ast.unparse(dec)}")
    bases = [ast.unparse(b) for b in node.bases]
    bases += [f"{kw.arg}={ast.unparse(kw.value)}" for kw in node.keywords]
    head = f"{indent}class {node.name}"
    if bases:
        head += f"({', '.join(bases)})"
    head += ":"
    out.append(head)
    inner = indent + "    "
    doc = _doc_first_line(node)
    if doc:
        out.append(f'{inner}"""{doc}"""')
    body_lines: list[str] = []
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if child.name.startswith("__") and child.name.endswith("__") and child.name != "__init__":
                pass  # keep dunders too, they are interface surface
            body_lines.extend(_func_signature(child, inner))
        elif isinstance(child, ast.ClassDef):
            body_lines.extend(_class_signature(child, inner))
        elif isinstance(child, (ast.Assign, ast.AnnAssign)):
            # Class-level attributes are part of the interface/signature surface.
            try:
                body_lines.append(f"{inner}{ast.unparse(child)}")
            except Exception:
                pass
        elif isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant) \
                and isinstance(child.value.value, str):
            continue  # docstring already handled
    if body_lines:
        out.extend(body_lines)
    else:
        out.append(f"{inner}...")
    return out


def _is_type_alias(node) -> bool:
    if isinstance(node, ast.TypeAlias):  # Python 3.12+
        return True
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return True
    if isinstance(node, ast.Assign):
        # X = SomeType / list[...] / Union[...] style alias: value is a Name/Subscript/Call/BinOp
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, (ast.Name, ast.Subscript, ast.BinOp, ast.Call)):
                # Heuristic: capitalised target is treated as a type alias.
                return node.targets[0].id[:1].isupper()
    return False


def _slice_python(source: str, mode: str) -> str:
    if mode == "strip-tests":
        return _py_strip_tests(source)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _py_fallback_defs(source)
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out.append(ast.unparse(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if mode == "signatures":
                out.extend(_func_signature(node))
            # interfaces: plain functions dropped
        elif isinstance(node, ast.ClassDef):
            out.extend(_class_signature(node))
        elif _is_type_alias(node):
            try:
                out.append(ast.unparse(node))
            except Exception:
                pass
        elif mode == "signatures" and isinstance(node, ast.Assign):
            # Module constants read as context in signatures mode.
            try:
                text = ast.unparse(node)
            except Exception:
                continue
            if len(text) <= 200:
                out.append(text)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str) and not out:
            out.append(f'"""{node.value.value.strip().splitlines()[0]}"""' if node.value.value.strip() else '""""""')
    return "\n\n".join(out).strip() + ("\n" if out else "")


def _py_strip_tests(source: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    drop: set[int] = set()

    def collect(body):
        for node in body:
            is_test = False
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                is_test = node.name.startswith("test_")
            elif isinstance(node, ast.ClassDef):
                is_test = node.name.startswith("Test")
                if not is_test:
                    collect(node.body)
            if is_test:
                start = node.lineno
                if node.decorator_list:
                    start = min(d.lineno for d in node.decorator_list)
                for ln in range(start, (node.end_lineno or node.lineno) + 1):
                    drop.add(ln)

    collect(tree.body)
    lines = source.splitlines()
    kept = [ln for i, ln in enumerate(lines, start=1) if i not in drop]
    text = "\n".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text).strip("\n")
    return text + ("\n" if text else "")


def _py_fallback_defs(source: str) -> str:
    kept = [ln for ln in source.splitlines()
            if re.match(r"\s*(def |async def |class |import |from )", ln)]
    return "\n".join(kept) + ("\n" if kept else "")


# ---------------------------------------------------------------------------
# TypeScript / JavaScript (parser-lite)
# ---------------------------------------------------------------------------

def _body_brace_col(line: str) -> int:
    """Column of the opening *body* brace on a declaration line.

    Parameter defaults can contain balanced braces (`meta = {}`), so the
    body brace is the one after the parameter list's closing paren, or
    after `=>` for arrow functions, not the first `{` on the line.
    """
    if "=>" in line:
        idx = line.find("{", line.find("=>"))
        if idx >= 0:
            return idx
    m = re.search(r"\)\s*\{", line)
    if m:
        return m.end() - 1
    return line.find("{")


def _brace_end(lines: list[str], start_idx: int, start_col: int = 0,
               body_col: int | None = None) -> int:
    """Return index of the line where the brace opened at/after start closes."""
    depth = 0
    seen = False
    for i in range(start_idx, len(lines)):
        line = lines[i]
        if i == start_idx and body_col is not None and body_col >= 0:
            j = body_col
        else:
            j = start_col if i == start_idx else 0
        in_str: str | None = None
        while j < len(line):
            ch = line[j]
            if in_str:
                if ch == in_str and line[j - 1] != "\\":
                    in_str = None
            elif ch in ("'", '"', "`"):
                in_str = ch
            elif ch == "{":
                depth += 1
                seen = True
            elif ch == "}":
                depth -= 1
                if seen and depth == 0:
                    return i
            j += 1
        if seen and depth == 0:
            return i
    return len(lines) - 1


def _statement_end(lines: list[str], start_idx: int) -> int:
    for i in range(start_idx, len(lines)):
        if lines[i].rstrip().endswith(";"):
            return i
    return start_idx


_INTERFACE_RE = re.compile(r"^\s*(export\s+)?(declare\s+)?interface\s+\w+")
_TYPE_RE = re.compile(r"^\s*(export\s+)?type\s+\w+")
_ENUM_RE = re.compile(r"^\s*(export\s+)?(declare\s+)?(const\s+)?enum\s+\w+")
_FUNCTION_RE = re.compile(r"^\s*(export\s+)?(default\s+)?(async\s+)?function\s+\w+")
_CLASS_RE = re.compile(r"^\s*(export\s+)?(default\s+)?(abstract\s+)?class\s+\w+")
_ARROW_RE = re.compile(r"^\s*(export\s+)?(const|let|var)\s+\w+\s*(:\s*[^=]+)?=\s*(async\s*)?\(.*\)\s*(:\s*[^=>{]+)?=>\s*\{?")
_IMPORT_RE = re.compile(r"^\s*import\s")
_EXPORT_CONST_RE = re.compile(r"^\s*export\s+(const|let|var)\s+\w+")
_TEST_BLOCK_RE = re.compile(r"^\s*(describe|it|test|suite|context)\s*\(")
_METHOD_RE = re.compile(
    r"^\s*(public\s+|private\s+|protected\s+|static\s+|async\s+|readonly\s+|abstract\s+)*"
    r"(get\s+|set\s+)?[A-Za-z_$][\w$]*\s*\(.*\)\s*(:\s*[^{};]+)?\s*\{")


def _sig_before_body(line: str) -> str:
    """Signature text before the opening body brace.

    Handles object/destructuring defaults: `foo(a = {}) {` keeps the
    whole parameter list, because we cut at the first `) {` (or at a
    trailing `{`), not at the first `{` on the line.
    """
    stripped = line.rstrip()
    if stripped.endswith("{"):
        return stripped[:-1].rstrip()
    m = re.search(r"\)\s*\{", stripped)
    if m:
        return stripped[: m.start() + 1].rstrip()
    return stripped.split("{")[0].rstrip()
_PROP_RE = re.compile(r"^\s*(public\s+|private\s+|protected\s+|static\s+|readonly\s+)*[A-Za-z_$][\w$]*\s*[?!]?\s*:\s*[^;{}]+;\s*$")


def _ts_interface_blocks(lines: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _IMPORT_RE.match(line):
            out.append(line.rstrip())
            i += 1
        elif _INTERFACE_RE.match(line) or _ENUM_RE.match(line):
            end = _brace_end(lines, i, body_col=line.find("{"))
            out.extend(ln.rstrip() for ln in lines[i:end + 1])
            out.append("")
            i = end + 1
        elif _TYPE_RE.match(line):
            if "{" in line and not line.rstrip().endswith(";"):
                end = _brace_end(lines, i, body_col=line.find("{"))
                out.extend(ln.rstrip() for ln in lines[i:end + 1])
            else:
                end = _statement_end(lines, i)
                out.extend(ln.rstrip() for ln in lines[i:end + 1])
            out.append("")
            i = end + 1
        else:
            i += 1
    return out


def _ts_class_signatures(lines: list[str], start: int) -> list[str]:
    end = _brace_end(lines, start, body_col=lines[start].find("{"))
    header = _sig_before_body(lines[start]) + " {"
    out = [header]
    i = start + 1
    while i < end:
        line = lines[i]
        if _METHOD_RE.match(line):
            sig = _sig_before_body(line)
            out.append(sig + " { /* ... */ }")
            i = _brace_end(lines, i, body_col=_body_brace_col(line)) + 1
        elif _PROP_RE.match(line):
            out.append(line.rstrip())
            i += 1
        elif "constructor" in line and "(" in line:
            sig = _sig_before_body(line)
            out.append(sig + (" { /* ... */ }" if "{" in line else ""))
            i = _brace_end(lines, i, body_col=_body_brace_col(line)) + 1 if "{" in line else i + 1
        else:
            i += 1
    out.append("}")
    return out


def _ts_signatures(lines: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _IMPORT_RE.match(line):
            out.append(line.rstrip())
            i += 1
        elif _INTERFACE_RE.match(line) or _ENUM_RE.match(line) or (_TYPE_RE.match(line) and "{" in line):
            end = _brace_end(lines, i, body_col=line.find("{"))
            out.extend(ln.rstrip() for ln in lines[i:end + 1])
            out.append("")
            i = end + 1
        elif _TYPE_RE.match(line):
            end = _statement_end(lines, i)
            out.extend(ln.rstrip() for ln in lines[i:end + 1])
            out.append("")
            i = end + 1
        elif _CLASS_RE.match(line):
            out.extend(_ts_class_signatures(lines, i))
            out.append("")
            i = _brace_end(lines, i, body_col=line.find("{")) + 1
        elif _FUNCTION_RE.match(line):
            sig = _sig_before_body(line)
            out.append(sig + " { /* ... */ }")
            i = _brace_end(lines, i, body_col=_body_brace_col(line)) + 1 if "{" in line else i + 1
        elif _ARROW_RE.match(line):
            sig = line.split("=>")[0].rstrip()
            out.append(sig + " => { /* ... */ };")
            i = _brace_end(lines, i, body_col=_body_brace_col(line)) + 1 if "{" in line else i + 1
        elif _EXPORT_CONST_RE.match(line) and "=>" not in line:
            end = _statement_end(lines, i)
            stmt = " ".join(ln.strip() for ln in lines[i:end + 1])
            out.append(stmt[:200])
            i = end + 1
        else:
            i += 1
    return out


def _ts_strip_tests(lines: list[str]) -> str:
    drop: set[int] = set()
    i = 0
    while i < len(lines):
        if _TEST_BLOCK_RE.match(lines[i]):
            end = _brace_end(lines, i, body_col=_body_brace_col(lines[i])) if "{" in "".join(lines[i:i + 3]) else i
            # describe/it may open its brace on a following line; extend search.
            if end == i:
                for k in range(i, min(i + 3, len(lines))):
                    if "{" in lines[k]:
                        end = _brace_end(lines, k, body_col=_body_brace_col(lines[k]))
                        break
            for ln in range(i, end + 1):
                drop.add(ln)
            i = end + 1
        else:
            i += 1
    kept = [ln for idx, ln in enumerate(lines) if idx not in drop]
    text = "\n".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text).strip("\n")
    return text + ("\n" if text else "")


def _slice_ts(source: str, mode: str) -> str:
    lines = source.splitlines()
    if mode == "strip-tests":
        return _ts_strip_tests(lines)
    if mode == "interfaces":
        out = _ts_interface_blocks(lines)
    elif mode == "signatures":
        out = _ts_signatures(lines)
    else:
        return source
    text = "\n".join(out).strip()
    return text + ("\n" if text else "")
