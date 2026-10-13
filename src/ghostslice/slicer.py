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

Go/Rust/Java/C# (v0.3), PHP/Kotlin/Swift (v0.5): the same line-scan +
brace-matching approach, reusing the string/comment-aware brace
matcher. Ruby (v0.5): no braces to match, so blocks are tracked by
opener keywords and closing `end` lines (indent-conventional Ruby).

C/C++/Scala (v0.8): same parser-lite approach again. C keeps `#include`
and other preprocessor lines as surface and treats struct/union/enum/
typedef declarations as interface surface; C++ adds classes with
member signatures, namespaces, and single-line template heads; Scala
adds def/val/var signatures and class/object/trait declarations.
The shared brace matcher gained, gated to these languages only:
C/C++ preprocessor lines (and their backslash continuations) are
never brace-counted, C++ raw strings R"delim(...)delim" are consumed
whole, C++ digit separators (1'000'000) do not open char literals,
and Scala block comments nest while `triple-quoted` strings and
s"...${...}" interpolation are honoured. Scala 3 significant-
indentation style (no braces) is handled by an indentation-based
fallback that degrades to keeping more, never less.
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
    if language == "ruby":
        return _slice_ruby(source, mode, path)
    if language in ("php", "kotlin", "swift"):
        return _slice_brace_extra(source, mode, language, path)
    if language in ("c", "cpp"):
        return _slice_c_family(source, mode, language, path)
    if language == "scala":
        return _slice_scala(source, mode, path)
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
    templates), // line comments and /* ... */ comments do not
    affect depth. State persists across lines. Remaining parser-lite
    limits: regex literals containing braces (e.g. /}/) and nested
    backticks inside ${...} expressions can still confuse the count.
    For Go/Rust/Java/C#/Kotlin/Swift (lang set), single quotes use a
    char-literal heuristic so Rust lifetimes do not open a phantom
    string (and Swift apostrophes in code are not string delimiters).

    v0.8 additions, each gated to the new languages so the languages
    above are byte-for-byte unaffected:
    - c/cpp: lines whose first non-space char is `#` (and their
      backslash-continuation lines) are preprocessor, never scanned:
      braces in macro definitions cannot corrupt the count.
    - cpp: raw strings R"delim( ... )delim" (also u8R/uR/UR/LR) are
      consumed whole; their contents may hold quotes and braces.
    - c/cpp: a `'` between two digits is a digit separator
      (1'000'000), never a char literal.
    - scala: /* */ comments nest; triple-quoted strings are consumed
      whole; s"..." / striple-quoted ${...} interpolation counts braces
      like code ($$ is an escaped dollar, ignored).
    """
    depth = 0
    seen = False
    state: str | None = None  # "'", '"', '`', '"""', 'line', 'block', 'raw'
    escaped = False
    interp: list[tuple[int, str]] = []  # (depth at ${ open, string state to resume)
    block_depth = 0
    raw_term = ""
    pp_cont = False
    char_langs = lang in ("go", "rust", "java", "csharp", "kotlin", "swift",
                          "c", "cpp", "scala")
    for i in range(start_idx, len(lines)):
        line = lines[i]
        if i == start_idx and body_col is not None and body_col >= 0:
            j = body_col
        else:
            j = start_col if i == start_idx else 0
        if lang in ("c", "cpp") and state is None:
            # Preprocessor line (or macro continuation): never scanned.
            if pp_cont or line.lstrip().startswith("#"):
                pp_cont = line.rstrip().endswith("\\")
                if seen and depth == 0:
                    return i
                continue
            pp_cont = False
        while j < len(line):
            ch = line[j]
            nxt = line[j + 1] if j + 1 < len(line) else ""
            if state == "line":
                break
            if state == "raw":
                idx = line.find(raw_term, j)
                if idx < 0:
                    j = len(line)
                    continue
                state = None
                j = idx + len(raw_term)
                continue
            if state == "block":
                if lang == "scala" and ch == "/" and nxt == "*":
                    block_depth += 1
                    j += 2
                    continue
                if ch == "*" and nxt == "/":
                    block_depth -= 1
                    if block_depth <= 0:
                        state = None
                    j += 2
                    continue
                j += 1
                continue
            if state in ("'", '"', "`", '"""'):
                if escaped:
                    escaped = False
                    j += 1
                    continue
                if ch == "\\" and state not in ("`", '"""'):
                    escaped = True
                    j += 1
                    continue
                if lang == "scala" and state in ('"', '"""') and ch == "$" and nxt == "$":
                    j += 2
                    continue
                if (state == "`" or (lang == "scala" and state in ('"', '"""'))) \
                        and ch == "$" and nxt == "{":
                    interp.append((depth, state))
                    depth += 1
                    seen = True
                    state = None
                    j += 2
                    continue
                if state == '"""':
                    if line[j:j + 3] == '"""':
                        state = None
                        j += 3
                    else:
                        j += 1
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
                block_depth = 1
                j += 2
                continue
            if lang == "cpp" and ch == '"' and \
                    re.search(r"(?:^|[^\w])(?:u8|u|U|L)?R$", line[:j]):
                # Possible raw string: delimiter runs to the first '('.
                k = j + 1
                while k < len(line) and line[k] != "(" and k - j <= 16 \
                        and line[k] not in ' )\\"':
                    k += 1
                if k < len(line) and line[k] == "(":
                    state = "raw"
                    raw_term = ")" + line[j + 1:k] + '"'
                    j = k + 1
                    continue
            if lang == "scala" and ch == '"' and line[j:j + 3] == '"""':
                state = '"""'
                j += 3
                continue
            if ch in ("'", '"', "`"):
                if ch == "'" and lang in ("c", "cpp") and j > 0 \
                        and line[j - 1].isdigit() and nxt.isdigit():
                    j += 1  # digit separator, e.g. 1'000'000
                    continue
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
                if interp and depth == interp[-1][0]:
                    state = interp.pop()[1]
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


# ---------------------------------------------------------------------------
# PHP / Kotlin / Swift (parser-lite, v0.5) and Ruby (parser-lite, v0.5)
#
# Same honesty label as the other lite slicers: line scanning + the
# string/comment-aware brace matcher (PHP/Kotlin/Swift) or indent +
# keyword block matching (Ruby, which has no braces for defs).
# Conventional formatting only: one declaration per line, opening
# brace on the declaration line, Ruby blocks closed by `end` at the
# opener's indent.
#   PHP:   function/class/interface/trait/enum; strip-tests drops
#          test-prefixed methods, /** @test */ docblock methods and
#          #[Test] attribute methods.
#   Ruby:  def/class/module, attr_*/include lines, constants;
#          strip-tests drops `def test_*` and describe/context/it
#          blocks.
#   Kotlin: fun/class/interface/object; strip-tests drops @Test
#          functions and test-prefixed functions.
#   Swift: func/class/struct/protocol/enum/extension; strip-tests
#          drops test-prefixed XCTest-style functions and @Test
#          (swift-testing) functions.
# `interfaces` keeps interface/protocol/trait declarations in full and
# reduces classes to member signatures; `signatures` also keeps
# top-level function signatures.
# ---------------------------------------------------------------------------

_EXTRA_CFG = {
    "php": {
        "import": re.compile(r"^\s*(<\?php|declare\s*\(|namespace\s|use\s)"),
        "type": re.compile(r"^\s*(abstract\s+|final\s+|readonly\s+)?(class|interface|trait|enum)\s+\w+"),
        "func": re.compile(r"^\s*(public\s+|private\s+|protected\s+|static\s+|abstract\s+|final\s+)*function\s+&?\w+\s*\("),
        "func_name": re.compile(r"function\s+&?(\w+)\s*\("),
        "prop": re.compile(r"^\s*(public\s+|private\s+|protected\s+|static\s+|readonly\s+|var\s+)[^()]*;\s*$"),
        "const": re.compile(r"^\s*(public\s+|private\s+|protected\s+)?const\s+\w+[^()]*;\s*$"),
        "full_kinds": {"interface", "trait"},
    },
    "kotlin": {
        "import": re.compile(r"^\s*(package|import)\b"),
        "type": re.compile(r"^\s*(public\s+|private\s+|protected\s+|internal\s+|open\s+|final\s+|abstract\s+|sealed\s+|data\s+|enum\s+|annotation\s+|inner\s+)*(class|interface|object)\s+[\w`]+"),
        "func": re.compile(r"^\s*(public\s+|private\s+|protected\s+|internal\s+|open\s+|final\s+|abstract\s+|override\s+|suspend\s+|inline\s+|tailrec\s+|operator\s+|infix\s+)*fun\s+(<[^>]*>\s*)?[\w`]+\s*\("),
        "func_name": re.compile(r"fun\s+(?:<[^>]*>\s*)?`?(\w+)`?\s*\("),
        "prop": re.compile(r"^\s*(public\s+|private\s+|protected\s+|internal\s+|open\s+|final\s+|abstract\s+|override\s+|lateinit\s+|const\s+)*(val|var)\s+\w+"),
        "const": None,
        "full_kinds": {"interface"},
    },
    "swift": {
        "import": re.compile(r"^\s*import\s+\w+"),
        "type": re.compile(r"^\s*(public\s+|private\s+|fileprivate\s+|internal\s+|open\s+|final\s+)*(class|struct|protocol|enum|extension|actor)\s+\w+"),
        "func": re.compile(r"^\s*(public\s+|private\s+|fileprivate\s+|internal\s+|open\s+|final\s+|static\s+|class\s+|override\s+|mutating\s+|nonmutating\s+|convenience\s+|required\s+)*func\s+\w+\s*[<(]"),
        "func_name": re.compile(r"func\s+(\w+)\s*[<(]"),
        "prop": re.compile(r"^\s*(public\s+|private\s+|fileprivate\s+|internal\s+|open\s+|final\s+|static\s+|class\s+|lazy\s+|weak\s+|unowned\s+)*(var|let)\s+\w+\s*[:=]"),
        "const": None,
        "full_kinds": {"protocol"},
    },
}


def _extra_block_end(lines, start, lang):
    return _brace_end(lines, start, body_col=lines[start].find("{"), lang=lang)


def _extra_class_members(lines, start, lang, cfg):
    """Member signatures of a class-like block starting at `start`."""
    end = _extra_block_end(lines, start, lang)
    header = _sig_before_body(lines[start]) + " {"
    out = [header]
    i = start + 1
    while i < end:
        line = lines[i]
        stripped = line.strip()
        tm = cfg["type"].match(line)
        if stripped.startswith("@") or stripped.startswith("#["):
            out.append(line.rstrip())
            i += 1
        elif cfg["func"].match(line):
            if "{" in line:
                out.append(_sig_before_body(line) + " { /* ... */ }")
                i = _extra_block_end(lines, i, lang) + 1
            else:  # body-less declaration (interface-style, abstract, `= expr`)
                out.append(line.rstrip())
                i += 1
        elif tm:
            kind = tm.group(2)
            if "{" in line and kind in cfg["full_kinds"]:
                bend = _extra_block_end(lines, i, lang)
                out.extend(ln.rstrip() for ln in lines[i:bend + 1])
                i = bend + 1
            elif "{" in line:
                sub, nxt = _extra_class_members(lines, i, lang, cfg)
                out.extend(sub)
                i = nxt
            else:
                out.append(line.rstrip())
                i += 1
        elif cfg["prop"].match(line) or (cfg["const"] and cfg["const"].match(line)):
            if "{" in line:  # computed property / accessor block
                out.append(_sig_before_body(line) + " { /* ... */ }")
                i = _extra_block_end(lines, i, lang) + 1
            else:
                out.append(line.rstrip())
                i += 1
        elif lang == "php" and stripped.endswith(";") and "(" not in stripped:
            out.append(line.rstrip())  # trait use / field inside a PHP class
            i += 1
        elif lang == "swift" and re.match(r"^\s*(public\s+|private\s+|required\s+|convenience\s+|override\s+)*init\s*[?(]", line):
            if "{" in line:
                out.append(_sig_before_body(line) + " { /* ... */ }")
                i = _extra_block_end(lines, i, lang) + 1
            else:
                out.append(line.rstrip())
                i += 1
        else:
            i += 1
    out.append("}")
    return out, end + 1


def _extra_signatures(lines, lang, cfg, mode):
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        tm = cfg["type"].match(line)
        if cfg["import"].match(line):
            out.append(line.rstrip())
            i += 1
        elif tm and "{" in line:
            kind = tm.group(2)
            if kind in cfg["full_kinds"]:
                end = _extra_block_end(lines, i, lang)
                out.extend(ln.rstrip() for ln in lines[i:end + 1])
                out.append("")
                i = end + 1
            else:
                sub, nxt = _extra_class_members(lines, i, lang, cfg)
                out.extend(sub)
                out.append("")
                i = nxt
        elif cfg["func"].match(line):
            if mode == "interfaces":
                i = _extra_block_end(lines, i, lang) + 1 if "{" in line else i + 1
            elif "{" in line:
                out.append(_sig_before_body(line) + " { /* ... */ }")
                i = _extra_block_end(lines, i, lang) + 1
            else:
                out.append(line.rstrip())
                i += 1
        elif mode == "signatures" and lang in ("kotlin", "swift") and cfg["prop"].match(line) and "{" not in line:
            out.append(line.rstrip())  # top-level val/var/let
            i += 1
        else:
            i += 1
    return out


def _extra_strip_tests(lines, lang, cfg, source):
    drop: set[int] = set()
    i = 0
    pending: int | None = None  # start line of a test annotation/docblock
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        is_annotation = False
        if lang == "php" and ("@test" in line or stripped.startswith("#[Test")):
            is_annotation = True
            if pending is None:
                pending = i
                # A /** docblock above the @test line belongs to the method.
                j = i - 1
                while j >= 0 and (lines[j].strip().startswith("*") or lines[j].strip().startswith("/**")):
                    pending = j
                    if lines[j].strip().startswith("/**"):
                        break
                    j -= 1
        elif lang in ("kotlin", "swift") and stripped.startswith("@Test"):
            is_annotation = True
            if pending is None:
                pending = i
        elif stripped.startswith("@") or stripped.startswith("#[") or stripped.startswith("*"):
            is_annotation = True  # other annotations / docblock lines: keep pending
        if is_annotation:
            i += 1
            continue
        fm = cfg["func"].match(line)
        if fm:
            mname = cfg["func_name"].search(line)
            name = mname.group(1) if mname else ""
            if pending is not None or name.startswith("test"):
                start = pending if pending is not None else i
                end = _extra_block_end(lines, i, lang) if "{" in line else i
                for ln in range(start, end + 1):
                    drop.add(ln)
                i = end + 1
            else:
                i += 1
            pending = None
            continue
        if stripped and not stripped.startswith("//") and not stripped.startswith("/*"):
            pending = None
        i += 1
    kept = [ln for idx, ln in enumerate(lines) if idx not in drop]
    text = "\n".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text).strip("\n")
    return text + ("\n" if text else "")


def _slice_brace_extra(source: str, mode: str, lang: str, path: str = "") -> str:
    cfg = _EXTRA_CFG[lang]
    lines = source.splitlines()
    if mode == "strip-tests":
        return _extra_strip_tests(lines, lang, cfg, source)
    if mode in ("signatures", "interfaces"):
        out = _extra_signatures(lines, lang, cfg, mode)
        text = "\n".join(out).strip()
        return text + ("\n" if text else "")
    return source


# ---------------------------------------------------------------------------
# Ruby (parser-lite, v0.5): blocks are keyword/`end`, tracked by the
# opener keywords and trailing `do`, which is reliable for conventional
# (indented, one-statement-per-line) Ruby.
# ---------------------------------------------------------------------------

_RB_REQUIRE_RE = re.compile(r"^\s*(require|require_relative)\b")
_RB_TYPE_RE = re.compile(r"^\s*(module|class)\s+[\w:]+")
_RB_DEF_RE = re.compile(r"^\s*def\s+[\w!?=<>+\-*\[\]]+")
_RB_ATTR_RE = re.compile(r"^\s*(attr_reader|attr_writer|attr_accessor|include|extend|using)\b")
_RB_CONST_RE = re.compile(r"^\s*[A-Z][\w:]*\s*=[^=]")
_RB_OPENER_RE = re.compile(r"^(def|class|module|if|unless|case|while|until|begin|for)\b")
_RB_DO_RE = re.compile(r"\bdo\s*(\|[^|]*\|)?\s*$")
_RB_TEST_BLOCK_RE = re.compile(r"^\s*(describe|context|it|specify|feature|scenario)\b")
_RB_TEST_DEF_RE = re.compile(r"^\s*def\s+test_\w*")


def _rb_block_end(lines: list[str], start: int) -> int:
    """Index of the `end` line closing the block opened at `start`."""
    depth = 0
    for i in range(start, len(lines)):
        s = lines[i].strip()
        if _RB_OPENER_RE.match(s) or _RB_DO_RE.search(s):
            depth += 1
        if s == "end" or s.startswith("end ") or s.startswith("end."):
            depth -= 1
            if depth == 0:
                return i
    return len(lines) - 1


def _rb_type_block(lines, start, mode):
    end = _rb_block_end(lines, start)
    indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
    out = [lines[start].rstrip()]
    i = start + 1
    while i < end:
        line = lines[i]
        if _RB_DEF_RE.match(line):
            out.append(line.rstrip())
            i = _rb_block_end(lines, i) + 1
        elif _RB_TYPE_RE.match(line):
            sub, nxt = _rb_type_block(lines, i, mode)
            out.extend(sub)
            i = nxt
        elif _RB_ATTR_RE.match(line) or _RB_CONST_RE.match(line) or _RB_REQUIRE_RE.match(line):
            out.append(line.rstrip())
            i += 1
        else:
            i += 1
    out.append(indent + "end")
    return out, end + 1


def _slice_ruby(source: str, mode: str, path: str = "") -> str:
    lines = source.splitlines()
    if mode == "strip-tests":
        drop: set[int] = set()
        i = 0
        while i < len(lines):
            if _RB_TEST_DEF_RE.match(lines[i]) or \
                    (_RB_TEST_BLOCK_RE.match(lines[i]) and _RB_DO_RE.search(lines[i].strip())):
                end = _rb_block_end(lines, i)
                for ln in range(i, end + 1):
                    drop.add(ln)
                i = end + 1
            else:
                i += 1
        kept = [ln for idx, ln in enumerate(lines) if idx not in drop]
        text = "\n".join(kept)
        text = re.sub(r"\n{3,}", "\n\n", text).strip("\n")
        return text + ("\n" if text else "")
    if mode in ("signatures", "interfaces"):
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if _RB_REQUIRE_RE.match(line) or _RB_ATTR_RE.match(line) or _RB_CONST_RE.match(line):
                out.append(line.rstrip())
                i += 1
            elif _RB_TYPE_RE.match(line):
                block, i = _rb_type_block(lines, i, mode)
                out.extend(block)
                out.append("")
            elif _RB_DEF_RE.match(line):
                if mode == "signatures":
                    out.append(line.rstrip())
                i = _rb_block_end(lines, i) + 1
            else:
                i += 1
        text = "\n".join(out).strip()
        return text + ("\n" if text else "")
    return source


# ---------------------------------------------------------------------------
# C / C++ (parser-lite, v0.8)
#
# Same honesty label as the other lite slicers: line scanning plus the
# shared string/comment-aware brace matcher (extended in v0.8 with
# preprocessor skipping, C++ raw strings, and digit separators).
# Conventional formatting only: one declaration per line, multi-line
# signatures gathered while parentheses are unbalanced, opening brace
# on the declaration line or alone on the next line (K&R functions).
#
# C: preprocessor lines are surface and kept in both reducing modes;
# struct/union/enum blocks and typedefs are declaration surface (kept
# in full in signatures AND interfaces, the Go/Rust rule); function
# definitions collapse to their signature, prototypes are kept as-is;
# interfaces drops free functions. A .h header of prototypes barely
# shrinks in signatures mode — correct behaviour, pinned by a test.
#
# C++ adds: classes/structs reduced to member signatures, namespaces
# recursed, templates (a template head on its own line is carried onto
# the next declaration; single-line template heads work inline), enum
# (incl. enum class) blocks in full, typedef/using kept. strip-tests
# drops gtest TEST/TEST_F/TEST_P blocks (in non-test-named files;
# *_test.cpp etc. are dropped wholesale by slice_source) and
# test-named functions; C strip-tests drops test-named functions.
# Known lite limits: K&R parameter declarations (a K&R definition
# is read as a prototype: head kept, body not stripped), declarations
# split with the return type on its own line, one-line class bodies
# (members on the declaration line itself are not reduced), extern
# "C" blocks (their functions are still found, the wrapper is
# dropped), and C++ requires-clauses / concepts.
# ---------------------------------------------------------------------------

_PREPROC_RE = re.compile(r"^\s*#")
_C_TYPE_RE = re.compile(r"^\s*(typedef\s+)?(struct|union|enum)\s*(\w+)?")
_CPP_ENUM_RE = re.compile(r"^\s*enum\s+(class\s+|struct\s+)?(\w+)?")
_CPP_CLASS_RE = re.compile(
    r"^\s*(?:template\s*<.*>\s*)?(class|struct|union)\s+([A-Za-z_]\w*)")
_CPP_NS_RE = re.compile(r"^\s*(inline\s+)?namespace\s*([\w:]*)\s*(=\s*[\w:]+)?\s*$"
                        r"|^\s*(inline\s+)?namespace\s*([\w:]*)\s*\{")
_C_HEAD_RE = re.compile(
    r"^\s*(?:template\s*<[^;{}]*>\s*)?"
    r"(?P<prefix>[\w:<>,\*&\[\]~ ]*?)"
    r"(?P<name>~?[A-Za-z_]\w*|operator\s*\S+?)\s*\(")
_C_NOT_FUNCS = {"if", "for", "while", "switch", "return", "sizeof",
                "catch", "do", "else", "case", "goto"}
_GTEST_RE = re.compile(r"^\s*(TEST|TEST_F|TEST_P|TYPED_TEST|TYPED_TEST_P)\s*\(")
_ACCESS_RE = re.compile(r"^\s*(public|private|protected)\s*:\s*$")


def _mask_quotes(line: str) -> str:
    """Same-length copy with literal and comment interiors blanked.

    Keeps indices aligned so paren/brace positions found in the masked
    line are valid in the original. Handles '...' and "..." with
    backslash escapes, `//` line comments, and same-line `/* ... */`
    block comments (string state wins, so `http://` inside a literal
    is safe; a block comment that spans lines is masked only on its
    opening line). A `'` between digits (digit separator) is left
    alone.
    """
    out = list(line)
    state: str | None = None
    i = 0
    while i < len(line):
        ch = line[i]
        nxt = line[i + 1] if i + 1 < len(line) else ""
        if state == "line":
            out[i] = " "
            i += 1
            continue
        if state is None:
            if ch == "/" and nxt == "/":
                state = "line"
                out[i] = " "
                i += 1
                continue
            if ch == "/" and nxt == "*":
                end = line.find("*/", i + 2)
                stop = len(line) if end < 0 else end + 2
                for k in range(i, stop):
                    out[k] = " "
                i = stop
                continue
            if ch in ("'", '"'):
                if ch == "'" and i > 0 and line[i - 1].isdigit() \
                        and i + 1 < len(line) and line[i + 1].isdigit():
                    i += 1
                    continue
                state = ch
            i += 1
            continue
        if ch == "\\":
            out[i] = " "
            if i + 1 < len(line):
                out[i + 1] = " "
            i += 2
            continue
        if ch == state:
            state = None
        else:
            out[i] = " "
        i += 1
    return "".join(out)


def _find_block_brace(lines, i, limit=5):
    """(line, col) of a block-opening `{` at paren depth 0, or None when
    a `;` at depth 0 comes first (a statement, not a block)."""
    depth = 0
    for t in range(i, min(i + limit, len(lines))):
        masked = _mask_quotes(lines[t])
        for idx, ch in enumerate(masked):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif depth == 0 and ch == "{":
                return (t, idx)
            elif depth == 0 and ch == ";":
                return None
    return None


def _stmt_end(lines, i, limit=6):
    """Index of the line where the statement starting at `i` ends (`;`)."""
    for t in range(i, min(i + limit, len(lines))):
        if ";" in _mask_quotes(lines[t]):
            return t
    return i


def _c_func_head(lines, i, lang, bare_name=None):
    """Detect a C/C++ function head starting at line `i`.

    Returns {"name", "kind" ("def"|"proto"), "head_end", "body_line",
    "body_col"} or None. `bare_name` (a class name, inside a class
    body) additionally allows return-type-less heads: constructors
    and destructors. A `=` before the parameter `(` (initialisers,
    assignments) and `typedef` lines are rejected, as are control
    keywords wearing a return type (`return f(x);` etc.).
    """
    masked = _mask_quotes(lines[i])
    if masked.lstrip().startswith("typedef"):
        return None
    m = _C_HEAD_RE.match(masked)
    if not m:
        return None
    name = m.group("name")
    base = name.lstrip("~").split()[-1] if name.startswith("operator") else name.lstrip("~")
    if base in _C_NOT_FUNCS or name in _C_NOT_FUNCS:
        return None
    prefix = m.group("prefix") or ""
    if prefix.strip():
        # The prefix is everything before the name: return type and
        # modifiers (or a `Class::` qualifier). It can never contain
        # parens/braces/semicolons (the regex charset excludes them)
        # and it cannot start with a control keyword wearing a type:
        # `return f(x);` is a statement, not a head.
        first = prefix.strip().split(None, 1)[0]
        if first in _C_NOT_FUNCS:
            return None
    elif bare_name is None or base != bare_name:
        # No return type at all: only a constructor/destructor of
        # the enclosing class (bare_name) may omit it.
        return None
    paren = masked.find("(", m.start("name"))
    if paren < 0 or "=" in masked[:paren]:
        return None
    if masked[paren + 1:].lstrip().startswith("*"):
        return None  # function-pointer declarator, not a function head
    depth = 0
    j = i
    while j < len(lines) and j - i <= 12:
        txt = _mask_quotes(lines[j])
        depth += txt.count("(") - txt.count(")")
        if depth <= 0:
            close = txt.rfind(")")
            rest = txt[close + 1:] if close >= 0 else ""
            if "{" in rest:
                bcol = lines[j].find("{", lines[j].rfind(")"))
                return {"name": name, "kind": "def", "head_end": j,
                        "body_line": j, "body_col": bcol}
            if rest.rstrip().endswith(";"):
                return {"name": name, "kind": "proto", "head_end": j,
                        "body_line": -1, "body_col": -1}
            k = j + 1
            while k < len(lines) and not lines[k].strip():
                k += 1
            if k < len(lines) and lines[k].lstrip().startswith("{"):
                return {"name": name, "kind": "def", "head_end": j,
                        "body_line": k, "body_col": lines[k].find("{")}
            if ";" not in rest:
                # Continued declarations: a constructor initializer
                # list or a trailing return type may sit between the
                # parameter list and the body brace; a split
                # declaration (`= 0;` or an attribute on its own line,
                # a split trailing return) ends at a `;` on a later
                # line and is a prototype whose head runs to it.
                for k in range(j + 1, min(j + 5, len(lines))):
                    txt2 = _mask_quotes(lines[k])
                    if not txt2.strip():
                        continue
                    semi = txt2.find(";")
                    brace = txt2.find("{")
                    if brace >= 0 and (semi < 0 or brace < semi):
                        return {"name": name, "kind": "def", "head_end": j,
                                "body_line": k,
                                "body_col": lines[k].find("{")}
                    if semi >= 0:
                        return {"name": name, "kind": "proto",
                                "head_end": k, "body_line": -1,
                                "body_col": -1}
            return None
        j += 1
    return None


def _c_head_end(lines, head, lang):
    """First line index AFTER the function described by `head`."""
    if head["kind"] == "def":
        return _brace_end(lines, head["body_line"],
                          body_col=head["body_col"], lang=lang) + 1
    return head["head_end"] + 1


def _c_sig_text(lines, i, head):
    parts = []
    last = head["body_line"] if head["kind"] == "def" else head["head_end"]
    for t in range(i, last + 1):
        seg = lines[t]
        if head["kind"] == "def" and t == head["body_line"]:
            seg = seg[:head["body_col"]]
        parts.append(seg.strip())
    sig = " ".join(p for p in parts if p)
    if head["kind"] == "def":
        return sig + " { /* ... */ }"
    return sig


def _c_type_block(lines, i, lang):
    """struct/union/enum (optionally typedef'd) starting at line `i`.

    Returns ("block", end) / ("stmt", end) / None.
    """
    if not _C_TYPE_RE.match(_mask_quotes(lines[i])):
        return None
    found = _find_block_brace(lines, i)
    if found is None:
        return ("stmt", _stmt_end(lines, i))
    bl, bcol = found
    return ("block", _brace_end(lines, bl, body_col=bcol, lang=lang))


def _is_test_func_name(name: str) -> bool:
    base = name.lstrip("~")
    if not base.lower().startswith("test"):
        return False
    if len(base) == 4:
        return True
    ch = base[4]
    return ch == "_" or ch.isupper() or ch.isdigit()


def _slice_c(source: str, mode: str, lang: str) -> str:
    lines = source.splitlines()
    out: list[str] = []
    i = 0
    pp_cont = False
    while i < len(lines):
        line = lines[i]
        masked = _mask_quotes(line)
        if pp_cont or _PREPROC_RE.match(line):
            out.append(line.rstrip())
            pp_cont = line.rstrip().endswith("\\")
            i += 1
            continue
        pp_cont = False
        head = _c_func_head(lines, i, lang)
        if head is not None:
            nxt = _c_head_end(lines, head, lang)
            if mode == "signatures":
                out.append(_c_sig_text(lines, i, head))
            i = nxt
            continue
        tb = _c_type_block(lines, i, lang)
        if tb is not None:
            kind, end = tb
            if kind == "block":
                out.extend(ln.rstrip() for ln in lines[i:end + 1])
                out.append("")
            else:
                # A statement: typedefs and forward declarations are
                # type surface (both modes); a struct/enum *variable*
                # is signatures-only surface.
                stmt = " ".join(_mask_quotes(ln) for ln in lines[i:end + 1])
                if masked.lstrip().startswith("typedef") or re.match(
                        r"^\s*(struct|union|enum)\s+\w+\s*;$", stmt.strip()) \
                        or mode == "signatures":
                    out.extend(ln.rstrip() for ln in lines[i:end + 1])
            i = end + 1
            continue
        if masked.lstrip().startswith("typedef"):
            end = _stmt_end(lines, i)
            out.extend(ln.rstrip() for ln in lines[i:end + 1])
            i = end + 1
            continue
        if mode == "signatures" and ";" in masked and not masked.lstrip().startswith("}"):
            end = _stmt_end(lines, i)
            out.extend(ln.rstrip() for ln in lines[i:end + 1])
            i = end + 1
            continue
        i += 1
    text = "\n".join(out).strip()
    return text + ("\n" if text else "")


def _cpp_decls(lines, i0, end, mode, out, class_name=None):
    """Process C++ declarations in lines[i0:end], appending to `out`.

    Used for the top level (class_name=None), namespace interiors,
    and class interiors (class_name set: constructors/destructors may
    omit the return type and member signatures are kept in both
    reducing modes). Returns nothing; callers advance by block spans.
    """
    i = i0
    pp_cont = False
    pending: list[str] = []  # template head lines awaiting a declaration
    while i < end:
        line = lines[i]
        masked = _mask_quotes(line)
        stripped = masked.strip()
        if pp_cont or _PREPROC_RE.match(line):
            out.append(line.rstrip())
            pp_cont = line.rstrip().endswith("\\")
            i += 1
            continue
        pp_cont = False
        if stripped.startswith("template") and (stripped.startswith("template <")
                                                or stripped.startswith("template<")):
            # Template head: gather while angle brackets are unbalanced.
            j = i
            ang = 0
            while j < end and j - i <= 4:
                ang += _mask_quotes(lines[j]).count("<") - _mask_quotes(lines[j]).count(">")
                j += 1
                if ang <= 0:
                    break
            rest = _mask_quotes(lines[j - 1])
            after = rest[rest.rfind(">") + 1:].strip() if ">" in rest else ""
            if not after:
                pending = [ln.rstrip() for ln in lines[i:j]]
                i = j
                continue
            # else: declaration shares the line; fall through and let the
            # matchers (which accept a template prefix) handle this line.
        if class_name is None and _CPP_NS_RE.match(masked) \
                and not masked.rstrip().endswith(";"):
            found = _find_block_brace(lines, i)
            if found is not None:
                bl, bcol = found
                bend = _brace_end(lines, bl, body_col=bcol, lang="cpp")
                header = " ".join(
                    ln.strip() for ln in lines[i:bl] + [lines[bl][:bcol]]).strip()
                out.extend(pending)
                pending = []
                out.append(header + " {")
                _cpp_decls(lines, bl + 1, bend, mode, out)
                out.append("}")
                out.append("")
                i = bend + 1
                continue
        _tm = _C_TYPE_RE.match(masked)
        if _CPP_ENUM_RE.match(masked) or (_tm and _tm.group(2) == "enum") \
                or (masked.lstrip().startswith("typedef") and _tm):
            tb = _c_type_block(lines, i, "cpp")
            if tb is not None:
                kind, tend = tb
                out.extend(pending)
                pending = []
                out.extend(ln.rstrip() for ln in lines[i:tend + 1])
                out.append("")
                i = tend + 1
                continue
        cm = _CPP_CLASS_RE.match(masked)
        if cm:
            found = _find_block_brace(lines, i)
            if found is None:
                tend = _stmt_end(lines, i)  # forward declaration / alias-ish
                out.extend(pending)
                pending = []
                out.extend(ln.rstrip() for ln in lines[i:tend + 1])
                i = tend + 1
                continue
            bl, bcol = found
            bend = _brace_end(lines, bl, body_col=bcol, lang="cpp")
            header = " ".join(
                ln.strip() for ln in lines[i:bl] + [lines[bl][:bcol]]).strip()
            out.extend(pending)
            pending = []
            out.append(header + " {")
            _cpp_decls(lines, bl + 1, bend, mode, out,
                       class_name=cm.group(2))
            out.append("}")
            out.append("")
            i = bend + 1
            continue
        if masked.lstrip().startswith(("typedef", "using ")):
            found = _find_block_brace(lines, i)
            if found is not None:
                # typedef class/enum/struct with a body: emit the block.
                bl, bcol = found
                tend = _brace_end(lines, bl, body_col=bcol, lang="cpp")
            else:
                tend = _stmt_end(lines, i)
            out.extend(pending)
            pending = []
            out.extend(ln.rstrip() for ln in lines[i:tend + 1])
            i = tend + 1
            continue
        if class_name is not None and _ACCESS_RE.match(masked):
            out.append(line.rstrip())
            i += 1
            continue
        head = _c_func_head(lines, i, "cpp", bare_name=class_name)
        if head is not None:
            nxt = _c_head_end(lines, head, "cpp")
            if mode == "signatures" or class_name is not None:
                out.extend(pending)
                out.append(_c_sig_text(lines, i, head))
            pending = []
            i = nxt
            continue
        if (class_name is not None or mode == "signatures") \
                and ";" in masked and not stripped.startswith("}"):
            tend = _stmt_end(lines, i)
            out.extend(ln.rstrip() for ln in lines[i:tend + 1])
            i = tend + 1
            continue
        i += 1
    out.extend(pending)


def _slice_cpp(source: str, mode: str) -> str:
    lines = source.splitlines()
    out: list[str] = []
    _cpp_decls(lines, 0, len(lines), mode, out)
    text = "\n".join(out).strip()
    return text + ("\n" if text else "")


def _c_family_strip_tests(lines, lang, source):
    drop: set[int] = set()
    i = 0
    while i < len(lines):
        if lang == "cpp" and _GTEST_RE.match(lines[i]):
            found = _find_block_brace(lines, i, limit=3)
            if found is not None:
                bl, bcol = found
                end = _brace_end(lines, bl, body_col=bcol, lang=lang)
                for ln in range(i, end + 1):
                    drop.add(ln)
                i = end + 1
                continue
            i += 1
            continue
        head = _c_func_head(lines, i, lang)
        if head is not None and _is_test_func_name(head["name"]):
            end = _c_head_end(lines, head, lang)
            for ln in range(i, end):
                drop.add(ln)
            i = end
            continue
        i += 1
    kept = [ln for idx, ln in enumerate(lines) if idx not in drop]
    text = "\n".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text).strip("\n")
    return text + ("\n" if text else "")


def _slice_c_family(source: str, mode: str, lang: str, path: str = "") -> str:
    lines = source.splitlines()
    if mode == "strip-tests":
        return _c_family_strip_tests(lines, lang, source)
    if mode in ("signatures", "interfaces"):
        if lang == "c":
            return _slice_c(source, mode, lang)
        return _slice_cpp(source, mode)
    return source


# ---------------------------------------------------------------------------
# Scala (parser-lite, v0.8)
#
# Line scanning + the shared brace matcher (v0.8 extensions: nested
# block comments, triple-quoted strings, s-interpolation). Keeps
# package/import lines, def signatures, val/var declarations, and
# class/object/trait/enum declarations; traits and enums are kept in
# full (declaration surface, the Go/Rust rule), classes/objects are
# reduced to member signatures. interfaces drops top-level defs.
#
# Scala 3 significant-indentation style (type bodies with no braces,
# opened by a trailing `:`) is handled by an indentation fallback:
# the body region is the run of more-indented lines, and members are
# collected from it with the same def/val/type logic. Degradation
# rule: when a construct cannot be understood, MORE is kept (a trait
# body in full, a def head with its body region skipped by indent),
# never less — the output can be longer than ideal, never corrupted.
# strip-tests drops @Test-annotated defs, test-named defs, and
# test("...") { } blocks (munit/FunSuite style in ordinary files);
# *Spec/*Suite/Test files are dropped wholesale by slice_source.
# Known lite limits: `given` instances, extension methods, defs whose
# parameter lists use brace-block default arguments spanning lines,
# and one-line `class Foo { def bar = 1 }` bodies (contents on the
# declaration line itself are not reduced).
# ---------------------------------------------------------------------------

_SC_IMPORT_RE = re.compile(r"^\s*(package|import)\b")
_SC_TYPE_RE = re.compile(
    r"^\s*(?:(?:abstract|final|sealed|open|case|transparent|infix|opaque)\s+)*"
    r"(class|object|trait|enum)\s+([A-Za-z_]\w*)")
_SC_ALIAS_RE = re.compile(
    r"^\s*(?:(?:abstract|opaque)\s+)*type\s+([A-Za-z_]\w*)")
_SC_DEF_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|override|final|abstract|sealed|"
    r"inline|open|erased)\s+)*def\s+([A-Za-z_]\w*|[^\s(\[:]+)?")
_SC_VAL_RE = re.compile(
    r"^\s*(?:(?:private|protected|override|final|abstract|sealed|lazy)\s+)*"
    r"(val|var)\s+([A-Za-z_]\w*)")
_SC_TEST_BLOCK_RE = re.compile(r"^\s*test\s*\(")


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip())


def _indent_block_end(lines, start, limit):
    """Last index of the indented region opened at `start` (blank lines
    do not end the region). Returns `start` when there is no region."""
    base = _indent_of(lines[start])
    last = start
    j = start + 1
    while j < limit:
        if not lines[j].strip():
            j += 1
            continue
        if _indent_of(lines[j]) > base:
            last = j
            j += 1
        else:
            break
    return last


def _scala_def(lines, i, limit):
    """Detect a def starting at line `i`.

    Returns (sig_text, next_i, name) or None. Bodies: brace bodies are
    skipped with the shared matcher; `= expr` bodies by indentation
    (the expression is the run of lines more indented than the def,
    or the rest of the head line); no body = abstract def.
    """
    m = _SC_DEF_RE.match(lines[i])
    if not m:
        return None
    name = m.group(1) or ""
    pad = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
    # Gather the head: while parens are unbalanced or lines end in ','.
    j = i
    paren = 0
    while j < limit and j - i <= 12:
        txt = _mask_quotes(lines[j])
        paren += txt.count("(") - txt.count(")")
        j += 1
        if paren <= 0 and not lines[j - 1].rstrip().endswith(","):
            break
    head_end = j - 1
    # Scan the masked head at paren depth 0 for a body brace or '='.
    body = None
    eq = None
    depth = 0
    for t in range(i, head_end + 1):
        txt = _mask_quotes(lines[t])
        for idx, ch in enumerate(txt):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif depth == 0 and ch == "{" and body is None:
                body = (t, idx)
            elif depth == 0 and ch == "=" and eq is None:
                # Only a standalone `=` is the body equals: `=:=`,
                # `==`, `>=`, `<=`, `!=` are signature operators.
                prev = txt[idx - 1] if idx > 0 else " "
                after = txt[idx + 1] if idx + 1 < len(txt) else " "
                if prev not in "=<>!" and after not in "=:>":
                    eq = (t, idx)
        if body is not None:
            break
    if body is not None:
        bl, bcol = body
        parts = [lines[t].strip() for t in range(i, bl)]
        parts.append(lines[bl][:bcol].strip())
        sig = " ".join(p for p in parts if p)
        nxt = _brace_end(lines, bl, body_col=bcol, lang="scala") + 1
        return (pad + sig + " { /* ... */ }", min(nxt, limit), name)
    if eq is not None:
        et, ecol = eq
        parts = [lines[t].strip() for t in range(i, et)]
        parts.append(lines[et][:ecol].strip())
        sig = " ".join(p for p in parts if p)
        base = _indent_of(lines[i])
        nxt = head_end + 1
        while nxt < limit:
            if lines[nxt].strip() and _indent_of(lines[nxt]) <= base:
                break
            nxt += 1
        return (pad + sig + " = ...", nxt, name)
    parts = [lines[t].strip() for t in range(i, head_end + 1)]
    return (pad + " ".join(p for p in parts if p), head_end + 1, name)


def _scala_region(lines, i0, end, mode, out, in_type=False):
    """Process Scala declarations in lines[i0:end] into `out`.

    Works at the top level, inside brace-delimited type bodies, and
    inside Scala 3 indented type bodies — construct spans are computed
    per construct (brace span, indented span, or single line), so the
    two styles can mix.
    """
    i = i0
    while i < end:
        line = lines[i]
        masked = _mask_quotes(line)
        if _SC_IMPORT_RE.match(line):
            out.append(line.rstrip())
            i += 1
            continue
        tm = _SC_TYPE_RE.match(line)
        if tm:
            kind, _name = tm.group(1), tm.group(2)
            found = _find_block_brace(lines, i, limit=4)
            if found is not None:
                bl, bcol = found
                bend = _brace_end(lines, bl, body_col=bcol, lang="scala")
                if kind in ("trait", "enum"):
                    out.extend(ln.rstrip() for ln in lines[i:bend + 1])
                    out.append("")
                else:
                    header = " ".join(
                        ln.strip() for ln in lines[i:bl] + [lines[bl][:bcol]]).strip()
                    out.append(header + " {")
                    _scala_region(lines, bl + 1, bend, mode, out, in_type=True)
                    out.append("}")
                    out.append("")
                i = bend + 1
                continue
            region_end = _indent_block_end(lines, i, end)
            if region_end == i:
                out.append(line.rstrip())  # bodyless declaration line
                i += 1
                continue
            if kind in ("trait", "enum"):
                out.extend(ln.rstrip() for ln in lines[i:region_end + 1])
                out.append("")
            else:
                out.append(line.rstrip())
                _scala_region(lines, i + 1, region_end + 1, mode, out,
                              in_type=True)
            i = region_end + 1
            continue
        if _SC_ALIAS_RE.match(line):
            out.append(line.rstrip())
            i += 1
            continue
        d = _scala_def(lines, i, end)
        if d is not None:
            sig, nxt, _name = d
            if mode == "signatures" or in_type:
                out.append(sig)
            i = nxt
            continue
        vm = _SC_VAL_RE.match(line)
        if vm:
            if mode == "signatures" or in_type:
                out.append(line.rstrip())
            if "{" in masked:
                i = _brace_end(lines, i, body_col=masked.find("{"),
                               lang="scala") + 1
            else:
                i += 1
            continue
        i += 1


def _scala_strip_tests(lines, source):
    drop: set[int] = set()
    i = 0
    pending: int | None = None
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("@Test"):
            if pending is None:
                pending = i
            i += 1
            continue
        if stripped.startswith("@"):
            i += 1
            continue
        if _SC_TEST_BLOCK_RE.match(lines[i]):
            found = _find_block_brace(lines, i, limit=3)
            if found is not None:
                bl, bcol = found
                end = _brace_end(lines, bl, body_col=bcol, lang="scala")
                for ln in range(i, end + 1):
                    drop.add(ln)
                i = end + 1
                pending = None
                continue
        d = _scala_def(lines, i, len(lines))
        if d is not None:
            _sig, nxt, name = d
            if pending is not None or _is_test_func_name(name):
                start = pending if pending is not None else i
                for ln in range(start, nxt):
                    drop.add(ln)
                i = nxt
            else:
                i = nxt
            pending = None
            continue
        if stripped:
            pending = None
        i += 1
    kept = [ln for idx, ln in enumerate(lines) if idx not in drop]
    text = "\n".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text).strip("\n")
    return text + ("\n" if text else "")


def _slice_scala(source: str, mode: str, path: str = "") -> str:
    lines = source.splitlines()
    if mode == "strip-tests":
        return _scala_strip_tests(lines, source)
    if mode in ("signatures", "interfaces"):
        out: list[str] = []
        _scala_region(lines, 0, len(lines), mode, out)
        text = "\n".join(out).strip()
        return text + ("\n" if text else "")
    return source
