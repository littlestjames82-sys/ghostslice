"""GhostSlice integration + a stdlib fallback engine.

GhostAtlas is built on GhostSlice data: when the ``ghostslice``
package is importable (installed, on PYTHONPATH, or in the sibling
``~/workspace/ghostslice/src`` checkout in the studio workspace), its
scanner / import graph / entry candidates / duplicates / call graph
are used directly, so Atlas numbers are GhostSlice numbers.

When GhostSlice is not available, a documented fallback engine in
this module supplies the same shapes (scanner with .gitignore-lite,
the same BPE-like token estimator method, Python ast import graph,
TS/JS import regexes). The fallback is labelled in the run stamp
(``engine: fallback``) wherever results surface, never silently.
"""
from __future__ import annotations

import ast
import fnmatch
import math
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

# ---------------------------------------------------------------------------
# GhostSlice discovery
# ---------------------------------------------------------------------------

def _ghostslice_src_candidates():
    """Candidate ``src/`` directories to look for GhostSlice in.

    Order matters: the ``GHOSTATLAS_GHOSTSLICE_SRC`` and
    ``GHOSTSLICE_SRC`` environment variables first, then a sibling
    checkout, the current directory, and ``~/workspace``.
    """
    here = Path(__file__).resolve()
    # src/ghostatlas/engine.py -> parents: [0] ghostatlas, [1] src,
    # [2] project root, [3] workspace dir holding sibling projects.
    out = []
    for env in ("GHOSTATLAS_GHOSTSLICE_SRC", "GHOSTSLICE_SRC"):
        val = os.environ.get(env)
        if val:
            out.append(Path(val))
    if len(here.parents) > 3:
        out.append(here.parents[3] / "ghostslice" / "src")
    out.append(Path.cwd() / "ghostslice" / "src")
    out.append(Path.home() / "workspace" / "ghostslice" / "src")
    return out


def load_ghostslice():
    """Return the ``ghostslice`` package module, or ``None``.

    Tries a normal import first, then each candidate directory from
    :func:`_ghostslice_src_candidates`. ``None`` is a normal result,
    not an error: callers fall back to this module's fallback engine
    and label the run ``engine: fallback``.
    """
    try:
        import ghostslice  # noqa: F401
        return ghostslice
    except Exception:
        pass
    for cand in _ghostslice_src_candidates():
        try:
            if (cand / "ghostslice" / "__init__.py").is_file():
                sp = str(cand)
                if sp not in sys.path:
                    sys.path.insert(0, sp)
                import ghostslice
                return ghostslice
        except Exception:
            continue
    return None


ENGINE_NAME = "ghostslice" if load_ghostslice() is not None else "fallback"

# ---------------------------------------------------------------------------
# Token estimator (same method as GhostSlice tokens.py v2, fallback only;
# when GhostSlice is present its own estimator produced the counts).
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\w\s]")
_FAMILY = {
    "python": 0.86, "typescript": 0.75, "javascript": 0.75, "go": 0.73,
    "rust": 0.89, "markdown": 0.85, "text": 0.85, "json": 0.95,
    "yaml": 0.95, "toml": 0.95,
}


def estimate_tokens(text: str, language: str | None = None) -> int:
    """Estimate the token count of ``text`` (fallback engine only).

    Uses the same method as GhostSlice's estimator: words and
    punctuation count as one token up to four characters, longer
    runs scale by length, and the total is adjusted by a per-language
    family factor. The result is an *estimate*, consistent with what
    a GhostSlice scan reports, not an exact tokenizer count. When
    GhostSlice itself is present, its estimator produces the counts
    and this function is not used for them.
    """
    if not text:
        return 0
    raw = 0
    for match in _TOKEN_RE.findall(text):
        n = len(match)
        raw += 1 if n <= 4 else int(math.ceil(n / 4))
    factor = _FAMILY.get(language or "", 1.0)
    return raw if factor == 1.0 else int(raw * factor + 0.5)


# ---------------------------------------------------------------------------
# Fallback scanner
# ---------------------------------------------------------------------------

LANGUAGE_BY_EXT = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".cjs": "javascript", ".md": "markdown", ".markdown": "markdown",
    ".txt": "text", ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".go": "go", ".rs": "rust", ".java": "java",
    ".cs": "csharp", ".php": "php", ".rb": "ruby", ".kt": "kotlin",
    ".swift": "swift", ".c": "c", ".h": "c", ".cpp": "cpp",
    ".html": "html", ".css": "css", ".sh": "shell", ".sql": "sql",
    ".xml": "xml", ".cfg": "config", ".ini": "config",
}
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "dist", "build", "out",
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache",
    ".pytest_cache", ".next", ".nuxt", "coverage", ".cache", "target",
    ".idea", ".vscode", ".claude_context", ".ghostslice-cache",
}
BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".pdf",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".exe", ".dll",
    ".so", ".dylib", ".o", ".a", ".class", ".wasm", ".mp3", ".mp4",
    ".mov", ".avi", ".woff", ".woff2", ".ttf", ".eot", ".pyc", ".pyo",
    ".db", ".sqlite", ".sqlite3",
}
LOCKFILES = {
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock",
    "Pipfile.lock", "Cargo.lock", "composer.lock", "Gemfile.lock",
    "go.sum", "uv.lock",
}


@dataclass
class FileRec:
    """One scanned file in the fallback engine.

    Mirrors the shape of a GhostSlice scan record closely enough for
    the data assembly in :mod:`ghostatlas.data` to treat both
    engines the same way. ``path`` is project-relative with forward
    slashes; ``abspath`` never leaves the fallback scan.
    """

    path: str
    abspath: str
    size: int = 0
    lines: int = 0
    tokens: int = 0
    language: str = "other"
    is_test: bool = False
    is_lockfile: bool = False
    is_generated: bool = False
    is_minified: bool = False
    is_vendored: bool = False
    detect_evidence: dict = field(default_factory=dict)
    package: str = ""

    def to_dict(self):
        return dict(self.__dict__)


@dataclass
class ScanRec:
    """A fallback scan result: the root plus its :class:`FileRec` list."""

    root: str
    files: list = field(default_factory=list)
    packages: list = field(default_factory=list)

    @property
    def total_tokens(self):
        return sum(f.tokens for f in self.files)

    @property
    def total_size(self):
        return sum(f.size for f in self.files)


def _is_test(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    name = parts[-1] if parts else rel
    return (
        any(p in ("test", "tests", "__tests__", "spec") for p in parts[:-1])
        or name.startswith(("test_", "test."))
        or ".test." in name or ".spec." in name or name.endswith("_test.py")
        or name.endswith("_test.go")
    )


def _gitignore_patterns(root: Path):
    pats = []
    gi = root / ".gitignore"
    if gi.is_file():
        try:
            for ln in gi.read_text(encoding="utf-8", errors="replace").splitlines():
                ln = ln.strip()
                if ln and not ln.startswith("#"):
                    pats.append(ln)
        except OSError:
            pass
    return pats


def _ignored(rel: str, is_dir: bool, pats) -> bool:
    name = PurePosixPath(rel).name
    ignored = False
    for pat in pats:
        p = pat.strip()
        neg = p.startswith("!")
        if neg:
            p = p[1:]
        p = p.strip("/")
        if not p:
            continue
        hit = (
            fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p + "/*")
            or fnmatch.fnmatch(name, p)
            or (is_dir and (rel == p or rel.startswith(p + "/")))
        )
        if hit:
            # gitignore semantics: the LAST matching pattern decides,
            # so a later "!name" re-includes a file an earlier pattern
            # excluded. (Previously negation patterns were parsed but
            # had no effect at all.)
            ignored = not neg
    return ignored


def _looks_minified(text: str) -> bool:
    if len(text) < 400:
        return False
    lines = text.splitlines()
    if not lines:
        return False
    return max(len(x) for x in lines) >= 300 and len(text) / len(lines) >= 200


def _looks_generated(text: str) -> bool:
    head = "\n".join(text.splitlines()[:5]).lower()
    # Same markers GhostSlice's detect uses: any one suffices. (The
    # old expression's and/or precedence silently required "generated"
    # alongside "do not edit", so a plain "do not edit" header - a
    # GhostSlice generated signal - was missed.)
    return any(m in head for m in
               ("generated by", "autogenerated by", "do not edit", "@generated"))


def fallback_scan(root: str | Path) -> ScanRec:
    """Scan ``root`` with the fallback engine and return a ScanRec.

    Walks the tree skipping VCS/build/vendor directories and binary
    files, honours a lite subset of ``.gitignore``, estimates tokens
    per file, and flags test, lockfile, generated, minified, and
    vendored files. Used only when GhostSlice is not importable.
    """
    root = Path(root).resolve()
    pats = _gitignore_patterns(root)
    result = ScanRec(root=str(root))
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        rel_dir = d.relative_to(root).as_posix() if d != root else ""
        dirnames[:] = [
            n for n in sorted(dirnames)
            if n not in SKIP_DIRS
            and not _ignored((rel_dir + "/" + n).strip("/"), True, pats)
        ]
        for name in sorted(filenames):
            rel = (rel_dir + "/" + name).strip("/")
            if _ignored(rel, False, pats):
                continue
            ap = d / name
            ext = ap.suffix.lower()
            if ext in BINARY_EXTS:
                continue
            try:
                raw = ap.read_bytes()
                text = raw.decode("utf-8", errors="replace")
            except OSError:
                continue
            lang = LANGUAGE_BY_EXT.get(ext, "other")
            entry = FileRec(
                path=rel, abspath=str(ap), size=len(raw),
                lines=text.count("\n") + (1 if text and not text.endswith("\n") else 0),
                tokens=estimate_tokens(text, lang), language=lang,
                is_test=_is_test(rel), is_lockfile=name in LOCKFILES,
            )
            parts = PurePosixPath(rel).parts
            if any(p in ("vendor", "vendors", "third_party", "thirdparty")
                   for p in parts[:-1]):
                entry.is_vendored = True
                entry.detect_evidence["vendored"] = "path segment: " + parts[0]
            if lang in ("javascript", "typescript") and _looks_minified(text):
                entry.is_minified = True
                entry.detect_evidence["minified"] = "long lines, low newline ratio"
            if lang not in ("markdown",) and _looks_generated(text):
                entry.is_generated = True
                entry.detect_evidence["generated"] = "generated marker in file header"
            entry.package = rel.rsplit("/", 1)[0] if "/" in rel else ""
            result.files.append(entry)
    pkgs: dict[str, dict] = {}
    for f in result.files:
        pkg = pkgs.setdefault(f.package, {"path": f.package, "files": 0,
                                         "tokens": 0, "size": 0})
        pkg["files"] += 1
        pkg["tokens"] += f.tokens
        pkg["size"] += f.size
    result.packages = sorted(pkgs.values(), key=lambda p: p["path"])
    return result


# ---------------------------------------------------------------------------
# Fallback import graph + entry candidates
# ---------------------------------------------------------------------------

_IMPORT_RE = re.compile(r"""(?:import|export)\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]""")
_REQUIRE_RE = re.compile(r"""(?:require|import)\s*\(\s*['"]([^'"]+)['"]\s*\)""")
_ENTRY_NAMES = {
    "main.py", "main.ts", "main.js", "main.mjs", "__main__.py",
    "index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs",
    "app.py", "app.ts", "app.js", "cli.py", "cli.ts", "cli.js",
    "cli.mjs", "server.py", "server.ts", "server.js", "server.mjs",
    "handler.py", "handler.js", "manage.py", "run.py",
}


def _read(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def fallback_graph(scan: ScanRec) -> dict:
    """Build the fallback import graph for a fallback scan.

    Returns ``{path: {"imports": [...], "external": [...]}}`` in the
    same shape GhostSlice's graph builder returns. Python imports
    are resolved via ``ast``; TypeScript/JavaScript imports via
    regex over import/require specifiers. Unresolved specifiers are
    reported as external, never dropped silently.
    """
    root_files = {f.path for f in scan.files}
    graph = {}
    for entry in scan.files:
        edges, external = [], []
        src = _read(entry.abspath)
        if entry.language == "python":
            try:
                tree = ast.parse(src)
            except Exception:
                tree = None
            if tree is not None:
                cur = PurePosixPath(entry.path).parent
                for node in ast.walk(tree):
                    mods = []
                    dot_names = False
                    if isinstance(node, ast.Import):
                        mods = [a.name for a in node.names]
                        lvl = 0
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            mods = [node.module]
                        elif node.level:
                            # `from . import helper` / `from .. import x`:
                            # the imported names ARE the modules (or
                            # names re-exported by the package __init__).
                            # These used to be dropped silently - no
                            # edge, not even an external entry.
                            mods = [a.name for a in node.names]
                            dot_names = True
                        else:
                            mods = []
                        lvl = node.level
                    else:
                        continue
                    for mod in mods:
                        base = list(cur.parts) if lvl else []
                        if lvl:
                            base = base[: max(0, len(base) - (lvl - 1))] if lvl > 1 else base
                        cand = "/".join([p for p in base if p != "."] + mod.split("."))
                        for suffix in (".py", "/__init__.py"):
                            if cand + suffix in root_files:
                                edges.append(cand + suffix)
                                break
                        else:
                            init = "/".join(
                                [p for p in base if p != "."] + ["__init__.py"])
                            if dot_names and init in root_files:
                                edges.append(init)
                            else:
                                external.append(mod)
        elif entry.language in ("typescript", "javascript"):
            specs = _IMPORT_RE.findall(src) + _REQUIRE_RE.findall(src)
            cur = PurePosixPath(entry.path).parent
            for spec in specs:
                if not spec.startswith("."):
                    external.append(spec)
                    continue
                parts = [p for p in cur.parts if p != "."]
                for seg in spec.split("/"):
                    if seg == "..":
                        if parts:
                            parts.pop()
                    elif seg not in (".", ""):
                        parts.append(seg)
                cand = "/".join(parts)
                hit = None
                # An explicit extension may already name the real file
                # ("./data.json"), and TS ESM style "./util.js" usually
                # means util.ts on disk. Both used to miss every
                # candidate and be misreported as external imports.
                direct = [cand]
                if cand.endswith(".js"):
                    direct += [cand[:-3] + ".ts", cand[:-3] + ".tsx"]
                elif cand.endswith(".jsx"):
                    direct += [cand[:-4] + ".tsx"]
                for cand0 in direct:
                    if cand0 in root_files:
                        hit = cand0
                        break
                if hit is None:
                    for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".json",
                                "/index.ts", "/index.js",
                                "/index.tsx", "/index.jsx"):
                        if cand + ext in root_files:
                            hit = cand + ext
                            break
                if hit:
                    edges.append(hit)
                else:
                    external.append(spec)
        graph[entry.path] = {
            "imports": sorted({e for e in edges if e != entry.path}),
            "external": sorted(set(external)),
        }
    return graph


def fallback_entries(scan: ScanRec, graph: dict) -> list:
    """Return fallback entry-point candidates for a scan.

    Each candidate carries a score and the factual ``signals`` that
    produced it (entry-like file name, ``__main__`` guard, shebang,
    nothing importing it), mirroring GhostSlice's entry evidence so
    the reading order can show its reasons either way.
    """
    importers = {}
    for src, data in graph.items():
        for dst in data.get("imports", []):
            importers.setdefault(dst, []).append(src)
    out = []
    for f in scan.files:
        if f.is_test or f.is_vendored or f.is_generated:
            continue
        signals = []
        score = 0
        if PurePosixPath(f.path).name in _ENTRY_NAMES:
            signals.append("name matches the entry-point heuristic (main/cli/app/server/index/...)")
            score += 40
        if f.language == "python":
            text = _read(f.abspath)
            if '__name__ == "__main__"' in text or "__name__ == '__main__'" in text:
                signals.append('has an `if __name__ == "__main__"` guard')
                score += 35
        first = _read(f.abspath).splitlines()[:1]
        if first and first[0].startswith("#!"):
            signals.append("starts with a shebang")
            score += 25
        if not signals:
            continue
        if not importers.get(f.path):
            signals.append("nothing in the project imports it")
            score += 10
        out.append({"path": f.path, "score": score, "signals": signals})
    out.sort(key=lambda c: (-c["score"], c["path"]))
    return out
