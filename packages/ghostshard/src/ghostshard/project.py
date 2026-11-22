"""Project scanning, symbol extraction, and import graph.

Python files are parsed with stdlib ``ast`` (complete edges).
Other languages are parser-lite: import/require lines only, and the
plan records the seam basis per shard so that limit is never hidden.
"""
from __future__ import annotations
import ast, re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_IGNORES = {".git", "__pycache__", "node_modules", "dist", "build",
                   ".venv", "venv", ".ghostshard", ".claude_context", ".ghostslice-cache"}
TEXT_EXTS = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".md", ".txt",
             ".go", ".rs", ".java", ".c", ".h", ".cpp", ".json", ".toml"}

@dataclass
class FileInfo:
    """One scanned project file and what the scanner learned about it.

    ``symbols`` are names defined here, ``imports`` are resolved
    project-internal paths this file imports, ``external_imports``
    are import names that did not resolve inside the project, and
    ``references`` are names used (Python only, via ``ast``).
    """

    rel: str
    text: str
    language: str = "other"
    symbols: list = field(default_factory=list)       # symbols defined here
    imports: list = field(default_factory=list)        # resolved rel paths
    external_imports: list = field(default_factory=list)
    references: set = field(default_factory=set)       # names used (python ast)

    @property
    def package(self) -> str:
        parts = Path(self.rel).parts
        return parts[0] if len(parts) > 1 else "."

def language_for(rel: str) -> str:
    """Return the language label for a relative path, by extension.

    Known extensions map to ``python``, ``javascript``,
    ``typescript``, ``markdown``, ``go``, ``rust``, or ``java``;
    anything else is ``"other"`` (parser-lite handling).
    """
    ext = Path(rel).suffix.lower()
    return {".py": "python", ".js": "javascript", ".mjs": "javascript",
            ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
            ".md": "markdown", ".go": "go", ".rs": "rust", ".java": "java",
            }.get(ext, "other")

def _gitignore_matchers(root: Path):
    pats = []
    gi = root / ".gitignore"
    if gi.is_file():
        for line in gi.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("!"):
                pats.append(line.strip("/"))
    return pats

def scan_project(root) -> dict[str, FileInfo]:
    """Scan a project tree and return ``{relative_path: FileInfo}``.

    Only recognised text extensions are included. Built-in ignore
    names (``.git``, ``__pycache__``, ``node_modules``, and similar)
    plus simple ``.gitignore`` entries are skipped, and files that
    are not valid UTF-8 are skipped. A second pass fills in symbols
    and imports once the full file set is known.
    """
    root = Path(root)
    ignored_names = set(DEFAULT_IGNORES) | set(_gitignore_matchers(root))
    files: dict[str, FileInfo] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in TEXT_EXTS:
            continue
        rel = p.relative_to(root).as_posix()
        if any(part in ignored_names for part in Path(rel).parts):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue
        files[rel] = FileInfo(rel=rel, text=text, language=language_for(rel))
    # second pass: symbols / imports need the full file set
    for fi in files.values():
        if fi.language == "python":
            _parse_python(fi, files)
        else:
            _parse_lite(fi, files)
    return files

def _module_to_path(module: str, files) -> str | None:
    cand = module.replace(".", "/") + ".py"
    if cand in files:
        return cand
    cand2 = module.replace(".", "/") + "/__init__.py"
    return cand2 if cand2 in files else None

def _parse_python(fi: FileInfo, files):
    try:
        tree = ast.parse(fi.text)
    except SyntaxError:
        fi.symbols, fi.imports = [], []
        return
    pkg_parts = Path(fi.rel).parts[:-1]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            fi.symbols.append(node.name)
        elif isinstance(node, ast.Name):
            fi.references.add(node.id)
        elif isinstance(node, ast.Attribute):
            pass
        elif isinstance(node, ast.Import):
            for a in node.names:
                tgt = _module_to_path(a.name, files)
                (fi.imports.append(tgt) if tgt else fi.external_imports.append(a.name))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level and node.level > 0:
                base = list(pkg_parts[: len(pkg_parts) - node.level + 1]) if node.level <= len(pkg_parts) else []
                mod = ".".join(base + ([mod] if mod else []))
            tgt = _module_to_path(mod, files) if mod else None
            if tgt:
                fi.imports.append(tgt)
            elif mod:
                fi.external_imports.append(mod)
            for a in node.names:
                fi.references.add(a.name)
    fi.imports = sorted(set(fi.imports))

_LITE_IMPORT = re.compile(r"""(?:import\s+.*?from\s+|require\(|import\s+)\s*['"]([^'"]+)['"]""")
_LITE_DEF = re.compile(r"^(?:export\s+)?(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)

def _parse_lite(fi: FileInfo, files):
    fi.symbols = _LITE_DEF.findall(fi.text)
    for spec in _LITE_IMPORT.findall(fi.text):
        if not spec.startswith("."):
            fi.external_imports.append(spec); continue
        base = (Path(fi.rel).parent / spec).as_posix()
        for cand in (base, base + ".ts", base + ".js", base + ".mjs", base + "/index.ts", base + "/index.js"):
            cand = cand.replace("./", "", 1) if cand.startswith("./") else cand
            # normalise ../ segments
            parts = []
            ok = True
            for seg in cand.split("/"):
                if seg == "..":
                    if parts: parts.pop()
                    else: ok = False
                elif seg not in ("", "."):
                    parts.append(seg)
            norm = "/".join(parts)
            if ok and norm in files:
                fi.imports.append(norm); break
    fi.imports = sorted(set(fi.imports))

def build_graph(files: dict[str, FileInfo]) -> dict[str, list[str]]:
    """rel -> sorted list of rel paths it imports (project-internal)."""
    return {rel: list(fi.imports) for rel, fi in files.items()}

def strongly_connected_components(graph: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan SCC. Deterministic (sorted iteration)."""
    index_counter = [0]; stack = []; low = {}; idx = {}; on_stack = set(); result = []
    import sys; sys.setrecursionlimit(10000)
    def strongconnect(v):
        idx[v] = low[v] = index_counter[0]; index_counter[0] += 1
        stack.append(v); on_stack.add(v)
        for w in sorted(graph.get(v, [])):
            if w not in graph: continue
            if w not in idx:
                strongconnect(w); low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], idx[w])
        if low[v] == idx[v]:
            comp = []
            while True:
                w = stack.pop(); on_stack.discard(w); comp.append(w)
                if w == v: break
            result.append(sorted(comp))
    for v in sorted(graph):
        if v not in idx: strongconnect(v)
    return result

def find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """Return one cycle as a node list (last repeats first), or None."""
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}; parent = {}
    def dfs(u):
        color[u] = GREY
        for v in graph.get(u, []):
            if v not in color: continue
            if color[v] == GREY:
                cyc = [v]; cur = u
                while cur != v and cur in parent:
                    cyc.append(cur); cur = parent[cur]
                cyc.append(v); return list(reversed(cyc))
            if color[v] == WHITE:
                parent[v] = u
                r = dfs(v)
                if r: return r
        color[u] = BLACK; return None
    import sys; sys.setrecursionlimit(10000)
    for n in sorted(graph):
        if color[n] == WHITE:
            r = dfs(n)
            if r: return r
    return None
