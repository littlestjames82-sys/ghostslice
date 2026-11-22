"""Static local import closure.

Parse-level only. Given a project root and a file inside it, return
the project-relative paths that file imports locally, plus the bare
external specifiers it references (recorded, never resolved).

- Python: real ``ast``. Absolute imports resolve from the project
  root, then from the importing file's directory; relative imports
  resolve against the file's package. Package ``__init__.py`` files
  along a resolved module path are included, so the fixture keeps the
  package chain. Dynamic imports (``importlib``, ``__import__``) are
  invisible here and that limit is stated in the fixture manifest.
- JS/TS: import / export-from / require / dynamic-import patterns,
  relative specifiers (``./``, ``../``) only, with the usual extension
  and ``index`` resolution.
- Go: import paths are resolved through the ``module`` directive in
  the project's ``go.mod``. A module-local import path names a
  package directory exactly (that is how the Go toolchain resolves
  it), so the closure is every non-test ``.go`` file in that
  directory. ``*_test.go`` files are excluded; a directory carrying
  its own ``go.mod`` is a nested module and is NOT part of this
  module, so imports of it stay unresolved (recorded as external).
  Without a ``go.mod`` there is no module context and no local
  resolution is attempted.
- C/C++: preprocessor ``#include`` directives. The quoted form is
  local by the language's own rule: it is resolved first against
  the including file's directory, then against the project root
  (modelling the project root as one include path, the common
  ``-I.`` setup). The angle-bracket form names a system or
  include-path header this tool cannot see the search path for,
  so it is recorded as an external reference, never resolved.
  A macro include (``#include SOME_MACRO``) cannot be resolved
  statically and is likewise recorded as external. Comments are
  stripped before scanning, so a commented-out include pulls
  nothing in, and conditional (``#ifdef``) includes are taken
  unconditionally, as with conditional imports in Python: a
  fixture errs toward including what a build might need.
- Anything else: no closure in v0.1. ``closure_supported`` says which
  languages get a closure so reports can label the difference.

Returned local paths are candidates: the caller re-validates each one
against the project root and runs the safety rules (existence,
symlinks, secret shapes, size cap) before copying anything.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

PYTHON_EXTS = {".py"}
JS_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
JS_RESOLVE_EXTS = [".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", ".json"]
GO_EXTS = {".go"}
CPP_EXTS = {".c", ".h", ".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx", ".inl"}
CLOSURE_EXTS = PYTHON_EXTS | JS_EXTS | GO_EXTS | CPP_EXTS


def closure_supported(rel_path: str) -> bool:
    """True when a static import closure is computed for this file type."""
    return Path(rel_path).suffix in CLOSURE_EXTS


def language_of(rel_path: str) -> str:
    """Closure language bucket for a path: python, javascript/typescript, go, or other."""
    suffix = Path(rel_path).suffix
    if suffix == ".py":
        return "python"
    if suffix in JS_EXTS:
        return "javascript/typescript"
    if suffix == ".go":
        return "go"
    if suffix in CPP_EXTS:
        return "c/c++"
    return "other"


def closure_note(rel_path: str) -> str:
    """Human note for the manifest's per-language closure record."""
    lang = language_of(rel_path)
    if lang == "go":
        return ("computed statically (package level: module-local import "
                "paths resolved via go.mod to their package directory; "
                "all non-test .go files of the package; *_test.go excluded)")
    if lang == "c/c++":
        return ("computed statically (preprocessor level: quoted #include "
                "resolved against the including file's directory, then "
                "the project root; angle-bracket and macro includes "
                "recorded as external references)")
    if lang in ("python", "javascript/typescript"):
        return "computed statically (parse level)"
    return "not computed in v0.1"


# ---------------- Python ----------------

def _module_candidates(root: Path, parts: list) -> list:
    """Project-relative candidate files for a module path, init chain first."""
    out: list = []
    for i in range(1, len(parts)):
        init = "/".join(parts[:i]) + "/__init__.py"
        if (root / init).is_file():
            out.append(init)
    joined = "/".join(parts)
    for cand in (joined + ".py", joined + "/__init__.py"):
        if (root / cand).is_file():
            out.append(cand)
    return out


def _python_imports(root: Path, rel: str, text: str) -> tuple:
    locals_found: list = []
    externals: list = []
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return locals_found, externals
    file_dir_parts = rel.split("/")[:-1]  # directory of the importing file
    is_init = rel.endswith("/__init__.py") or rel == "__init__.py"
    package_parts = file_dir_parts if is_init else file_dir_parts

    def resolve(parts: list) -> list:
        return _module_candidates(root, parts)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                cands = resolve(parts)
                if not cands and file_dir_parts:
                    cands = resolve(file_dir_parts + parts)
                if cands:
                    locals_found.extend(cands)
                else:
                    externals.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                up = node.level - 1
                base = package_parts[: len(package_parts) - up] if up <= len(package_parts) else []
                mod_parts = base + (node.module.split(".") if node.module else [])
                cands = resolve(mod_parts) if mod_parts else []
                # `from . import name` / `from .mod import name`: names may be submodules.
                for alias in node.names:
                    sub = mod_parts + [alias.name]
                    cands.extend(resolve(sub))
                if cands:
                    locals_found.extend(cands)
                elif node.module:
                    externals.append("." * node.level + node.module)
            else:
                mod = node.module or ""
                parts = mod.split(".") if mod else []
                cands = resolve(parts) if parts else []
                if not cands and file_dir_parts and parts:
                    cands = resolve(file_dir_parts + parts)
                for alias in node.names:
                    sub = parts + [alias.name]
                    sub_cands = resolve(sub)
                    if not sub_cands and file_dir_parts:
                        sub_cands = resolve(file_dir_parts + sub)
                    cands.extend(sub_cands)
                if cands:
                    locals_found.extend(cands)
                elif mod:
                    externals.append(mod)
    return locals_found, externals


# ---------------- JS / TS ----------------

_JS_SPEC_RE = re.compile(
    r"""(?:import\s+(?:[^'"]*?\s+from\s+)?|export\s+[^'"]*?\s+from\s+|require\s*\(|import\s*\()\s*['"]([^'"]+)['"]""")


def _js_imports(root: Path, rel: str, text: str) -> tuple:
    locals_found: list = []
    externals: list = []
    file_dir = Path(rel).parent
    for spec in _JS_SPEC_RE.findall(text):
        if not (spec.startswith("./") or spec.startswith("../")):
            externals.append(spec)
            continue
        base = (file_dir / spec)
        base_str = base.as_posix()
        # Normalise ../ and ./ segments without touching the filesystem.
        parts: list = []
        escaped = False
        for seg in base_str.split("/"):
            if seg in ("", "."):
                continue
            if seg == "..":
                if parts:
                    parts.pop()
                else:
                    escaped = True
            else:
                parts.append(seg)
        if escaped or not parts:
            continue  # resolves outside the project: not a local candidate
        stem = "/".join(parts)
        cands: list = []
        if Path(stem).suffix:
            if (root / stem).is_file():
                cands.append(stem)
        else:
            for ext in JS_RESOLVE_EXTS:
                if (root / (stem + ext)).is_file():
                    cands.append(stem + ext)
                    break
            else:
                for ext in JS_RESOLVE_EXTS:
                    idx = stem + "/index" + ext
                    if (root / idx).is_file():
                        cands.append(idx)
                        break
        if cands:
            locals_found.extend(cands)
        else:
            externals.append(spec)
    return locals_found, externals


# ---------------- Go ----------------

_GO_MODULE_CACHE: dict = {}


def _go_module_path(root: Path):
    """The ``module`` directive of root/go.mod, or None.

    Module mode is the only resolution context v0.1 supports: with no
    go.mod (or no module line) there is nothing exact to resolve
    against, so callers treat every import as external.
    """
    gomod = root / "go.mod"
    # Cache per go.mod STATE, not per directory: this module also
    # serves the long-lived MCP server, where a project whose go.mod
    # is edited between builds must not keep resolving against the
    # module path the file had at first read.
    try:
        st = gomod.stat()
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = None
    key = (str(root), stamp)
    if key in _GO_MODULE_CACHE:
        return _GO_MODULE_CACHE[key]
    module = None
    try:
        text = gomod.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    for line in text.splitlines():
        line = line.split("//", 1)[0].strip()
        if line.startswith("module") and (len(line) == 6 or line[6] in " \t"):
            rest = line[6:].strip().strip('"')
            if rest:
                module = rest.split()[0]
            break
    _GO_MODULE_CACHE[key] = module
    return module


_GO_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'"}


def _go_tokens(text: str) -> list:
    """Tokenise Go source just far enough to find import specs.

    Returns (kind, value) pairs: kind is "ident", "string" (value is
    the decoded string), or "punct". Comments are dropped; rune
    literals are consumed so a quoted character cannot fake a string.
    """
    tokens: list = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "/" and text[i + 1:i + 2] == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
        elif c == "/" and text[i + 1:i + 2] == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif c == '"' or c == "`":
            quote = c
            j = i + 1
            buf: list = []
            while j < n:
                ch = text[j]
                if quote == '"' and ch == "\\" and j + 1 < n:
                    buf.append(_GO_ESCAPES.get(text[j + 1], text[j + 1]))
                    j += 2
                    continue
                if ch == quote:
                    break
                buf.append(ch)
                j += 1
            tokens.append(("string", "".join(buf)))
            i = j + 1
        elif c == "'":
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "'":
                    break
                j += 1
            i = j + 1
        elif c.isalpha() or c == "_":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            tokens.append(("ident", text[i:j]))
            i = j
        else:
            tokens.append(("punct", c))
            i += 1
    return tokens


def _go_import_paths(text: str) -> list:
    """Import paths named by import declarations, in source order.

    Grammar (Go spec): ImportDecl = "import" ( ImportSpec | "("
    { ImportSpec } ")" ); ImportSpec = [ PackageName ] ImportPath,
    PackageName an identifier, "." or "_", ImportPath a string
    literal. Each spec carries exactly one string literal, so inside
    an import declaration every string token is an import path.
    """
    tokens = _go_tokens(text)
    paths: list = []
    i, n = 0, len(tokens)
    while i < n:
        kind, value = tokens[i]
        if kind == "ident" and value == "import":
            i += 1
            if i < n and tokens[i] == ("punct", "("):
                depth = 0
                while i < n:
                    k, v = tokens[i]
                    if k == "punct" and v == "(":
                        depth += 1
                    elif k == "punct" and v == ")":
                        depth -= 1
                        if depth == 0:
                            i += 1
                            break
                    elif k == "string" and depth >= 1:
                        paths.append(v)
                    i += 1
            else:
                # Single spec: [alias] "path" - take the first string.
                while i < n and tokens[i][0] != "string":
                    if tokens[i][0] == "ident" and tokens[i][1] not in ("import",):
                        i += 1
                        continue
                    if tokens[i] == ("punct", "."):
                        i += 1
                        continue
                    break
                if i < n and tokens[i][0] == "string":
                    paths.append(tokens[i][1])
                    i += 1
        else:
            i += 1
    return paths


def _go_imports(root: Path, rel: str, text: str) -> tuple:
    locals_found: list = []
    externals: list = []
    module = _go_module_path(root)
    for spec in _go_import_paths(text):
        dir_rel = None
        if module:
            if spec == module:
                dir_rel = ""
            elif spec.startswith(module + "/"):
                dir_rel = spec[len(module) + 1:]
        if dir_rel is None:
            externals.append(spec)
            continue
        pkg_dir = root / dir_rel if dir_rel else root
        # A directory with its own go.mod is a nested module: its
        # packages are not part of this module, so the import does
        # not resolve here (it is recorded as unresolved, below).
        if dir_rel and (pkg_dir / "go.mod").is_file():
            externals.append(spec)
            continue
        try:
            names = sorted(p.name for p in pkg_dir.glob("*.go")
                           if not p.name.endswith("_test.go"))
        except OSError:
            names = []
        if not names:
            externals.append(spec)
            continue
        for name in names:
            locals_found.append(f"{dir_rel}/{name}" if dir_rel else name)
    return locals_found, externals


# ---------------- C / C++ ----------------

def _strip_c_comments(text: str) -> str:
    """Return ``text`` with // and /* */ comments blanked out.

    Newlines inside comments are preserved so line structure (and
    therefore directive positions) survives. String and character
    literals are copied verbatim: a ``//`` or ``/*`` inside a
    literal does not open a comment, and an include path inside a
    quoted literal stays readable for the directive scan. C++
    raw strings (``R"delim(...)delim"``) are consumed whole so a
    quote inside one cannot fake a literal boundary.
    """
    out: list = []
    i, n = 0, len(text)
    state = "code"  # code | string | char
    while i < n:
        c = text[i]
        if state == "code":
            if c == "/" and text[i + 1:i + 2] == "/":
                j = text.find("\n", i)
                if j < 0:
                    break
                out.append("\n")
                i = j + 1
            elif c == "/" and text[i + 1:i + 2] == "*":
                j = text.find("*/", i + 2)
                end = n if j < 0 else j + 2
                out.append(" ")
                out.append("\n" * text.count("\n", i, end))
                i = end
            elif c == "R" and text[i + 1:i + 2] == '"':
                # Possible raw string: R"delim( ... )delim"
                k = text.find("(", i + 2)
                delim = text[i + 2:k] if 0 <= k else ""
                if 0 <= k and len(delim) <= 16 and not any(
                        ch in delim for ch in ' )\\"\t'):
                    closer = ")" + delim + '"'
                    j = text.find(closer, k + 1)
                    if j >= 0:
                        out.append(text[i:j + len(closer)])
                        i = j + len(closer)
                        continue
                out.append(c)
                i += 1
            elif c == '"':
                state = "string"
                out.append(c)
                i += 1
            elif c == "'":
                state = "char"
                out.append(c)
                i += 1
            else:
                out.append(c)
                i += 1
        else:  # inside a string or char literal: copy, honour escapes
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if (state == "string" and c == '"') or \
                    (state == "char" and c == "'"):
                state = "code"
            i += 1
    return "".join(out)


_C_INCLUDE_RE = re.compile(
    r"""^[ \t]*#[ \t]*include(?![A-Za-z0-9_])[ \t]*"""
    r"""(?:"([^"\n]+)"|<([^>\n]+)>|([A-Za-z_][A-Za-z0-9_]*))""",
    re.MULTILINE)


def _normalise_include(base_parts: list, spec: str):
    """Project-relative parts for ``spec`` taken from ``base_parts``.

    Returns None when the path climbs above the base (escapes the
    project root once resolved) instead of a candidate.
    """
    parts = list(base_parts)
    for seg in spec.replace("\\", "/").split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(seg)
    return parts


def _c_imports(root: Path, rel: str, text: str) -> tuple:
    locals_found: list = []
    externals: list = []
    cleaned = _strip_c_comments(text)
    file_dir_parts = [p for p in Path(rel).parent.as_posix().split("/")
                      if p not in ("", ".")]
    for m in _C_INCLUDE_RE.finditer(cleaned):
        quoted, angle, macro = m.group(1), m.group(2), m.group(3)
        if angle is not None:
            # System / include-path header: the search path is a
            # build flag this tool never sees, so it stays external.
            externals.append(angle)
            continue
        if macro is not None:
            # #include SOME_MACRO: the path is chosen by the build,
            # invisible statically. Record the token as unresolved.
            externals.append(macro)
            continue
        spec = quoted
        if spec.startswith("/") or spec.startswith("\\"):
            externals.append(spec)  # absolute path: outside the project
            continue
        resolved = None
        for base in (file_dir_parts, []):
            parts = _normalise_include(base, spec)
            if not parts:
                continue
            cand = "/".join(parts)
            if (root / cand).is_file():
                resolved = cand
                break
        if resolved is not None:
            locals_found.append(resolved)
        else:
            externals.append(spec)
    return locals_found, externals


# ---------------- entry point ----------------

def imports_of(root: Path, rel: str, text: str) -> tuple:
    """(local candidate paths, external specifiers) for one file.

    Local paths are deduplicated, order-preserving, project-relative,
    and never include the file itself.
    """
    suffix = Path(rel).suffix
    if suffix == ".py":
        locals_raw, externals = _python_imports(root, rel, text)
    elif suffix in JS_EXTS:
        locals_raw, externals = _js_imports(root, rel, text)
    elif suffix in GO_EXTS:
        locals_raw, externals = _go_imports(root, rel, text)
    elif suffix in CPP_EXTS:
        locals_raw, externals = _c_imports(root, rel, text)
    else:
        return [], []
    seen: set = set()
    out: list = []
    for cand in locals_raw:
        if cand == rel or cand in seen:
            continue
        seen.add(cand)
        out.append(cand)
    ext_seen: set = set()
    ext_out: list = []
    for spec in externals:
        if spec not in ext_seen:
            ext_seen.add(spec)
            ext_out.append(spec)
    return out, ext_out
