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
  matching that is string/comment aware since v0.4 (braces inside
  strings, template literals, and // or /* */ comments do not count;
  braces inside regex literals can still confuse it). It handles the
  common, conventional shapes:
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

MODES = ("full", "signatures", "interfaces", "strip-tests", "exclude", "headings")


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
    if mode == "headings" and language not in ("markdown", "notebook"):
        return source  # headings is a docs/notebook mode; other files stay full
    if language == "python":
        return _slice_python(source, mode)
    if language == "notebook":
        return _slice_notebook(source, mode, path)
    if language == "markdown":
        if mode == "headings":
            return _slice_markdown_headings(source)
        if mode in ("signatures", "interfaces"):
            return _slice_markdown_headings(source)
        if mode == "strip-tests":
            return source
        return source
    if language in ("typescript", "javascript"):
        return _slice_ts(source, mode)
    if language in ("go", "rust", "java", "csharp"):
        return _slice_brace_lite(source, mode, language, path)
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
    type_alias = getattr(ast, "TypeAlias", None)  # Python 3.12+ only
    if type_alias is not None and isinstance(node, type_alias):
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


def _is_char_literal(line: str, j: int) -> bool:
    """Heuristic for Go/Rust/Java/C# single quotes: `'a'`, `'\\n'`, `'{'`
    are char literals, while Rust lifetimes (`'a`, `'static`) are not.
    Returns True when the quote at j opens a short char literal."""
    rest = line[j + 1:j + 6]
    if rest.startswith("\\") and len(rest) >= 3 and rest[2] == "'":
        return True
    return len(rest) >= 2 and rest[1] == "'" and rest[0] not in ("'", "\\")


def _brace_end(lines: list[str], start_idx: int, start_col: int = 0,
               body_col: int | None = None, lang: str = "") -> int:
    """Return index of the line where the brace opened at/after start closes.

    String/comment aware (v0.4): braces inside '...', "...", `...`
    template literals (including ${...} interpolation and multi-line
    templates), // line comments and /* ... */ block comments do not
    affect depth. State persists across lines. Remaining parser-lite
    limits: regex literals containing braces (e.g. /}/) and nested
    backticks inside ${...} expressions can still confuse the count.
    For Go/Rust/Java/C# (lang set), single quotes use a char-literal
    heuristic so Rust lifetimes do not open a phantom string.
    """
    depth = 0
    seen = False
    state: str | None = None  # "'", '"', '`', 'line', 'block'
    escaped = False
    interp: list[int] = []  # depths at which a template ${ opened
    char_langs = lang in ("go", "rust", "java", "csharp")
    for i in range(start_idx, len(lines)):
        line = lines[i]
        if i == start_idx and body_col is not None and body_col >= 0:
            j = body_col
        else:
            j = start_col if i == start_idx else 0
        while j < len(line):
            ch = line[j]
            nxt = line[j + 1] if j + 1 < len(line) else ""
            if state == "line":
                break
            if state == "block":
                if ch == "*" and nxt == "/":
                    state = None
                    j += 2
                    continue
                j += 1
                continue
            if state in ("'", '"', "`"):
                if escaped:
                    escaped = False
                    j += 1
                    continue
                if ch == "\\" and state != "`":
                    escaped = True
                    j += 1
                    continue
                if state == "`" and ch == "$" and nxt == "{":
                    interp.append(depth)
                    depth += 1
                    seen = True
                    state = None
                    j += 2
                    continue
                if ch == state:
                    state = None
                j += 1
                continue
            # code state
            if ch == "/" and nxt == "/":
                state = "line"
                break
            if ch == "/" and nxt == "*":
                state = "block"
                j += 2
                continue
            if ch in ("'", '"', "`"):
                if ch == "'" and char_langs and not _is_char_literal(line, j):
                    j += 1
                    continue
                state = ch
                j += 1
                continue
            if ch == "{":
                depth += 1
                seen = True
            elif ch == "}":
                depth -= 1
                if interp and depth == interp[-1]:
                    interp.pop()
                    state = "`"
                    j += 1
                    continue
                if seen and depth == 0:
                    return i
            j += 1
        if state == "line":
            state = None
        escaped = False
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


# ---------------------------------------------------------------------------
# Go / Rust / Java / C# (parser-lite, v0.3)
#
# Same honesty label as TS: line scanning + brace matching for
# conventional formatting (one declaration per line, opening brace on
# the declaration line). Guaranteed mode is `signatures`; `interfaces`
# keeps type declarations (Go/Rust: struct/interface/trait/enum blocks
# in full; Java/C#: interface/enum in full, classes reduced to member
# signatures). `strip-tests` removes test files wholesale (handled in
# slice_source) and test functions/blocks:
#   Go:   func TestXxx / BenchmarkXxx / ExampleXxx
#   Rust: #[test] functions and `mod tests { ... }` blocks
#   Java: @Test methods
#   C#:   [Test] / [Fact] / [Theory] methods
# ---------------------------------------------------------------------------

_GO_FUNC_RE = re.compile(r"^\s*func\s+(\([^)]*\)\s*)?[A-Za-z_]\w*\s*\(")
_GO_TYPE_RE = re.compile(r"^\s*type\s+[A-Za-z_]\w*\s+(struct|interface)\b")
_RS_FN_RE = re.compile(r"^\s*(#\[.*\]\s*)?(pub(\s*\([^)]*\))?\s+)?(async\s+|unsafe\s+|const\s+)*fn\s+[A-Za-z_]\w*\s*[<(]")
_RS_TYPE_RE = re.compile(r"^\s*(pub(\s*\([^)]*\))?\s+)?(struct|enum|trait|union)\s+[A-Za-z_]\w*")
_RS_IMPL_RE = re.compile(r"^\s*(unsafe\s+)?impl\b")
_JV_TYPE_RE = re.compile(r"^\s*(public\s+|private\s+|protected\s+|abstract\s+|final\s+|static\s+|sealed\s+|partial\s+|async\s+|unsafe\s+|readonly\s+|ref\s+)*(class|interface|enum|record|struct)\s+[A-Za-z_]\w*")
_JV_METHOD_RE = re.compile(r"^\s*(public\s+|private\s+|protected\s+|internal\s+|static\s+|abstract\s+|virtual\s+|override\s+|sealed\s+|async\s+|final\s+|synchronized\s+|native\s+|extern\s+|new\s+)*[A-Za-z_][\w<>\[\],.? ]*\s+[A-Za-z_]\w*\s*\(.*\)\s*(throws\s+[\w, ]+)?[{;]\s*$")
_IMPORT_LINE_RES = {
    "go": re.compile(r"^\s*(package|import)\b"),
    "rust": re.compile(r"^\s*(use|mod|extern\s+crate)\b"),
    "java": re.compile(r"^\s*(package|import)\b"),
    "csharp": re.compile(r"^\s*(using|namespace)\b"),
}
_TEST_FN_RES = {
    "go": re.compile(r"^\s*func\s+(Test|Benchmark|Example|Fuzz)[A-Z]\w*\s*\("),
    "java": re.compile(r"^\s*@Test\b"),
    "csharp": re.compile(r"^\s*\[(Test|Fact|Theory|TestMethod|TestCase)\b"),
}


def _block_end(lines, start, lang=""):
    return _brace_end(lines, start, body_col=lines[start].find("{"), lang=lang)


def _lite_type_kind(line: str, lang: str) -> str | None:
    if lang == "go":
        m = _GO_TYPE_RE.match(line)
        return m.group(1) if m else None
    if lang == "rust":
        if _RS_TYPE_RE.match(line):
            m = re.search(r"\b(struct|enum|trait|union)\s+[A-Za-z_]\w*", line)
            return m.group(1) if m else None
        return None
    m = _JV_TYPE_RE.match(line)
    return m.group(2) if m else None


def _lite_is_func(line: str, lang: str) -> bool:
    if lang == "go":
        return bool(_GO_FUNC_RE.match(line))
    if lang == "rust":
        return bool(_RS_FN_RE.match(line))
    return bool(_JV_METHOD_RE.match(line)) and not _JV_TYPE_RE.match(line)


def _lite_keep_full_type(kind: str | None, lang: str, mode: str) -> bool:
    if kind is None:
        return False
    if mode == "interfaces":
        return True
    # signatures: declaration-style types are surface in Go/Rust; Java/C#
    # classes are reduced to member signatures instead.
    if lang in ("go", "rust"):
        return True
    return kind in ("interface", "enum", "record")


def _lite_class_members(lines, start, lang):
    """Member signatures of a class/impl block starting at `start`."""
    end = _block_end(lines, start, lang)
    header = _sig_before_body(lines[start]) + " {"
    out = [header]
    i = start + 1
    while i < end:
        line = lines[i]
        stripped = line.strip()
        if _lite_is_func(line, lang):
            if "{" in line:
                out.append(_sig_before_body(line) + " { /* ... */ }")
                i = _block_end(lines, i, lang) + 1
            else:  # abstract / interface method ending in ;
                out.append(line.rstrip())
                i += 1
        elif _lite_type_kind(line, lang) or _JV_TYPE_RE.match(line):
            kind = _lite_type_kind(line, lang)
            if "{" in line and _lite_keep_full_type(kind, lang, "signatures"):
                bend = _block_end(lines, i, lang)
                out.extend(ln.rstrip() for ln in lines[i:bend + 1])
                i = bend + 1
            elif "{" in line:
                sub, nxt = _lite_class_members(lines, i, lang)
                out.extend(sub)
                i = nxt
            else:
                out.append(line.rstrip())
                i += 1
        elif lang == "rust" and _RS_IMPL_RE.match(line):
            sub, nxt = _lite_class_members(lines, i, lang)
            out.extend(sub)
            i = nxt
        elif stripped.endswith(";") and "(" not in stripped:
            out.append(line.rstrip())  # field / constant
            i += 1
        elif stripped.startswith("#[") or stripped.startswith("@"):
            out.append(line.rstrip())
            i += 1
        else:
            i += 1
    out.append("}")
    return out, end + 1


def _lite_signatures(lines, lang, mode):
    out: list[str] = []
    imp_re = _IMPORT_LINE_RES[lang]
    i = 0
    while i < len(lines):
        line = lines[i]
        kind = _lite_type_kind(line, lang) or (("class" if _JV_TYPE_RE.match(line) else None)
                if lang in ("java", "csharp") else None)
        if lang == "csharp" and re.match(r"^\s*namespace\s+[\w.]+\s*\{", line):
            if mode == "interfaces":
                sub, nxt = _lite_class_members(lines, i, lang)
                # keep interface/enum members only is overkill here; namespace
                # members were signature-reduced, which matches the class rule.
                out.extend(sub); out.append(""); i = nxt
            else:
                sub, nxt = _lite_class_members(lines, i, lang)
                out.extend(sub); out.append(""); i = nxt
        elif imp_re.match(line):
            if "(" in line and "{" not in line and lang == "go" and line.rstrip().endswith("("):
                # go import ( ... ) block: copy until closing paren
                j = i
                while j < len(lines) and lines[j].strip() != ")":
                    out.append(lines[j].rstrip()); j += 1
                if j < len(lines):
                    out.append(lines[j].rstrip())
                i = j + 1
            else:
                out.append(line.rstrip())
                i += 1
        elif kind and "{" in line and _lite_keep_full_type(kind, lang, mode):
            end = _block_end(lines, i, lang)
            out.extend(ln.rstrip() for ln in lines[i:end + 1])
            out.append("")
            i = end + 1
        elif (kind or (lang == "rust" and _RS_IMPL_RE.match(line))) and "{" in line:
            if mode == "interfaces" and lang in ("java", "csharp") and kind == "class":
                sub, nxt = _lite_class_members(lines, i, lang)
                out.extend(sub); out.append(""); i = nxt
            elif mode == "interfaces":
                i = _block_end(lines, i, lang) + 1  # impl/class bodies are not interfaces in go/rust
            else:
                sub, nxt = _lite_class_members(lines, i, lang)
                out.extend(sub); out.append(""); i = nxt
        elif _lite_is_func(line, lang):
            if mode == "interfaces" and lang in ("go", "rust"):
                i = _block_end(lines, i, lang) + 1 if "{" in line else i + 1
            elif "{" in line:
                sig = _sig_before_body(line)
                out.append(sig + (" { /* ... */ }" if lang != "go" else " { /* ... */ }"))
                i = _block_end(lines, i, lang) + 1
            else:
                out.append(line.rstrip())
                i = _statement_end(lines, i) + 1
        elif mode == "signatures" and line.strip().endswith(";") and "(" not in line:
            out.append(line.rstrip())  # top-level const/var/type alias
            i += 1
        elif mode == "signatures" and lang == "rust" and re.match(r"^\s*(pub\s+)?(type|static|const)\b", line):
            out.append(line.rstrip())
            i += 1
        else:
            i += 1
    return out


def _lite_strip_tests(lines, lang, source):
    if lang == "rust":
        drop: set[int] = set()
        i = 0
        while i < len(lines):
            if re.match(r"^\s*mod\s+tests\s*\{", lines[i]) or \
               (re.match(r"^\s*#\[cfg\(test\)\]", lines[i]) and i + 1 < len(lines)
                    and "{" in lines[i + 1]):
                start = i + 1 if lines[i].lstrip().startswith("#[") else i
                end = _block_end(lines, start, lang) if "{" in lines[start] else i
                for ln in range(i, end + 1):
                    drop.add(ln)
                i = end + 1
            elif re.match(r"^\s*#\[test\]", lines[i]):
                j = i + 1
                while j < len(lines) and not _RS_FN_RE.match(lines[j]):
                    j += 1
                if j < len(lines):
                    end = _block_end(lines, j, lang) if "{" in lines[j] else j
                    for ln in range(i, end + 1):
                        drop.add(ln)
                    i = end + 1
                else:
                    i += 1
            else:
                i += 1
        kept = [ln for idx, ln in enumerate(lines) if idx not in drop]
        text = "\n".join(kept)
        text = re.sub(r"\n{3,}", "\n\n", text).strip("\n")
        return text + ("\n" if text else "")
    # go / java / csharp: drop annotated or conventionally named test functions
    test_re = _TEST_FN_RES.get(lang)
    if test_re is None:
        return source
    drop: set[int] = set()
    i = 0
    while i < len(lines):
        if test_re.match(lines[i]):
            if lang == "go":
                start = i
            else:
                # annotation line: the method follows within a few lines
                start = i
                j = i
                while j < min(i + 4, len(lines)) and "{" not in lines[j] and not lines[j].rstrip().endswith(";"):
                    j += 1
                end = _block_end(lines, j, lang) if j < len(lines) and "{" in lines[j] else start
                for ln in range(start, end + 1):
                    drop.add(ln)
                i = end + 1
                continue
            end = _block_end(lines, start, lang) if "{" in lines[start] else start
            for ln in range(start, end + 1):
                drop.add(ln)
            i = end + 1
        else:
            i += 1
    kept = [ln for idx, ln in enumerate(lines) if idx not in drop]
    text = "\n".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text).strip("\n")
    return text + ("\n" if text else "")


def _slice_brace_lite(source: str, mode: str, lang: str, path: str = "") -> str:
    lines = source.splitlines()
    if mode == "strip-tests":
        return _lite_strip_tests(lines, lang, source)
    if mode in ("signatures", "interfaces"):
        out = _lite_signatures(lines, lang, mode)
        text = "\n".join(out).strip()
        return text + ("\n" if text else "")
    return source


# ---------------------------------------------------------------------------
# Jupyter notebooks (.ipynb) — stdlib json parsing (v0.4)
#
# A notebook is JSON: cells with cell_type + source. Slicing returns a
# *text* rendering (GhostSlice bundles are text), not re-serialised JSON:
#   signatures / full-ish : code cells' source only — outputs and
#       execution counts are never included (they live outside `source`,
#       so they are stripped by construction); markdown cells are kept
#       as `#`-prefixed comments so narrative survives.
#   interfaces: same rendering (notebooks have no separate interface
#       surface; documented, not a distinct algorithm).
#   strip-tests: code cells mentioning test markers (test_, assert in a
#       test-named cell, `pytest`, `unittest`) are dropped.
#   headings: markdown headings + code cell first lines as comments.
# Malformed notebooks never crash: unparsable JSON returns the source
# unchanged for full, and "" for reducing modes with the raw text kept
# only under full.
# ---------------------------------------------------------------------------

def _nb_cell_source(cell) -> str:
    src = cell.get("source", "")
    if isinstance(src, list):
        return "".join(str(s) for s in src)
    return str(src or "")


def _slice_notebook(source: str, mode: str, path: str = "") -> str:
    import json as _json
    try:
        nb = _json.loads(source)
        cells = nb.get("cells")
        if not isinstance(cells, list):
            raise ValueError("no cells")
    except Exception:
        return source if mode == "full" else ""
    parts: list[str] = []
    for idx, cell in enumerate(cells):
        if not isinstance(cell, dict):
            continue
        ctype = cell.get("cell_type", "")
        text = _nb_cell_source(cell).rstrip()
        if mode == "strip-tests":
            low = text.lower()
            if ctype == "code" and ("def test_" in low or "pytest" in low
                                    or "unittest" in low or low.lstrip().startswith("test")):
                continue
        if ctype == "markdown":
            if mode == "headings":
                for ln in text.splitlines():
                    if ln.lstrip().startswith("#"):
                        parts.append(ln)
                continue
            commented = "\n".join(f"# {ln}" if ln else "#" for ln in text.splitlines())
            parts.append(commented)
        elif ctype == "code":
            if not text:
                continue
            if mode == "headings":
                first = text.splitlines()[0] if text.splitlines() else ""
                parts.append(f"# %% cell {idx}: {first}")
            else:
                parts.append(f"# %% cell {idx}\n{text}")
        elif ctype == "raw":
            continue
    out = "\n\n".join(p for p in parts if p).strip()
    return out + ("\n" if out else "")


# ---------------------------------------------------------------------------
# Markdown headings mode (v0.4)
#
# Keeps every ATX heading plus the first paragraph (first run of
# non-blank lines) directly under it, plus any content before the
# first heading's first paragraph. Fenced code blocks under a heading
# are not treated as its paragraph.
# ---------------------------------------------------------------------------

def _slice_markdown_headings(source: str) -> str:
    lines = source.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)
    # Preamble: keep lines up to and including first paragraph.
    while i < n and not lines[i].lstrip().startswith("#"):
        out.append(lines[i])
        i += 1
        if i < n and not lines[i - 1].strip() and out and any(l.strip() for l in out):
            break
    while i < n:
        line = lines[i]
        if line.lstrip().startswith("#"):
            out.append(line)
            i += 1
            # skip blank lines, keep them minimal
            while i < n and not lines[i].strip():
                i += 1
            # first paragraph: consecutive non-blank, non-heading lines
            para: list[str] = []
            in_fence = False
            while i < n and lines[i].strip() and not lines[i].lstrip().startswith("#"):
                if lines[i].lstrip().startswith("```"):
                    if not para:
                        break
                    in_fence = not in_fence
                para.append(lines[i])
                i += 1
            out.extend(para)
            out.append("")
        else:
            i += 1
    text = "\n".join(out).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text + ("\n" if text else "")
