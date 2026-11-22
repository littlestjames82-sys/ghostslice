"""Symbol outlines: Python via stdlib ast (exact), other languages
parser-lite (regex by line, always labelled parser-lite).

An outline records, per file: symbols (name, qualified, kind,
line span, signature text), the names each symbol calls, file-level
imports (project-relative where resolvable plus external names),
exported names (__all__ / export statements), and whether the file
has a __main__ guard.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath


@dataclass
class Symbol:
    name: str
    qualified: str
    kind: str  # function | method | class
    path: str
    start_line: int
    end_line: int
    signature: str
    calls: list[str] = field(default_factory=list)
    exported: bool = False


@dataclass
class FileOutline:
    path: str
    language: str
    method: str  # "ast" for python, "parser-lite" otherwise
    symbols: dict[str, Symbol] = field(default_factory=dict)  # qualified -> Symbol
    imports: list[str] = field(default_factory=list)         # project paths
    external: list[str] = field(default_factory=list)
    imported_names: dict[str, str] = field(default_factory=dict)  # local name -> module/path hint
    has_main_guard: bool = False
    all_names: list[str] = field(default_factory=list)
    parse_error: str | None = None

    def symbol_at_line(self, line: int) -> Symbol | None:
        best = None
        for sym in self.symbols.values():
            if sym.start_line <= line <= sym.end_line:
                if best is None or sym.start_line >= best.start_line:
                    best = sym
        return best


# ---------------------------------------------------------------------------
# Python (ast)
# ---------------------------------------------------------------------------

def _dotted(node) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _py_signature(node, prefix: str = "") -> str:
    try:
        args = ast.unparse(node.args)
    except Exception:
        args = "..."
    ret = ""
    if getattr(node, "returns", None) is not None:
        try:
            ret = " -> " + ast.unparse(node.returns)
        except Exception:
            ret = ""
    kind = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    if isinstance(node, ast.ClassDef):
        bases = ""
        if node.bases:
            try:
                bases = "(" + ", ".join(ast.unparse(b) for b in node.bases) + ")"
            except Exception:
                bases = ""
        return f"class {node.name}{bases}:"
    return f"{prefix}{kind} {node.name}({args}){ret}:"


def _calls_in(node) -> list[str]:
    names: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            d = _dotted(child.func)
            if d:
                names.append(d)
    return names


def _py_outline(path: str, source: str) -> FileOutline:
    out = FileOutline(path=path, language="python", method="ast")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        out.parse_error = f"syntax error line {exc.lineno}: {exc.msg}"
        return out
    lines = source.splitlines()

    def add_symbol(node, qualified: str, kind: str, prefix: str = ""):
        sym = Symbol(
            name=node.name, qualified=qualified, kind=kind, path=path,
            start_line=node.lineno, end_line=getattr(node, "end_lineno", node.lineno),
            signature=_py_signature(node, prefix),
            calls=sorted(set(_calls_in(node))),
        )
        out.symbols[qualified] = sym
        return sym

    def visit(body, prefix_qual: str = "", prefix_sig: str = ""):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix_qual}{node.name}"
                add_symbol(node, qual, "method" if prefix_qual else "function",
                           prefix_sig)
            elif isinstance(node, ast.ClassDef):
                qual = f"{prefix_qual}{node.name}"
                add_symbol(node, qual, "class")
                visit(node.body, prefix_qual=f"{qual}.", prefix_sig="    ")

    visit(tree.body)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.external.append(alias.name)
                out.imported_names[(alias.asname or alias.name).split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            out.external.append(mod)
            for alias in node.names:
                out.imported_names[alias.asname or alias.name] = mod
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "__all__" \
                        and isinstance(node.value, (ast.List, ast.Tuple)):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            out.all_names.append(elt.value)
        elif isinstance(node, ast.If):
            try:
                test = ast.unparse(node.test)
            except Exception:
                test = ""
            if "__main__" in test:
                out.has_main_guard = True

    for name in out.all_names:
        for sym in out.symbols.values():
            if sym.name == name:
                sym.exported = True
    # top-level functions/classes in a non-test module are its API
    # surface candidates; exported marking is refined by the risk
    # layer (entry points / __all__ win over this default).
    _ = lines
    return out


# ---------------------------------------------------------------------------
# Parser-lite (TS/JS and brace languages)
# ---------------------------------------------------------------------------

_LITE_FUNC = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(")
_LITE_ARROW = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(")
_LITE_CLASS = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)")
_LITE_IFACE = re.compile(
    r"^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)")
_LITE_GO_FUNC = re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)\s*\(")
_LITE_IMPORT_FROM = re.compile(r"""(?:from\s+|import\s+)['"]([^'"]+)['"]""")
_LITE_REQUIRE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")
_LITE_CALL = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
_LITE_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function",
                  "class", "import", "from", "require", "new"}


def _lite_outline(path: str, source: str, language: str) -> FileOutline:
    out = FileOutline(path=path, language=language, method="parser-lite")
    lines = source.splitlines()
    depth = 0
    stack: list[tuple[str, int]] = []  # (qualified, brace depth at open)
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        for regex, kind in ((_LITE_GO_FUNC, "function"), (_LITE_FUNC, "function"),
                            (_LITE_ARROW, "function"), (_LITE_CLASS, "class"),
                            (_LITE_IFACE, "class")):
            m = regex.match(line)
            if m:
                name = m.group(1)
                qual = f"{stack[-1][0]}.{name}" if stack and kind == "function" else name
                sym = Symbol(name=name, qualified=qual,
                             kind="method" if stack and kind == "function" else kind,
                             path=path, start_line=i, end_line=len(lines),
                             signature=stripped[:200],
                             calls=[])
                out.symbols[qual] = sym
                if "{" in line:
                    stack.append((qual, depth + line.count("{") - line.count("}")))
                break
        for spec in _LITE_IMPORT_FROM.findall(line) + _LITE_REQUIRE.findall(line):
            out.external.append(spec)
        depth += line.count("{") - line.count("}")
        while stack and depth < stack[-1][1]:
            qual, _d = stack.pop()
            if qual in out.symbols:
                out.symbols[qual].end_line = i
        if "export" in stripped and ("{" in stripped and "}" in stripped):
            for name in re.findall(r"export\s*\{([^}]*)\}", stripped):
                for part in name.split(","):
                    part = part.strip().split(" as ")[-1].strip()
                    if part:
                        out.all_names.append(part)
    for name in out.all_names:
        for sym in out.symbols.values():
            if sym.name == name:
                sym.exported = True
    # calls per symbol: any call-shaped name inside its line span
    for sym in out.symbols.values():
        body = "\n".join(lines[sym.start_line - 1:sym.end_line])
        calls = [c for c in _LITE_CALL.findall(body) if c not in _LITE_KEYWORDS]
        sym.calls = sorted(set(calls))
    return out


def build_outline(path: str, source: str, language: str) -> FileOutline:
    if language == "python":
        return _py_outline(path, source)
    if language in ("typescript", "javascript", "go", "rust", "java",
                    "csharp", "php", "ruby", "kotlin", "swift", "c",
                    "cpp", "scala"):
        return _lite_outline(path, source, language)
    return FileOutline(path=path, language=language, method="none")


def resolve_imports(outline: FileOutline, root_files: set[str]) -> None:
    """Fill outline.imports with project-relative paths (best effort)."""
    cur_dir = PurePosixPath(outline.path).parent
    resolved: set[str] = set()
    if outline.language == "python":
        for hint in sorted(set(outline.imported_names.values()) | set(outline.external)):
            if not hint:
                continue
            mod_path = hint.replace(".", "/")
            # relative import level unknown here; try both anchored
            # at the project root and at the file's directory.
            for base in (PurePosixPath(""), cur_dir):
                for cand in (base / (mod_path + ".py"),
                             base / mod_path / "__init__.py"):
                    if cand.as_posix() in root_files:
                        resolved.add(cand.as_posix())
    elif outline.language in ("typescript", "javascript"):
        for spec in outline.external:
            if not spec.startswith("."):
                continue
            base = (cur_dir / spec).as_posix()
            # normalise ../ and ./
            parts: list[str] = []
            for part in base.split("/"):
                if part == "..":
                    if parts:
                        parts.pop()
                elif part not in (".", ""):
                    parts.append(part)
            norm = "/".join(parts)
            for cand in (norm + ".ts", norm + ".tsx", norm + ".js",
                         norm + ".jsx", norm + ".mjs",
                         norm + "/index.ts", norm + "/index.js",
                         norm):
                if cand in root_files:
                    resolved.add(cand)
                    break
    outline.imports = sorted(resolved)
