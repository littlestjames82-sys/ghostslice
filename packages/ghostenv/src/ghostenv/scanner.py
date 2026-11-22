"""Static scan for environment variable reads in source code.

Each finding records: name, relative file, line, pattern kind, a
``has_default`` boolean, and a confidence marker (``static`` or
``parser-lite`` for shell). Argument text beyond the variable name is
never captured into a finding: patterns are written so the only group
that survives is the name (plus, for defaults, the mere presence of a
second argument, detected structurally, never its text).

Dynamic reads (name held in a variable, template strings) cannot be
resolved statically. They are counted per site as ``dynamic`` records
with file + line only, never guessed at.

Ruby and Java/Kotlin support (PLAN's named v0.2 candidates, added
in the deepen round) is parser-lite in the same sense as shell:
Ruby ``ENV[...]`` / ``ENV.fetch(...)`` and Java/Kotlin
``System.getenv(...)`` / ``System.getenv().getOrDefault(...)`` /
Spring ``@Value("${NAME}")`` placeholders. Default detection stays
structural: a comma, an ``||`` / ``?:`` marker, a fetch block, or
the colon inside a Spring placeholder; the default's text is never
captured, exactly like every other language above.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from .envparse import is_valid_name

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv",
    "venv", ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    "vendor", ".next", ".idea",
}
# env-style files themselves are parsed by envparse, not scanned here:
# a KEY= line there is a definition, not a code read.
SKIP_FILENAMES = {
    ".env", ".env.example", ".env.sample", ".env.template",
    ".env.local", ".env.production", ".env.development", ".env.test",
}
MAX_FILE_BYTES = 2_000_000

CODE_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
             ".go", ".rs", ".sh", ".bash",
             ".rb", ".rake", ".java", ".kt", ".kts"}

_NAME = r"([A-Za-z_][A-Za-z0-9_]*)"
_QNAME = r"[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']"

# (pattern, kind, has_default_group_or_None, confidence)
# has_default is detected by an optional trailing group whose *presence*
# is checked; its contents use [^)] / [^\]] character classes and are
# captured into a throwaway group that is never read.
_PATTERNS: list[tuple[re.Pattern, str, str]] = []

def _add(source: str, kind: str, confidence: str = "static"):
    _PATTERNS.append((re.compile(source), kind, confidence))

# --- Python ---
_add(r"os\.environ\.get\(\s*" + _QNAME + r"\s*(,)?", "py-environ-get")
_add(r"os\.getenv\(\s*" + _QNAME + r"\s*(,)?", "py-getenv")
_add(r"(?<![\w.])getenv\(\s*" + _QNAME + r"\s*(,)?", "py-getenv")
_add(r"(?<![\w.])environ\.get\(\s*" + _QNAME + r"\s*(,)?",
     "py-environ-get")
_add(r"os\.environ\.setdefault\(\s*" + _QNAME + r"\s*(,)?",
     "py-environ-setdefault")
_add(r"(?<![\w.])environ\.setdefault\(\s*" + _QNAME + r"\s*(,)?",
     "py-environ-setdefault")
_add(r"os\.environ\[\s*" + _QNAME + r"\s*\]", "py-environ-subscript")
_add(r"(?<![\w.])environ\[\s*" + _QNAME + r"\s*\]", "py-environ-subscript")
_add(r"os\.environ\.pop\(\s*" + _QNAME + r"\s*(,)?", "py-environ-pop")
_add(_QNAME + r"\s+in\s+os\.environ\b", "py-environ-membership")
# Python `or` fallback: os.environ.get("X", ...) or <fallback> and
# os.getenv("X") or <fallback>. The marker group is the word "or";
# the fallback text itself is never captured.
_add(r"os\.environ\.get\(\s*" + _QNAME + r"[^)]*\)\s+(or)\b",
     "py-environ-get")
_add(r"os\.getenv\(\s*" + _QNAME + r"[^)]*\)\s+(or)\b", "py-getenv")
_add(r"(?<![\w.])getenv\(\s*" + _QNAME + r"[^)]*\)\s+(or)\b",
     "py-getenv")
_add(r"(?<![\w.])environ\.get\(\s*" + _QNAME + r"[^)]*\)\s+(or)\b",
     "py-environ-get")
# --- JavaScript / TypeScript ---
_add(r"process\.env\." + _NAME, "js-dot")
_add(r"process\.env\[\s*" + _QNAME + r"\s*\]", "js-subscript")
# destructuring: const { A, B: alias, C = fallback } = process.env
_DESTRUCTURE_RE = re.compile(
    r"\{([^{}]*)\}\s*=\s*process\.env\b")
# fallback markers: presence only, text unread (|| and ??)
_add(r"process\.env\." + _NAME + r"\s*(\|\|)", "js-dot")
_add(r"process\.env\[\s*" + _QNAME + r"\s*\]\s*(\|\|)", "js-subscript")
_add(r"process\.env\." + _NAME + r"\s*(\?\?)", "js-dot")
_add(r"process\.env\[\s*" + _QNAME + r"\s*\]\s*(\?\?)", "js-subscript")
# --- Go ---
_add(r"os\.Getenv\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"", "go-getenv")
_add(r"os\.LookupEnv\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"", "go-lookupenv")
# --- Rust ---
_add(r"(?:std::)?env!\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"", "rust-env-macro")
_add(r"option_env!\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"",
     "rust-option-env-macro")
_add(r"(?:std::env::|env::)var\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"",
     "rust-var")
_add(r"(?:std::env::|env::)var_os\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"",
     "rust-var-os")
# .unwrap_or(...) / .unwrap_or_default() after a var() call supplies
# a fallback; the marker group is the method name, text unread.
_add(r"(?:std::env::|env::)var\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""
     r"\s*\)\s*(\.unwrap_or(?:_default)?)\b", "rust-var")
# --- Ruby (parser-lite) ---
# ENV["NAME"] / ENV['NAME']; a trailing || supplies a fallback.
_add(r"ENV\[\s*" + _QNAME + r"\s*\]", "ruby-env-subscript", "parser-lite")
_add(r"ENV\[\s*" + _QNAME + r"\s*\]\s*(\|\|)", "ruby-env-subscript", "parser-lite")
# ENV.fetch("NAME", default): the comma proves a default argument;
# its text is never captured. ENV.fetch("NAME") { ... } supplies the
# fallback as a block: the marker group is the opening brace only.
_add(r"ENV\.fetch\(\s*" + _QNAME + r"\s*(,)?", "ruby-env-fetch", "parser-lite")
_add(r"ENV\.fetch\(\s*" + _QNAME + r"\s*\)\s*(\{)",
     "ruby-env-fetch", "parser-lite")
# --- Java / Kotlin (parser-lite) ---
# System.getenv("NAME"): Java/Kotlin offer no default at this call,
# so a plain read is a plain read (hard when missing, like Go).
_add(r"System\.getenv\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"",
     "java-getenv", "parser-lite")
# Kotlin elvis fallback: System.getenv("NAME") ?: fallback.
_add(r"System\.getenv\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""
     r"\s*\)\s*(\?:)", "java-getenv", "parser-lite")
# System.getenv().getOrDefault("NAME", default): comma = default
# present, text never captured.
_add(r"System\.getenv\(\)\.getOrDefault\(\s*"
     r"\"([A-Za-z_][A-Za-z0-9_]*)\"\s*(,)?", "java-getenv-or-default", "parser-lite")
# Spring @Value("${NAME}") / @Value("${NAME:default}"): the colon
# inside the placeholder proves a default; everything after it up
# to } is default text and is never captured. Parser-lite.
_add(r"@Value\([^)]*\$\{([A-Za-z_][A-Za-z0-9_]*)(:)?",
     "java-spring-value", "parser-lite")
# --- Shell (parser-lite, uppercase names only) ---
# POSIX forms with and without the colon: ${NAME:-d} ${NAME-d}
# ${NAME:=d} ${NAME=d} (defaults), ${NAME:+a} ${NAME:?e} (not).
_SHELL_RE = re.compile(
    r"\$(?:\{([A-Z_][A-Z0-9_]*)(?::?[-=?+][^}]*)?\}|([A-Z_][A-Z0-9_]*))")

# Groups whose presence in a match means "this read site supplies a
# default / fallback". Their text is a fixed marker, never a value.
# (":" is the Spring placeholder default separator, "{" a Ruby
# fetch block opener, "?:" the Kotlin elvis operator.)
_DEFAULT_MARKERS = (",", "||", "??", "or", ".unwrap_or",
                    ".unwrap_or_default", ":", "{", "?:")

# Dynamic read sites: a read whose name argument is not a literal.
# Tagged with the language they belong to, like _PATTERNS, so a
# Python dynamic shape in a JS file (or vice versa) is not counted.
_DYNAMIC_RES = [
    (re.compile(r"os\.environ\.get\(\s*(?![\"'])[A-Za-z_][\w.]*\s*[,)]"), "py"),
    (re.compile(r"os\.getenv\(\s*(?![\"'])[A-Za-z_][\w.]*\s*[,)]"), "py"),
    (re.compile(r"os\.environ\[\s*(?![\"'])[^\]]+\]"), "py"),
    (re.compile(r"process\.env\[\s*(?![\"'])[^\]]+\]"), "js"),
    (re.compile(r"process\.env\.\$\{"), "js"),
    # f-string names: os.getenv(f"{PREFIX}_KEY") - dynamic by shape.
    (re.compile(r"os\.(?:environ\.get|getenv)\(\s*f[\"']"), "py"),
    (re.compile(r"(?<![\w.])getenv\(\s*f[\"']"), "py"),
    # Bare forms (from os import getenv / environ): the static
    # patterns recognise these, so the dynamic shapes must too -
    # previously getenv(k) / environ[k] / environ.get(k) vanished
    # entirely instead of counting as dynamic sites.
    (re.compile(r"(?<![\w.])getenv\(\s*(?![\"'])[A-Za-z_][\w.]*\s*[,)]"), "py"),
    (re.compile(r"(?<![\w.])environ\.get\(\s*(?![\"'])[A-Za-z_][\w.]*\s*[,)]"), "py"),
    (re.compile(r"(?<![\w.])environ\[\s*(?![\"'])[^\]]+\]"), "py"),
    (re.compile(r"(?<![\w.])environ\.get\(\s*f[\"']"), "py"),
    # Ruby dynamic reads: ENV[some_var], ENV.fetch(some_var).
    (re.compile(r"ENV\[\s*(?![\"'])[^\]]+\]"), "ruby"),
    (re.compile(r"ENV\.fetch\(\s*(?![\"'])[A-Za-z_][\w.]*\s*[,)]"), "ruby"),
    # Ruby interpolated name: ENV["#{prefix}_KEY"] - dynamic by shape.
    (re.compile(r"ENV\[\s*[\"']#\{"), "ruby"),
    # Java/Kotlin dynamic read: System.getenv(some_var).
    (re.compile(r"System\.getenv\(\s*(?!\")[A-Za-z_][\w.]*\s*\)"), "java"),
]

# File extension -> pattern language. Patterns are language-specific
# by construction (PLAN lists them per language); applying every
# pattern to every file made e.g. a JS file containing the text
# os.environ.get("X") report a "static" Python read.
_EXT_LANG = {".py": "py", ".js": "js", ".jsx": "js", ".ts": "js",
             ".tsx": "js", ".mjs": "js", ".cjs": "js", ".go": "go",
             ".rs": "rust", ".rb": "ruby", ".rake": "ruby",
             ".java": "java", ".kt": "java", ".kts": "java"}
_KIND_LANG = {"py": "py", "js": "js", "go": "go", "rust": "rust",
              "ruby": "ruby", "java": "java"}


def _visible_after_block_comments(line: str, depth: int):
    """Strip /* ... */ spans (stateful, nesting-aware).

    Returns (visible_text, new_depth). Text inside a block comment
    is not code: previously only lines *starting* with //, /* or *
    were skipped, so the interior lines of a multi-line block
    comment were scanned and their mentions counted as real reads.
    String literals containing /* or */ remain a parser-lite edge.
    """
    out: list[str] = []
    i = 0
    while i < len(line):
        if depth:
            nxt_open = line.find("/*", i)
            nxt_close = line.find("*/", i)
            if nxt_close == -1:
                return "".join(out), depth
            if nxt_open != -1 and nxt_open < nxt_close:
                depth += 1
                i = nxt_open + 2
            else:
                depth -= 1
                i = nxt_close + 2
        else:
            nxt = line.find("/*", i)
            if nxt == -1:
                out.append(line[i:])
                break
            out.append(line[i:nxt])
            depth = 1
            i = nxt + 2
    return "".join(out), depth


def _iter_files(project: Path, extra_ignore: list[str]):
    """Yield ``(path, relative_path)`` for scannable source files
    under *project*, skipping VCS/vendor/build directories,
    env-style files (parsed elsewhere), oversized files, and
    paths matched by *extra_ignore* globs."""
    try:
        project_root = project.resolve()
    except (OSError, RuntimeError):
        project_root = project.absolute()
    for path in sorted(project.rglob("*")):
        if not path.is_file():
            continue
        if path.is_symlink():
            # PLAN: no reading outside the project root except files
            # the user explicitly passes. A symlinked source file
            # pointing outside was followed and scanned; a symlink
            # whose target stays inside the project is still fine.
            try:
                resolved = path.resolve()
            except (OSError, RuntimeError):
                continue
            if not resolved.is_relative_to(project_root):
                continue
        rel = path.relative_to(project)
        parts = rel.parts
        if any(p in SKIP_DIRS for p in parts[:-1]) or \
                parts[0] in SKIP_DIRS:
            continue
        if path.name in SKIP_FILENAMES or path.suffix == ".pyc":
            continue
        if path.suffix.lower() not in CODE_EXTS:
            continue
        rel_str = rel.as_posix()
        if any(fnmatch.fnmatch(rel_str, g) or fnmatch.fnmatch(path.name, g)
               for g in extra_ignore):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path, rel_str


def _shell_has_default(match_text: str, name: str) -> bool:
    """True for ${NAME-default} / ${NAME:-default} / ${NAME=default}
    / ${NAME:=default} shapes. ${NAME:+alt} and ${NAME:?err} are not
    defaults: one substitutes only when set, the other errors out.
    Inspects the operator characters only, never the default text."""
    if not match_text.startswith("${"):
        return False
    rest = match_text[2 + len(name):].lstrip(":")
    return rest[:1] in ("-", "=")


def scan_project(project, extra_ignore=None) -> dict:
    """Scan a project tree for environment reads.

    Returns {"findings": [...], "dynamic_sites": [...],
             "files_scanned": int, "by_name": {name: [findings]}}.
    Findings carry names only (see module docstring).
    """
    project = Path(project)
    extra_ignore = list(extra_ignore or [])
    findings: list[dict] = []
    dynamic: list[dict] = []
    files_scanned = 0

    for path, rel in _iter_files(project, extra_ignore):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files_scanned += 1
        is_shell = path.suffix.lower() in (".sh", ".bash")
        slash_comments = path.suffix.lower() in (
            ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs",
            ".java", ".kt", ".kts")
        lang = _EXT_LANG.get(path.suffix.lower())
        block_depth = 0
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            # Full-line comments are not reads, in any language
            # (polish fix: shell # lines and JS/Go/Rust // lines
            # used to produce findings). Trailing comments after
            # code on the same line are still scanned: parser-lite.
            if stripped.startswith("#"):
                continue
            if slash_comments:
                # Multi-line /* ... */ interiors are not reads
                # either; strip block spans (keeping any code that
                # shares the line) and skip // full-line comments.
                if block_depth == 0 and stripped.startswith("//"):
                    continue
                line, block_depth = _visible_after_block_comments(
                    line, block_depth)
                if not line.strip() or \
                        line.lstrip().startswith("//"):
                    continue
            if is_shell:
                for m in _SHELL_RE.finditer(line):
                    name = m.group(1) or m.group(2)
                    if name and is_valid_name(name):
                        findings.append({
                            "name": name, "file": rel, "line": lineno,
                            "kind": "shell-var",
                            "has_default": _shell_has_default(
                                m.group(0), name),
                            "confidence": "parser-lite",
                        })
                continue
            for rx, kind, confidence in _PATTERNS:
                if _KIND_LANG.get(kind.split("-", 1)[0]) != lang:
                    continue
                for m in rx.finditer(line):
                    # The name is always the first group that is a
                    # valid env name; default groups are "," markers.
                    name = None
                    has_default = False
                    for g in m.groups():
                        if g in _DEFAULT_MARKERS:
                            has_default = True
                        elif g is not None and name is None and \
                                is_valid_name(g):
                            name = g
                    if name:
                        findings.append({
                            "name": name, "file": rel, "line": lineno,
                            "kind": kind,
                            "has_default": has_default,
                            "confidence": confidence,
                        })
            for m in (_DESTRUCTURE_RE.finditer(line)
                      if lang == "js" else ()):
                inner = m.group(1)
                for part in inner.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    head = re.split(r"[:=]", part, maxsplit=1)
                    cand = head[0].strip()
                    if is_valid_name(cand):
                        findings.append({
                            "name": cand, "file": rel, "line": lineno,
                            "kind": "js-destructure",
                            "has_default": "=" in part,
                            "confidence": "static",
                        })
            for rx, rx_lang in _DYNAMIC_RES:
                if rx_lang == lang and rx.search(line):
                    dynamic.append({"file": rel, "line": lineno})
                    break

    # De-duplicate identical (name, file, line, kind) rows, which the
    # overlapping JS fallback pattern can produce.
    seen: dict[tuple, dict] = {}
    uniq = []
    for f in findings:
        key = (f["name"], f["file"], f["line"], f["kind"])
        if key in seen:
            # Same read seen twice (plain + fallback-marker pattern):
            # a fallback found by either pattern belongs to the site.
            seen[key]["has_default"] = (seen[key]["has_default"]
                                        or f["has_default"])
        else:
            seen[key] = f
            uniq.append(f)
    uniq.sort(key=lambda f: (f["name"], f["file"], f["line"]))
    dynamic.sort(key=lambda d: (d["file"], d["line"]))

    by_name: dict[str, list[dict]] = {}
    for f in uniq:
        by_name.setdefault(f["name"], []).append(f)
    return {
        "findings": uniq,
        "dynamic_sites": dynamic,
        "files_scanned": files_scanned,
        "by_name": by_name,
    }
