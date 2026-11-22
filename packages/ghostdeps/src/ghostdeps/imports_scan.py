"""Import extraction from source code.

Python: real `ast`, so import statements are exact.
JS/TS: parser-lite (regex over import/export/require statements after a
string-aware comment strip). Labelled parser-lite wherever its results
are used.
Rust: outline level (`use` statements and `extern crate`). Labelled
outline wherever its results are used.

The scanner honours local `.gitignore` files and the root
`.ghostslice.json` ignore list when choosing which files to scan.
Manifest discovery is separate and is not filtered by these rules.

Every import is classified as it is found:
  local  - resolves to a file or package inside the tree
  stdlib - Python stdlib / Node builtin / Rust std (never a declaration gap)
  third  - a third-party candidate to cross-reference against declarations
"""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

from .ignores import IgnoreMatcher
from .manifests import SKIP_DIRS
from .names import js_builtin, js_package_name

PY_EXTS = {".py"}
JS_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}
RS_EXTS = {".rs"}

METHOD_LABELS = {
    "python": "ast (exact import statements)",
    "javascript": "parser-lite (regex over import statements)",
    "rust": "outline (use statements only)",
}


class ImportIndex:
    """Collected imports: module top-level name -> record.

    Each record holds the files importing the module, its ecosystem,
    the extraction method label, and its classification (``local``,
    ``stdlib``, or ``third``). Also tracks files scanned per ecosystem,
    Python parse failures, and files skipped under local ignore rules.
    """

    def __init__(self):
        self.records: dict[tuple[str, str], dict] = {}
        self.files_scanned = {"python": 0, "javascript": 0, "rust": 0}
        self.parse_failures: list[str] = []
        self.ignored_files: list[str] = []
        self.ignore_sources: list[str] = []
        self.ignore_warnings: list[str] = []

    def add(self, ecosystem: str, module: str, rel_file: str,
            klass: str, method: str):
        """Record that ``rel_file`` imports ``module`` under ``klass``."""
        key = (ecosystem, module)
        rec = self.records.get(key)
        if rec is None:
            rec = {"module": module, "ecosystem": ecosystem,
                   "method": method, "class": klass, "files": set()}
            self.records[key] = rec
        rec["files"].add(rel_file)


def _iter_sources(root: Path):
    """Yield candidate source files under the built-in skip rules only.

    Project ignore rules are applied by ``scan_imports`` after local
    names have been collected, so an ignored file can still establish
    that a module name is local to the tree.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            yield fpath, str(fpath.relative_to(root))


def _local_names(root: Path, files: list[tuple[Path, str]]) -> dict[str, set[str]]:
    """Top-level names that resolve inside the tree, per ecosystem."""
    local: dict[str, set[str]] = {"python": set(), "javascript": set(),
                                  "rust": set()}
    dir_names: set[str] = set()
    for fpath, rel in files:
        parts = Path(rel).parts
        for part in parts[:-1]:
            dir_names.add(part)
        stem = fpath.stem
        suffix = fpath.suffix.lower()
        if suffix == ".py":
            local["python"].add(stem)
            # A package dir (contains __init__.py) contributes its name.
            if fname_is(fpath.parent, "__init__.py"):
                local["python"].add(fpath.parent.name)
        if suffix in JS_EXTS:
            local["javascript"].add(stem)
        if suffix == ".rs":
            local["rust"].add(stem)
    local["python"] |= dir_names
    local["javascript"] |= dir_names
    local["rust"] |= dir_names
    return local


def fname_is(directory: Path, name: str) -> bool:
    return (directory / name).is_file()


# ---------------------------------------------------------------- Python

def _scan_python(idx: ImportIndex, fpath: Path, rel: str,
                 local: set[str], stdlib: set[str]):
    try:
        # utf-8-sig: a byte-order mark left by a Windows editor used to
        # make ast.parse reject the whole file, silently dropping every
        # import in it. A file that vanishes or cannot be read between
        # discovery and scanning is a parse failure, not a crash of the
        # whole scan (the JS and Rust scanners already treat it so).
        tree = ast.parse(fpath.read_text(encoding="utf-8-sig",
                                         errors="replace"))
    except (SyntaxError, ValueError, OSError, RecursionError):
        idx.parse_failures.append(rel)
        return
    idx.files_scanned["python"] += 1
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import: local by construction
            if node.module:
                modules = [node.module.split(".")[0]]
        for mod in modules:
            if mod in local:
                klass = "local"
            elif mod in stdlib:
                klass = "stdlib"
            else:
                klass = "third"
            idx.add("python", mod, rel, klass, METHOD_LABELS["python"])


# ------------------------------------------------------------- JS / TS

_JS_PATTERNS = [
    re.compile(r"""(?:import|export)\s+(?:[^'";]*?\s+from\s+)?['"]([^'"]+)['"]"""),
    re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
    re.compile(r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
]

_JS_REGEX_PREFIX_KEYWORDS = {
    "await", "case", "delete", "do", "else", "in", "instanceof", "new",
    "of", "return", "throw", "typeof", "void", "yield",
}
_JS_IDENT_START = re.compile(r"[A-Za-z_$]")
_JS_IDENT_PART = re.compile(r"[A-Za-z0-9_$]")


def _strip_js_comments(text: str) -> str:
    """Remove JS/TS comments without treating markers in strings as code.

    This is a lexical helper for the parser-lite scanner, not a full
    JavaScript parser. It preserves string, template, and regex literal
    contents (import specifiers live in strings), replaces comment
    characters with spaces, and preserves newlines so positions stay
    recognisable. Template expressions are scanned as code, including
    nested templates and object braces.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    # Stack entries are templates or ${...} interpolations. The base
    # level and interpolation levels are code; template entries are
    # literal text until a closing backtick or an interpolation.
    stack: list[dict[str, int | str]] = []
    # The previous significant code token, reduced to whether a slash
    # may start a regex literal. Values, closing delimiters, strings,
    # templates, and regexes make a slash a division operator.
    prev_kind = "prefix"

    def in_template() -> bool:
        return bool(stack and stack[-1]["type"] == "template")

    while i < n:
        if in_template():
            ch = text[i]
            if ch == "\\":
                out.append(text[i:i + 2])
                i += 2 if i + 1 < n else 1
                continue
            if ch == "`":
                out.append(ch)
                stack.pop()
                prev_kind = "value"
                i += 1
                continue
            if ch == "$" and i + 1 < n and text[i + 1] == "{":
                out.append("${")
                stack.append({"type": "interp", "brace_depth": 0})
                prev_kind = "prefix"
                i += 2
                continue
            out.append(ch)
            i += 1
            continue

        ch = text[i]

        if ch.isspace():
            out.append(ch)
            i += 1
            continue

        # Comments. Comment text never changes the previous-token state.
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            out.extend("  ")
            i += 2
            while i < n:
                if text[i] == "*" and i + 1 < n and text[i + 1] == "/":
                    out.extend("  ")
                    i += 2
                    break
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            continue

        # Regex literal, when the grammar position allows one. Character
        # classes and escapes are tracked so // or /* inside a pattern
        # cannot be mistaken for a comment.
        if ch == "/" and prev_kind == "prefix":
            out.append(ch)
            i += 1
            escaped = False
            in_class = False
            while i < n:
                c = text[i]
                out.append(c)
                i += 1
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    break
                elif c == "\n":
                    break
            while i < n and (text[i].isalpha() or text[i] == "$"):
                out.append(text[i])
                i += 1
            prev_kind = "value"
            continue

        # Ordinary quoted strings: contents are evidence (specifiers),
        # and comment markers inside them are not comments.
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                c = text[i]
                out.append(c)
                i += 1
                if c == "\\" and i < n:
                    out.append(text[i])
                    i += 1
                elif c == quote:
                    break
                elif c == "\n":
                    break
            prev_kind = "value"
            continue

        # Template literal: switch to template mode above.
        if ch == "`":
            out.append(ch)
            stack.append({"type": "template"})
            i += 1
            continue

        if _JS_IDENT_START.match(ch):
            start = i
            i += 1
            while i < n and _JS_IDENT_PART.match(text[i]):
                i += 1
            word = text[start:i]
            out.append(word)
            prev_kind = "prefix" if word in _JS_REGEX_PREFIX_KEYWORDS \
                else "value"
            continue

        if ch.isdigit():
            start = i
            i += 1
            while i < n and (_JS_IDENT_PART.match(text[i]) or text[i] == "."):
                i += 1
            out.append(text[start:i])
            prev_kind = "value"
            continue

        if ch == "{":
            if stack and stack[-1]["type"] == "interp":
                stack[-1]["brace_depth"] = int(stack[-1]["brace_depth"]) + 1
            out.append(ch)
            prev_kind = "prefix"
            i += 1
            continue

        if ch == "}":
            out.append(ch)
            i += 1
            if stack and stack[-1]["type"] == "interp":
                depth = int(stack[-1]["brace_depth"])
                if depth == 0:
                    stack.pop()
                    # Back in template text; prev_kind is irrelevant
                    # until the template closes.
                    continue
                stack[-1]["brace_depth"] = depth - 1
            prev_kind = "value"
            continue

        out.append(ch)
        i += 1
        if ch in "([{,;:?":
            prev_kind = "prefix"
        elif ch in ")]":
            prev_kind = "value"
        elif ch == ".":
            prev_kind = "value"
        else:
            # Operators and other punctuation introduce an operand, so a
            # following slash may start a regex. Postfix ++/-- remain a
            # parser-lite approximation.
            prev_kind = "prefix"

    return "".join(out)


def _scan_js(idx: ImportIndex, fpath: Path, rel: str, local: set[str]):
    try:
        text = fpath.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return
    idx.files_scanned["javascript"] += 1
    text = _strip_js_comments(text)
    specifiers: set[str] = set()
    for pat in _JS_PATTERNS:
        specifiers.update(pat.findall(text))
    for spec in sorted(specifiers):
        pkg = js_package_name(spec)
        if pkg is None:
            continue  # relative/absolute/URL: not a package import
        if js_builtin(spec):
            idx.add("javascript", pkg, rel, "stdlib", METHOD_LABELS["javascript"])
        elif pkg.split("/")[0] in local or pkg in local:
            idx.add("javascript", pkg, rel, "local", METHOD_LABELS["javascript"])
        else:
            idx.add("javascript", pkg, rel, "third", METHOD_LABELS["javascript"])


# ------------------------------------------------------------------ Rust

_RS_USE = re.compile(r"^\s*(?:pub\s+(?:\([^)]*\)\s+)?)?use\s+([A-Za-z_][\w]*)")
_RS_EXTERN = re.compile(r"^\s*extern\s+crate\s+([A-Za-z_][\w]*)")
_RS_RESERVED = {"crate", "self", "super", "std"}


def _strip_rust_comments(text: str) -> str:
    """Blank out Rust // and /* */ comments, preserving newlines.

    Rust block comments nest. String and char contents are kept as-is
    (a ``use`` line is only matched at a line start, which a string
    body cannot fake except inside a multi-line literal; that residue
    is part of the outline-level limit). Without this, the body of a
    block comment such as::

        /*
        use phantomcrate;
        */

    was reported as a real import of ``phantomcrate``.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    depth = 0  # block-comment nesting depth; 0 means code
    while i < n:
        if depth:
            if text.startswith("/*", i):
                depth += 1
                out.extend("  ")
                i += 2
            elif text.startswith("*/", i):
                depth -= 1
                out.extend("  ")
                i += 2
            else:
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            continue
        if text.startswith("//", i):
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if text.startswith("/*", i):
            depth = 1
            out.extend("  ")
            i += 2
            continue
        ch = text[i]
        if ch in ("'", '"'):
            # Copy a char/string literal verbatim so a // or /* inside
            # it is not mistaken for a comment. Char literals are at
            # most a few characters; lifetimes ('a) have no closing
            # quote and simply fall through the scan limit below.
            quote = ch
            j = i + 1
            while j < n and j - i <= 1024:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote or text[j] == "\n":
                    break
                j += 1
            if j < n and text[j] == quote:
                out.append(text[i:j + 1])
                i = j + 1
            else:
                out.append(ch)
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _scan_rust(idx: ImportIndex, fpath: Path, rel: str, local: set[str]):
    try:
        text = fpath.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return
    idx.files_scanned["rust"] += 1
    crates: set[str] = set()
    for line in _strip_rust_comments(text).splitlines():
        m = _RS_USE.match(line) or _RS_EXTERN.match(line)
        if m:
            crates.add(m.group(1))
    for crate in sorted(crates):
        if crate in _RS_RESERVED:
            idx.add("rust", crate, rel, "stdlib", METHOD_LABELS["rust"])
        elif crate in local:
            idx.add("rust", crate, rel, "local", METHOD_LABELS["rust"])
        else:
            idx.add("rust", crate, rel, "third", METHOD_LABELS["rust"])


# ----------------------------------------------------------------- entry

def scan_imports(root: Path) -> ImportIndex:
    """Scan every non-ignored source file under ``root`` for imports.

    Local names are collected first (ignoring ignore rules, so an
    ignored file can still prove a name is local), then ``.gitignore``
    files and the root ``.ghostslice.json`` ignore list decide which
    files are actually scanned. Returns the populated index.
    """
    idx = ImportIndex()
    files = list(_iter_sources(root))
    local = _local_names(root, files)

    matcher = IgnoreMatcher(root)
    # Load nested .gitignore files for every directory that contains a
    # candidate source, plus each ancestor directory. Loading is in
    # shallow-to-deep order so later (nearer) rules can override parent
    # rules through the matcher's last-match-wins rule order.
    source_exts = PY_EXTS | JS_EXTS | RS_EXTS
    candidates = [(fpath, rel) for fpath, rel in files
                  if fpath.suffix.lower() in source_exts]
    bases = {""}
    for _, rel in candidates:
        parts = Path(rel).parts[:-1]
        for depth in range(1, len(parts) + 1):
            bases.add("/".join(parts[:depth]))
    for base in sorted(bases, key=lambda b: (b.count("/"), b)):
        matcher.load_dir(base)
    idx.ignore_sources = matcher.source_files()
    idx.ignore_warnings = matcher.warnings

    scan_files = []
    for fpath, rel in candidates:
        if matcher.ignored(rel):
            idx.ignored_files.append(rel)
        else:
            scan_files.append((fpath, rel))
    idx.ignored_files.sort()

    stdlib = getattr(sys, "stdlib_module_names", set())
    for fpath, rel in scan_files:
        suffix = fpath.suffix.lower()
        if suffix in PY_EXTS:
            _scan_python(idx, fpath, rel, local["python"], stdlib)
        elif suffix in JS_EXTS:
            _scan_js(idx, fpath, rel, local["javascript"])
        elif suffix in RS_EXTS:
            _scan_rust(idx, fpath, rel, local["rust"])
    return idx
