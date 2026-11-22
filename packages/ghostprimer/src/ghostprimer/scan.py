"""Project discovery: facts, entry points, layout, fan-in.

Project-local only: every path handled here is resolved and checked to
live inside the project root. Paths resolving into the user's private
memory locations (~/MEMORY.md, ~/memory/) are refused outright, even
before the inside-root check, per the plan's exclusion rule.
"""
from __future__ import annotations

import ast
import json
import os
import posixpath
import re
import tomllib
from pathlib import Path

SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs",
}
CODE_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".go", ".rs", ".java",
    ".rb", ".php", ".c", ".h", ".cpp", ".cs", ".swift", ".kt", ".sh",
}
ENTRY_NAMES = {"__main__.py", "main.py", "app.py", "cli.py", "index.js",
               "index.ts", "main.ts", "main.js", "manage.py", "run.py"}


def private_memory_roots() -> list[Path]:
    """The private memory locations refused by resolved-path check:
    ``~/MEMORY.md`` and ``~/memory/`` (both resolved)."""
    home = Path.home()
    return [(home / "MEMORY.md").resolve(), (home / "memory").resolve()]


def is_private_memory(path: Path) -> bool:
    """True when *path* resolves to, or inside, a private memory
    location. Resolution follows symlinks, so a symlink into private
    memory is still private memory."""
    try:
        resolved = path.resolve()
    except Exception:
        # Fail closed: a path that cannot be resolved (symlink loop,
        # too many links) must never be waved through as safe.
        return True
    for root in private_memory_roots():
        if resolved == root or root in resolved.parents:
            return True
    return False


def assert_project_local(root: Path, path: Path) -> Path:
    """Resolve path and require it to live inside root.

    Raises ValueError naming the reason when refused: private-memory
    location, or outside the project root.
    """
    try:
        # Resolve first so an unresolvable path (symlink loop) is
        # reported as such, not mislabelled by the fail-closed
        # private-memory check below.
        resolved = path.resolve()
        root_resolved = root.resolve()
    except Exception as exc:
        # Symlink loops and other unresolvable paths are refusals with
        # a clean ValueError, not a RuntimeError/OSError crash for the
        # caller (the CLI only reports ValueError cleanly).
        raise ValueError(f"refused: source path cannot be resolved: {path}: {exc}") from exc
    if is_private_memory(path):
        raise ValueError(f"refused: source is in a private memory location: {path}")
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(f"refused: source is outside the project root: {path}")
    return resolved


def iter_project_files(root: Path):
    """Yield (relative POSIX path, absolute path) for every file under
    *root*, skipping VCS, cache, and build directories (SKIP_DIRS)."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS
                             and not d.endswith(".egg-info"))
        for name in sorted(filenames):
            p = Path(dirpath) / name
            yield p.relative_to(root).as_posix(), p


def project_facts(root: Path) -> dict:
    """Extract name, version, description, requires-python, scripts,
    and main from pyproject.toml and/or package.json.

    A field that cannot be found stays None (or empty): callers record
    it as "not found" rather than inventing a value. Unreadable or
    malformed metadata files are ignored, not fatal.
    """
    facts: dict = {"name": None, "version": None, "description": None,
                   "requires_python": None, "scripts": {}, "main": None}
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            # A metadata file that is a symlink out of the project (or
            # into private memory) must not contribute facts.
            pyproject = assert_project_local(root, pyproject)
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            proj = data.get("project", {})
            facts["name"] = proj.get("name") or facts["name"]
            facts["version"] = proj.get("version") or facts["version"]
            facts["description"] = proj.get("description") or facts["description"]
            facts["requires_python"] = proj.get("requires-python")
            facts["scripts"] = proj.get("scripts", {}) or {}
        except Exception:
            pass
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            pkg_json = assert_project_local(root, pkg_json)
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            facts["name"] = facts["name"] or data.get("name")
            facts["version"] = facts["version"] or data.get("version")
            facts["description"] = facts["description"] or data.get("description")
            facts["main"] = data.get("main")
            if isinstance(data.get("bin"), dict):
                facts["scripts"] = {**facts["scripts"], **data["bin"]}
            elif isinstance(data.get("bin"), str):
                facts["scripts"] = {**facts["scripts"], data.get("name", "bin"): data["bin"]}
        except Exception:
            pass
    return facts


def readme_path(root: Path) -> Path | None:
    """First existing README file at the project root, or None."""
    for name in ("README.md", "README.rst", "README.txt", "README"):
        p = root / name
        if p.exists():
            return p
    return None


def find_entry_points(root: Path, facts: dict) -> list[str]:
    """Sorted relative paths of likely entry points: console-script
    and package.json main targets, well-known entry filenames near
    the top of the tree, and shallow package ``__init__.py`` files."""
    entries: set[str] = set()
    # Script targets like "pkg.cli:main" point at a module file.
    for target in (facts.get("scripts") or {}).values():
        if isinstance(target, str) and ":" in target:
            module = target.split(":", 1)[0]
            rel = module.replace(".", "/")
            for cand in (f"{rel}.py", f"{rel}/__init__.py",
                         f"src/{rel}.py", f"src/{rel}/__init__.py"):
                if (root / cand).exists():
                    entries.add(cand)
    if facts.get("main"):
        if (root / facts["main"]).exists():
            entries.add(facts["main"])
    for rel, _p in iter_project_files(root):
        name = Path(rel).name
        depth = rel.count("/")
        if name in ENTRY_NAMES and depth <= 3:
            entries.add(rel)
        if name == "__init__.py" and depth <= 3 and rel.startswith(("src/", "")):
            # Package __init__ files near the top are orientation material.
            if depth <= 2:
                entries.add(rel)
    return sorted(entries)


def language_mix(root: Path) -> dict:
    """Count of code files per extension, most common first."""
    mix: dict[str, int] = {}
    for rel, _p in iter_project_files(root):
        ext = Path(rel).suffix.lower()
        if ext in CODE_EXTS:
            mix[ext] = mix.get(ext, 0) + 1
    return dict(sorted(mix.items(), key=lambda kv: -kv[1]))


def top_level_layout(root: Path) -> list[str]:
    """Sorted top-level names (directories suffixed with "/"),
    skipping hidden names and SKIP_DIRS."""
    out = []
    for child in sorted(root.iterdir(), key=lambda c: c.name):
        if child.name in SKIP_DIRS or child.name.startswith("."):
            continue
        out.append(child.name + ("/" if child.is_dir() else ""))
    return out


def python_fan_in(root: Path) -> dict[str, int]:
    """Count, per project module, how many project files import it."""
    module_of: dict[str, str] = {}
    files: list[tuple[str, Path]] = []
    for rel, p in iter_project_files(root):
        if Path(rel).suffix != ".py":
            continue
        files.append((rel, p))
        mod = rel[:-3].replace("/", ".")
        if mod.endswith(".__init__"):
            mod = mod[: -len(".__init__")]
        module_of[mod] = rel
        if mod.startswith("src."):
            # src-layout: the importable dotted name drops the src/ part.
            module_of[mod[len("src."):]] = rel
    def dotted(rel: str) -> str:
        base = rel[4:] if rel.startswith("src/") else rel
        mod = base[:-3].replace("/", ".")
        if mod.endswith(".__init__"):
            mod = mod[: -len(".__init__")]
        return mod

    fan_in: dict[str, int] = {rel: 0 for rel, _ in files}
    for rel, p in files:
        try:
            resolved = assert_project_local(root, p)
            tree = ast.parse(resolved.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    # Relative import: resolve against the importer's
                    # package (dotted name minus level-1 trailing parts;
                    # an __init__ file's package is its own dotted name).
                    parts = dotted(rel).split(".")
                    if not rel.endswith("__init__.py"):
                        parts = parts[:-1]
                    keep = max(0, len(parts) - (node.level - 1))
                    base = ".".join(parts[:keep])
                    module = f"{base}.{module}" if module else base
                if module:
                    imported.add(module)
                    for alias in node.names:
                        imported.add(f"{module}.{alias.name}")
        for name in imported:
            target = module_of.get(name)
            if target and target != rel:
                fan_in[target] = fan_in.get(target, 0) + 1
    return fan_in


# ---------------------------------------------------------------- JS/TS
# Parser-lite import graph for JS/TS, labelled parser-lite wherever it
# is recorded (slicing uses the same label for these languages). The
# scanner is string/comment aware in the GhostSlice parser-lite sense:
# comments are blanked and string/template contents are replaced by
# placeholders before import patterns run, so an import-shaped line
# inside a comment or a string literal is never counted, while a real
# import's specifier is recovered through its placeholder.

JS_EXTS = {".js", ".ts", ".tsx", ".jsx", ".mjs"}
# Resolution preference for extensionless specifiers (TS sources win,
# mirroring tsc/bundler resolution order).
_JS_RESOLVE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs")
# Keywords after which a "/" starts a regex literal, not a division.
_JS_REGEX_KEYWORDS = {
    "return", "typeof", "case", "delete", "void", "in", "of", "new",
    "instanceof", "yield", "await", "else", "do", "throw",
}


def _scan_js_string(src: str, i: int) -> tuple[str, int]:
    """src[i] is a quote. Return (raw inner text, index past the string)."""
    quote = src[i]
    n = len(src)
    j = i + 1
    while j < n:
        ch = src[j]
        if ch == "\\":
            j += 2
            continue
        if ch == quote:
            return src[i + 1:j], j + 1
        if ch == "\n":  # unterminated string; stop at the newline
            return src[i + 1:j], j
        j += 1
    return src[i + 1:n], n


def _scan_js_regex(src: str, i: int) -> int:
    """src[i] is the opening "/" of a regex literal. Return its end."""
    n = len(src)
    j = i + 1
    in_class = False
    while j < n:
        ch = src[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            j += 1
            while j < n and src[j].isalpha():  # flags
                j += 1
            return j
        elif ch == "\n":  # unterminated; bail out
            return j
        j += 1
    return n


def _scan_js_template(src: str, i: int, literals: list[str]):
    """src[i] is a backtick. Return (masked, literal_or_None, end).

    A template without ${} is a plain literal: its raw inner text is
    returned as the literal. A template with expressions returns masked
    text where the expression code stays visible (so a dynamic import
    inside it can still be found) and the literal text is blanked.
    """
    n = len(src)
    j = i + 1
    text_start = j
    parts: list[str] = []
    saw_expr = False
    while j < n:
        ch = src[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "`":
            raw = src[text_start:j]
            if not saw_expr:
                return "", raw, j + 1
            parts.append("".join("\n" if c == "\n" else " " for c in raw))
            return "".join(parts), None, j + 1
        if ch == "$" and src[j + 1:j + 2] == "{":
            raw = src[text_start:j]
            parts.append("".join("\n" if c == "\n" else " " for c in raw))
            parts.append("  ")
            code, k = _scan_js_code(src, j + 2, literals, in_tpl_expr=True)
            parts.append(code)
            parts.append(" ")
            saw_expr = True
            j = k
            text_start = j
            continue
        j += 1
    raw = src[text_start:n]
    if not saw_expr:
        return "", raw, n
    parts.append("".join("\n" if c == "\n" else " " for c in raw))
    return "".join(parts), None, n


def _scan_js_code(src: str, i: int, literals: list[str],
                  in_tpl_expr: bool = False) -> tuple[str, int]:
    """Mask JS/TS code starting at i. Return (masked, end index).

    Comments are replaced by spaces (newlines kept). Every string
    literal is replaced by a quoted placeholder holding its index into
    literals. When in_tpl_expr is set, scanning stops just past the
    "}" that closes the template expression.
    """
    out: list[str] = []
    n = len(src)
    depth = 0
    last = ""   # "value" after a value-ending token, else "op"/""
    word = ""   # trailing identifier being accumulated
    prev = ""
    while i < n:
        ch = src[i]
        two = src[i:i + 2]
        if two == "//":
            j = src.find("\n", i)
            if j < 0:
                j = n
            out.append(" " * (j - i))
            i = j
            continue
        if two == "/*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            seg = src[i:j]
            out.append("".join("\n" if c == "\n" else " " for c in seg))
            i = j
            continue
        if ch in "'\"":
            lit, j = _scan_js_string(src, i)
            literals.append(lit)
            out.append(f"{ch}\x00{len(literals) - 1}\x00{ch}")
            last, word, prev = "value", "", ch
            i = j
            continue
        if ch == "`":
            masked, lit, j = _scan_js_template(src, i, literals)
            if lit is not None:
                literals.append(lit)
                out.append(f"`\x00{len(literals) - 1}\x00`")
            else:
                out.append(masked)
            last, word, prev = "value", "", "`"
            i = j
            continue
        if ch == "/":
            if last == "value" and word not in _JS_REGEX_KEYWORDS:
                out.append(ch)  # division, keep as an ordinary operator
                last, word, prev = "op", "", ch
                i += 1
                continue
            j = _scan_js_regex(src, i)
            out.append(" " * (j - i))
            last, word, prev = "value", "", "/"
            i = j
            continue
        if ch == "{":
            depth += 1
            out.append(ch)
            last, word, prev = "op", "", ch
            i += 1
            continue
        if ch == "}":
            if in_tpl_expr and depth == 0:
                return "".join(out), i + 1
            depth -= 1
            out.append(ch)
            last, word, prev = "value", "", ch
            i += 1
            continue
        out.append(ch)
        if ch.isalnum() or ch in "_$":
            word += ch
            last = "value"
        elif not ch.isspace():
            if ch in "+-" and prev == ch:  # postfix ++ / --
                last = "value"
            else:
                last = "op"
            word = ""
            prev = ch
        i += 1
    return "".join(out), i


def _mask_js(source: str) -> tuple[str, list[str]]:
    literals: list[str] = []
    masked, _ = _scan_js_code(source, 0, literals)
    return masked, literals


_JS_SPEC = r"[\"']\x00(\d+)\x00[\"']"
_JS_SPEC_TPL = r"`\x00(\d+)\x00`"
_JS_IMPORT_PATTERNS = [
    # import ... from "x"  |  import "x"  (side effect). The clause
    # may not cross a ";" or a string placeholder, so a side-effect
    # import is never glued to a later statement's "from".
    re.compile(r"(?<![\w$.])import\s+(?:[^;\x00]*?\bfrom\s*)?" + _JS_SPEC),
    # export ... from "x"  (re-export)
    re.compile(r"(?<![\w$.])export\s+[^;\x00]*?\bfrom\s*" + _JS_SPEC),
    # require("x") and import("x"), quoted or template specifiers
    re.compile(r"(?<![\w$.])require\s*\(\s*(?:" + _JS_SPEC + "|"
               + _JS_SPEC_TPL + r")\s*\)"),
    re.compile(r"(?<![\w$.])import\s*\(\s*(?:" + _JS_SPEC + "|"
               + _JS_SPEC_TPL + r")\s*\)"),
    # import name = require("x")  (TypeScript import-equals)
    re.compile(r"(?<![\w$.])import\s+[\w$]+\s*=\s*require\s*\(\s*"
               + _JS_SPEC + r"\s*\)"),
]


def _js_import_specifiers(source: str) -> list[str]:
    masked, literals = _mask_js(source)
    specs: list[str] = []
    for pattern in _JS_IMPORT_PATTERNS:
        for match in pattern.finditer(masked):
            for group in match.groups():
                if group is not None:
                    idx = int(group)
                    if idx < len(literals):
                        specs.append(literals[idx])
                    break
    return specs


def _resolve_js_specifier(rel_set: set[str], importer_rel: str,
                          spec: str) -> str | None:
    """Resolve a relative specifier to a project file, or None.

    Relative specifiers only; bare specifiers are packages, not project
    files. Handles extensionless imports, directory index files, and
    the NodeNext convention of writing ".js" for a ".ts" source.
    """
    if not spec.startswith(("./", "../")):
        return None
    base = posixpath.normpath(
        posixpath.join(posixpath.dirname(importer_rel), spec))
    if base == ".." or base.startswith("../"):
        return None  # escapes the project root
    stem, ext = posixpath.splitext(base)
    candidates: list[str] = []
    if ext in JS_EXTS:
        candidates.append(base)
        if ext == ".js":
            candidates += [stem + ".ts", stem + ".tsx"]
        elif ext == ".jsx":
            candidates.append(stem + ".tsx")
    elif ext == "":
        candidates += [base + e for e in _JS_RESOLVE_EXTS]
        candidates += [base + "/index" + e for e in _JS_RESOLVE_EXTS]
    else:
        return None  # .json/.css/... imports are not code modules here
    for cand in candidates:
        if cand in rel_set:
            return cand
    return None


def js_fan_in(root: Path) -> dict[str, int]:
    """Count, per JS/TS file, how many project files import it.

    Parser-lite: relative import/export-from/require/dynamic-import
    specifiers are resolved statically. One count per importing file
    per target, mirroring python_fan_in.
    """
    files: list[tuple[str, Path]] = []
    for rel, p in iter_project_files(root):
        if Path(rel).suffix.lower() in JS_EXTS:
            files.append((rel, p))
    rel_set = {rel for rel, _ in files}
    fan_in: dict[str, int] = {rel: 0 for rel, _ in files}
    for rel, p in files:
        try:
            resolved = assert_project_local(root, p)
            source = resolved.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        targets: set[str] = set()
        for spec in _js_import_specifiers(source):
            target = _resolve_js_specifier(rel_set, rel, spec)
            if target and target != rel:
                targets.add(target)
        for target in targets:
            fan_in[target] = fan_in.get(target, 0) + 1
    return fan_in


def import_fan_in(root: Path) -> dict[str, int]:
    """Fan-in for every language with an import graph (Python via ast,
    JS/TS parser-lite). Files of other languages are absent from the
    result: their fan-in is unknown, not zero."""
    merged = python_fan_in(root)
    merged.update(js_fan_in(root))
    return merged


def fan_in_method(rel: str) -> str:
    """How the fan-in recorded for rel was derived: ast, parser-lite,
    or none (no import graph for that language; fan-in unknown)."""
    ext = Path(rel).suffix.lower()
    if ext == ".py":
        return "ast"
    if ext in JS_EXTS:
        return "parser-lite"
    return "none"
