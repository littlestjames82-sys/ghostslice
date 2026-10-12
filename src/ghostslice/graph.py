"""Import / dependency graph + prune recommendations.

Python imports are parsed with the real stdlib `ast`. TypeScript /
JavaScript imports are parser-lite: regexes for `import ... from`,
side-effect `import '...'`, `export ... from`, `require('...')` and
dynamic `import('...')`. Only imports that resolve to a file inside the
scanned project become graph edges; everything else is recorded as an
external name.

Prune recommendations: a code file is a candidate when it is not
reachable from any entry point (following imports), or, when no entry
points are known, when nothing imports it. Entry points come from the
profile when set, otherwise from a documented name heuristic
(main / index / app / cli / __main__ / server / handler). Tests, docs,
config, and lockfiles are never prune candidates: tests are handled by
strip-tests, docs/config are cheap context an agent may genuinely need.
Every candidate is a *recommendation to review*, not an instruction:
dynamic imports and reflection can make a file look dead when it is not.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path, PurePosixPath

ENTRY_BASENAMES = {
    "main.py", "main.ts", "main.js", "main.mjs", "main.tsx", "__main__.py",
    "index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs",
    "app.py", "app.ts", "app.js", "cli.py", "cli.ts", "cli.js", "cli.mjs",
    "server.py", "server.ts", "server.js", "server.mjs",
    "handler.py", "handler.mjs", "handler.js", "manage.py", "run.py",
    "mod.rs", "main.go", "main.rs", "Program.cs", "Main.java",
}

CODE_LANGS = {"python", "typescript", "javascript", "go", "rust", "java", "csharp"}
CONFIG_SUFFIXES = {".json", ".toml", ".yaml", ".yml", ".cfg", ".ini", ".xml"}

_TS_EXTS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json"]
_IMPORT_FROM_RE = re.compile(r"""(?:import|export)\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]""")
_REQUIRE_RE = re.compile(r"""(?:require|import)\s*\(\s*['"]([^'"]+)['"]\s*\)""")


def _py_imports(source: str, rel: str, root_files: set[str]) -> tuple[list[str], list[str]]:
    edges: list[str] = []
    external: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return edges, external
    current_dir = PurePosixPath(rel).parent  # '.' for root files
    for node in ast.walk(tree):
        module = None
        level = 0
        if isinstance(node, ast.Import):
            for alias in node.names:
                _py_resolve(alias.name, 0, current_dir, root_files, edges, external)
            continue
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level or 0
            _py_resolve(module, level, current_dir, root_files, edges, external)
            # `from .pkg import name` may also pull pkg/name.py
            if module is not None:
                base = _py_module_base(module, level, current_dir)
                for alias in node.names:
                    cand = f"{base}/{alias.name}.py" if base else f"{alias.name}.py"
                    cand_init = f"{base}/{alias.name}/__init__.py" if base else f"{alias.name}/__init__.py"
                    for c in (cand, cand_init):
                        if c in root_files and c not in edges:
                            edges.append(c)
            continue
    return edges, external


def _py_module_base(module: str, level: int, current_dir: PurePosixPath) -> str:
    parts: list[str] = []
    if level:
        base_parts = [] if str(current_dir) == "." else list(current_dir.parts)
        # level 1 = current package; each extra level goes one up.
        keep = base_parts[: len(base_parts) - (level - 1)] if level - 1 <= len(base_parts) else []
        parts = list(keep)
    if module:
        parts += module.split(".")
    return "/".join(p for p in parts if p and p != ".")


def _py_resolve(module: str, level: int, current_dir, root_files, edges, external):
    if not module and not level:
        return
    base = _py_module_base(module, level, current_dir)
    candidates = [f"{base}.py", f"{base}/__init__.py"] if base else []
    hit = next((c for c in candidates if c in root_files), None)
    if hit:
        if hit not in edges:
            edges.append(hit)
    elif module:
        external.append(module)


def _ts_resolve(spec: str, rel: str, root_files: set[str]) -> str | None:
    if not (spec.startswith("./") or spec.startswith("../") or spec.startswith("/")):
        return None
    cur = PurePosixPath(rel).parent
    target = PurePosixPath(spec.lstrip("/")) if spec.startswith("/") else cur / spec
    # normalise ../ and ./
    parts: list[str] = []
    for part in target.parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    base = "/".join(parts)
    candidates = [base] + [base + ext for ext in _TS_EXTS] + [f"{base}/index{ext}" for ext in _TS_EXTS]
    return next((c for c in candidates if c in root_files), None)


def _ts_imports(source: str, rel: str, root_files: set[str]) -> tuple[list[str], list[str]]:
    edges: list[str] = []
    external: list[str] = []
    specs = _IMPORT_FROM_RE.findall(source) + _REQUIRE_RE.findall(source)
    for spec in specs:
        hit = _ts_resolve(spec, rel, root_files)
        if hit:
            if hit not in edges:
                edges.append(hit)
        elif not spec.startswith("."):
            if spec not in external:
                external.append(spec)
    return edges, external


def build_graph(scan_result) -> dict:
    """Return {path: {"imports": [project paths], "external": [names]}}."""
    root_files = {f.path for f in scan_result.files}
    root = Path(scan_result.root)
    graph: dict[str, dict] = {}
    for entry in scan_result.files:
        edges: list[str] = []
        external: list[str] = []
        if entry.language in ("python", "typescript", "javascript"):
            try:
                source = Path(entry.abspath).read_text(encoding="utf-8", errors="replace")
            except OSError:
                source = ""
            if entry.language == "python":
                edges, external = _py_imports(source, entry.path, root_files)
            else:
                edges, external = _ts_imports(source, entry.path, root_files)
            edges = [e for e in edges if e != entry.path]
        graph[entry.path] = {"imports": edges, "external": external}
    return graph


def importers_of(graph: dict) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = {p: [] for p in graph}
    for src, data in graph.items():
        for dst in data["imports"]:
            rev.setdefault(dst, []).append(src)
    return rev


def find_entry_points(scan_result, profile=None) -> list[str]:
    paths = {f.path for f in scan_result.files}
    configured = [p for p in (profile.entry_points if profile else []) if p in paths]
    if configured:
        return configured
    return sorted(p for p in paths if PurePosixPath(p).name in ENTRY_BASENAMES)


def reachable_from(entries: list[str], graph: dict) -> set[str]:
    seen: set[str] = set()
    stack = list(entries)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(graph.get(cur, {}).get("imports", []))
    return seen


def recommendations(scan_result, graph: dict, profile=None) -> list[dict]:
    entries = find_entry_points(scan_result, profile)
    rev = importers_of(graph)
    reachable = reachable_from(entries, graph) if entries else set()
    by_path = {f.path: f for f in scan_result.files}
    out: list[dict] = []
    for entry in scan_result.files:
        if entry.language not in CODE_LANGS:
            continue
        if entry.is_test or entry.is_lockfile:
            continue
        if PurePosixPath(entry.path).suffix.lower() in CONFIG_SUFFIXES:
            continue
        if entry.path in entries:
            continue
        if entries and entry.path not in reachable:
            reason = "unreachable from entry points"
            detail = f"entry points: {', '.join(entries)}"
        elif not entries and not rev.get(entry.path):
            reason = "no importers (no entry points configured; weaker signal)"
            detail = "nothing in the project imports this file"
        else:
            continue
        out.append({
            "path": entry.path,
            "tokens": entry.tokens,
            "potential_savings": entry.tokens,
            "reason": reason,
            "detail": detail,
            "importers": rev.get(entry.path, []),
        })
    out.sort(key=lambda r: r["tokens"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# git changed files (for --diff task selection)
# ---------------------------------------------------------------------------

def changed_files(root: str | Path) -> list[str]:
    """Files changed in the git working tree vs HEAD, plus untracked files.

    Combines `git status --porcelain` (staged + unstaged + untracked) and
    `git diff --name-only HEAD`. Returns [] when root is not a git repo.
    """
    root = Path(root)
    found: set[str] = set()
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        name = line[3:].strip()
        if " -> " in name:  # renamed: keep the new path
            name = name.split(" -> ", 1)[1]
        name = name.strip('"')
        if name and not name.endswith("/"):
            found.add(name)
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            found.update(n.strip() for n in proc.stdout.splitlines() if n.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return sorted(found)
