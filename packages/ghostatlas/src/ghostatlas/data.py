"""Data assembly over GhostSlice results.

One run produces one ``AtlasData``: every surface (map, reading
order, brief, HTML) renders from this single object, stamped once,
so numbers can never disagree between the HTML and ATLAS.md.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import engine
from .config import is_hidden, load_atlas_config

READ_MIN_PER_1K_TOKENS = 0.5  # documented reading estimate used everywhere

_MANIFEST_NAMES = ("package.json", "pyproject.toml", "Cargo.toml",
                   "go.mod", "requirements.txt", "setup.py", "Gemfile")
_CONFIG_EXTS = {".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".xml", ".env"}
_LICENSE_NAMES = {"license", "license.md", "license.txt", "licence",
                  "licence.md", "copying", "copying.md", "notice"}


def _read(path) -> str:
    """Read a file as UTF-8 text, replacing undecodable bytes.

    Returns an empty string when the file cannot be read, so one
    unreadable file never aborts a whole run.
    """
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def docstring_first_line(text: str, language: str) -> str:
    """Extractive only: the module docstring's first non-empty line
    (Python), a leading block comment's first line (JS/TS family), or
    a Markdown file's first heading. '' when there is none - callers
    must say so rather than invent a description."""
    if not text:
        return ""
    if language == "python":
        try:
            tree = ast.parse(text)
            doc = ast.get_docstring(tree) or ""
        except Exception:
            doc = ""
        for ln in doc.splitlines():
            if ln.strip():
                return ln.strip()
        return ""
    if language == "markdown":
        for ln in text.splitlines():
            if ln.startswith("#"):
                return ln.lstrip("#").strip()
        return ""
    if language in ("typescript", "javascript", "go", "rust", "java", "csharp", "c", "cpp"):
        stripped = text.lstrip()
        if stripped.startswith("/*"):
            body = stripped[2:].split("*/", 1)[0]
            for ln in body.splitlines():
                ln = ln.strip().lstrip("*").strip()
                if ln:
                    return ln
        elif stripped.startswith("//"):
            return stripped.splitlines()[0].lstrip("/").strip()
    return ""


def top_symbols(text: str, language: str, limit: int = 8) -> list:
    """Top-level symbol names, extracted. Python via ast, other code
    via a conservative definition-line regex. Names only, no prose."""
    out = []
    if language == "python":
        try:
            tree = ast.parse(text)
        except Exception:
            return out
        for node in getattr(tree, "body", []):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.append(node.name)
            if len(out) >= limit:
                break
        return out
    pat = re.compile(
        r"^(?:export\s+)?(?:default\s+)?(function|class|interface|const|def|func|fn)\s+"
        r"([A-Za-z_$][\w$]*)", re.M)
    for m in pat.finditer(text or ""):
        out.append(m.group(2))
        if len(out) >= limit:
            break
    return out


def _git(args, root: Path):
    """Run ``git -C <root> <args>`` and return stdout, or ``None``.

    ``None`` covers git being absent, timing out, or exiting
    non-zero; callers treat all three as "no git history available"
    and label the result that way.
    """
    try:
        r = subprocess.run(["git", "-C", str(root)] + args,
                           capture_output=True, text=True, timeout=30)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def git_activity(root: Path, window_commits: int = 200) -> dict:
    """Change activity from the local git log. Window is labelled:
    the most recent ``window_commits`` commits (or all, if fewer)."""
    out = {"available": False, "window": f"last {window_commits} commits",
           "commits_considered": 0, "per_file": {}, "first_date": None,
           "last_date": None, "total_commits": 0}
    if not (root / ".git").exists():
        return out
    log = _git(["log", "--name-only", "--pretty=format:%H",
                f"-n{window_commits}"], root)
    if log is None:
        return out
    counts = Counter()
    commits = 0
    for ln in log.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if re.fullmatch(r"[0-9a-f]{7,40}", ln):
            commits += 1
        else:
            counts[ln] += 1
    dates = _git(["log", "--pretty=format:%ad", "--date=short"], root)
    if dates:
        ds = [d for d in dates.splitlines() if d.strip()]
        if ds:
            out["total_commits"] = len(ds)
            out["last_date"] = ds[0]
            out["first_date"] = ds[-1]
    out.update({"available": True, "commits_considered": commits,
                "per_file": dict(counts)})
    return out


def dependency_surface(root: Path, files) -> list:
    """Dependency names declared in manifests. Names only - manifest
    dependency lists are the manifest's public interface."""
    deps = set()
    by_path = {f.path: f for f in files}
    pkg = by_path.get("package.json")
    if pkg:
        try:
            data = json.loads(_read(pkg.abspath))
            for key in ("dependencies", "devDependencies", "peerDependencies"):
                deps.update((data.get(key) or {}).keys())
        except ValueError:
            pass
    req = by_path.get("requirements.txt")
    if req:
        for ln in _read(req.abspath).splitlines():
            ln = ln.strip()
            # Option lines (-r includes, --extra-index-url, ...) and
            # direct URL/VCS references declare no package name for
            # this names-only surface; both used to leak in as bogus
            # "dependencies" ("-r", "--extra-index-url", a raw URL).
            if ln and not ln.startswith("#") and not ln.startswith("-") \
                    and "://" not in ln:
                name = re.split(r"[<>=!~\[; ]", ln, 1)[0].strip()
                if name and not name.startswith(
                        ("git+", "hg+", "svn+", "bzr+")):
                    deps.add(name)
    pyproj = by_path.get("pyproject.toml")
    if pyproj:
        text = _read(pyproj.abspath)
        m = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.S)
        if m:
            for item in re.findall(r'"([^"]+)"|\'([^\']+)\'', m.group(1)):
                name = re.split(r"[<>=!~\[; ]", (item[0] or item[1]), 1)[0].strip()
                if name:
                    deps.add(name)
    cargo = by_path.get("Cargo.toml")
    if cargo:
        in_deps = False
        for ln in _read(cargo.abspath).splitlines():
            s = ln.strip()
            if s.startswith("["):
                in_deps = s in ("[dependencies]", "[dev-dependencies]")
                continue
            if in_deps and "=" in s:
                deps.add(s.split("=", 1)[0].strip().strip('"'))
    gomod = by_path.get("go.mod")
    if gomod:
        in_require_block = False
        for ln in _read(gomod.abspath).splitlines():
            s = ln.strip()
            if s == "require (":
                in_require_block = True
                continue
            if in_require_block:
                if s == ")":
                    in_require_block = False
                elif s and not s.startswith("//"):
                    # The common multi-line form: one module per line
                    # inside require ( ... ). It used to be missed
                    # entirely; only single-line requires were read.
                    deps.add(s.split()[0])
                continue
            if s.startswith("require "):
                rest = s[len("require "):].strip("() ")
                if rest:
                    deps.add(rest.split()[0])
    return sorted(deps)


CODE_LANGUAGES = {
    "python", "typescript", "javascript", "go", "rust", "java", "csharp",
    "php", "ruby", "kotlin", "swift", "c", "cpp",
}

_TEST_DIR_SEGMENTS = {"test", "tests", "__tests__", "spec", "specs"}


def _stem_of(path: str) -> str:
    name = PurePosixPath(path).name
    return name.rsplit(".", 1)[0] if "." in name else name


def _test_target_stem(path: str) -> str | None:
    """The source stem a test file's name points at, by convention:
    ``test_engine.py`` / ``engine_test.py`` / ``engine.test.ts`` /
    ``engine.spec.ts`` all point at stem ``engine``. None when the
    file name carries no such convention."""
    name = PurePosixPath(path).name
    for marker in (".test.", ".spec."):
        if marker in name:
            return name.split(marker, 1)[0] or None
    stem = _stem_of(path)
    if stem.startswith("test_"):
        return stem[len("test_"):] or None
    if stem.endswith("_test"):
        return stem[: -len("_test")] or None
    return None


def test_linkage(files, graph) -> dict:
    """Static test linkage ("covering shape") for every code source
    file. Facts only, from the same run's import graph and file
    names; tests are never executed, so this is NOT measured
    coverage and surfaces must label it as such.

    A source file is:

    - ``direct``: a test file imports it (an edge in ``graph``), or
      a test file's name follows the test naming convention for it;
    - ``indirect``: reachable from a directly linked file through
      the import graph (shortest path, cycle-safe);
    - ``unlinked``: neither of the above.

    Test files, generated files, vendored files, and non-code files
    (docs, config, data) are never counted as sources.
    """
    sources = [f for f in files
               if not f.get("is_test") and not f.get("is_vendored")
               and not f.get("is_generated")
               and f.get("language") in CODE_LANGUAGES]
    source_paths = {f["path"] for f in sources}
    test_files = sorted(f["path"] for f in files if f.get("is_test"))

    direct_tests: dict[str, list] = defaultdict(list)
    for test_path in test_files:
        for dst in (graph.get(test_path) or {}).get("imports", []):
            if dst in source_paths:
                direct_tests[dst].append(test_path)
    by_stem: dict[str, list] = defaultdict(list)
    for f in sources:
        by_stem[_stem_of(f["path"])].append(f["path"])
    for test_path in test_files:
        stem = _test_target_stem(test_path)
        if not stem:
            continue
        matches = by_stem.get(stem, [])
        chosen = []
        if len(matches) == 1:
            chosen = matches
        elif len(matches) > 1:
            parent = PurePosixPath(test_path).parent
            mirror = PurePosixPath(
                *[p for p in parent.parts if p not in _TEST_DIR_SEGMENTS])
            chosen = [m for m in matches
                      if PurePosixPath(m).parent in (parent, mirror)]
        for m in chosen:
            if test_path not in direct_tests[m]:
                direct_tests[m].append(test_path)

    # Indirect: breadth-first from the directly linked files over the
    # import graph, sources only, shortest distance first.
    indirect: dict[str, dict] = {}
    queue = sorted(direct_tests)
    seen = set(queue)
    frontier = [(p, p, 0) for p in queue]  # (node, direct root, dist)
    while frontier:
        nxt = []
        for node, root, dist in frontier:
            for dst in sorted((graph.get(node) or {}).get("imports", [])):
                if dst in source_paths and dst not in seen:
                    seen.add(dst)
                    indirect[dst] = {"via": node, "direct_source": root,
                                     "distance": dist + 1}
                    nxt.append((dst, root, dist + 1))
        frontier = nxt

    rank = {"direct": 0, "indirect": 1, "unlinked": 2}
    out = []
    for f in sources:
        path = f["path"]
        if path in direct_tests:
            status, extra = "direct", {"test_files": sorted(direct_tests[path]),
                                       "via": None, "direct_source": None,
                                       "distance": 0}
        elif path in indirect:
            status = "indirect"
            extra = {"test_files": [], "via": indirect[path]["via"],
                     "direct_source": indirect[path]["direct_source"],
                     "distance": indirect[path]["distance"]}
        else:
            status, extra = "unlinked", {"test_files": [], "via": None,
                                         "direct_source": None, "distance": 0}
        out.append({"path": path, "status": status,
                    "tokens": f.get("tokens", 0),
                    "importer_count": f.get("importer_count", 0), **extra})
    out.sort(key=lambda s: (rank[s["status"]], -s["importer_count"],
                            -s["tokens"], s["path"]))
    summary = {
        "source_files": len(out),
        "direct": sum(1 for s in out if s["status"] == "direct"),
        "indirect": sum(1 for s in out if s["status"] == "indirect"),
        "unlinked": sum(1 for s in out if s["status"] == "unlinked"),
        "test_files": len(test_files),
    }
    return {"summary": summary, "sources": out, "test_files": test_files,
            "method": ("static linkage only: direct means a test file "
                       "imports the source or follows its test naming "
                       "convention; indirect means reachable from a "
                       "directly linked file through the import graph; "
                       "tests were not executed, so this is not "
                       "measured coverage")}


@dataclass
class AtlasData:
    """Everything one Atlas run knows about a project.

    A single instance feeds every surface (HTML map, ``ATLAS.md``
    brief, JSON), so numbers can never disagree between artifacts.
    File entries are plain dicts in scan order; each is enriched
    during assembly with ``doc`` (extracted docstring first line, or
    ``""``), ``symbols``, ``importer_count``, and ``package``.

    ``engine`` is ``"ghostslice"`` when GhostSlice produced the
    scan/graph numbers, or ``"fallback"`` when the labelled fallback
    engine in :mod:`ghostatlas.engine` did. Token counts are
    GhostSlice estimator *estimates*, never exact tokenizer counts.
    """

    root: str
    title: str
    run_stamp: str
    engine: str
    audience: str = "onboarding"
    generated_at: str = ""
    config: dict = field(default_factory=dict)
    files: list = field(default_factory=list)          # dicts, scan order
    packages: list = field(default_factory=list)       # {path, files, tokens, size}
    graph: dict = field(default_factory=dict)          # path -> {imports, external}
    importers: dict = field(default_factory=dict)      # path -> [importer paths]
    entries: list = field(default_factory=list)        # entry candidates w/ evidence
    call_chains: list = field(default_factory=list)    # sampled chains (python)
    call_counts: dict = field(default_factory=dict)
    duplicates: dict = field(default_factory=dict)     # {exact: [], near: []}
    dead_candidates: list = field(default_factory=list)
    git: dict = field(default_factory=dict)
    secrets_summary: dict = field(default_factory=dict)  # counts/types only
    lint_findings: list = field(default_factory=list)
    dependencies: list = field(default_factory=list)
    licenses: list = field(default_factory=list)
    test_coverage: dict = field(default_factory=dict)  # static linkage, see test_linkage
    total_tokens: int = 0
    total_size: int = 0

    def by_path(self):
        """Return the file dicts indexed by their project-relative path."""
        return {f["path"]: f for f in self.files}

    def to_dict(self):
        """Return a JSON-serialisable view of the run.

        This is what ``ghostatlas scan`` prints, what ``--json-out``
        writes, and what the HTML map embeds. Internal-only fields
        (per-file importers, call counts, config) are not included.
        """
        return {
            "root": self.root, "title": self.title,
            "run_stamp": self.run_stamp, "engine": self.engine,
            "audience": self.audience, "generated_at": self.generated_at,
            "files": self.files, "packages": self.packages,
            "graph": self.graph, "entries": self.entries,
            "call_chains": self.call_chains,
            "duplicates": self.duplicates,
            "dead_candidates": self.dead_candidates, "git": self.git,
            "secrets_summary": self.secrets_summary,
            "lint_findings": self.lint_findings,
            "dependencies": self.dependencies, "licenses": self.licenses,
            "test_coverage": self.test_coverage,
            "total_tokens": self.total_tokens, "total_size": self.total_size,
        }


def _sample_call_chains(gs, scan_obj, graph) -> tuple[list, dict]:
    """Top call chains from GhostSlice's Python call graph, capped.
    Returns ([{chain: 'a -> b -> c', sites}], counts). Sampled from
    static analysis - callers must label them as such."""
    chains, counts = [], {}
    if gs is None:
        return chains, counts
    try:
        from ghostslice.callgraph import build_call_graph
        payload = build_call_graph(scan_obj, graph=graph)
    except Exception:
        return chains, counts
    counts = payload.get("counts", {}) or {}
    adj: dict[str, list] = defaultdict(list)
    sites: dict[tuple, int] = {}
    for e in payload.get("edges", []):
        if e.get("kind") == "reference":
            continue
        adj[e["caller"]].append(e["callee"])
        sites[(e["caller"], e["callee"])] = e.get("sites", 1)
    starts = sorted(adj, key=lambda s: -sum(sites.get((s, t), 1) for t in adj[s]))
    seen = set()
    for start in starts[:40]:
        chain, cur, visited = [start], start, {start}
        while adj.get(cur) and len(chain) < 5:
            nxts = [t for t in adj[cur] if t not in visited]
            if not nxts:
                break
            cur = max(nxts, key=lambda t: sites.get((chain[-1], t), 1))
            chain.append(cur)
            visited.add(cur)
        if len(chain) >= 3:
            key = " -> ".join(chain)
            if key not in seen:
                seen.add(key)
                chains.append({"chain": key,
                               "length": len(chain),
                               "symbols": list(chain)})
        if len(chains) >= 10:
            break
    return chains, counts


def build_atlas_data(root: str | Path, audience: str = "onboarding") -> AtlasData:
    """Assemble the :class:`AtlasData` for the project at ``root``.

    Steps: load and validate the project's atlas config, scan and
    graph the project (via GhostSlice when importable, otherwise
    the labelled fallback engine), drop any config-hidden paths
    from every surface, then enrich each file with its extracted
    docstring first line, top symbols, and importer count.

    Args:
        root: Path to the project directory. Read only; the project
            is never modified.
        audience: ``"onboarding"`` (default) or ``"diligence"``.
            Recorded on the result; it changes brief ordering, not
            the underlying data.

    Raises:
        ValueError: If ``root`` is not a directory, or if the
            project's ``.ghostslice.json`` atlas section is malformed
            or contains an unknown key. The CLI maps this to exit 2.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    cfg = load_atlas_config(root)
    gs = engine.load_ghostslice()
    eng = "ghostslice" if gs is not None else "fallback"

    scan_obj = None
    files: list = []
    packages: list = []
    graph: dict = {}
    entries: list = []
    duplicates: dict = {"exact": [], "near": []}
    secret_findings: list = []
    secrets_summary: dict = {"count": 0, "by_type": {}, "by_file": {}}
    lint_findings: list = []
    call_chains: list = []
    call_counts: dict = {}
    dead: list = []

    if gs is not None:
        from ghostslice.scanner import scan as gs_scan
        from ghostslice.graph import build_graph, importers_of, recommendations
        from ghostslice.entries import find_entry_candidates
        scan_obj = gs_scan(root)
        for f in scan_obj.files:
            d = f.to_dict() if hasattr(f, "to_dict") else dict(f.__dict__)
            d.pop("abspath", None)
            files.append(d)
        try:
            from ghostslice.workspaces import summarize_packages
            packages = summarize_packages(scan_obj)
        except Exception:
            packages = []
        graph = build_graph(scan_obj)
        entries = find_entry_candidates(scan_obj, graph)
        try:
            from ghostslice.duplicates import find_duplicates
            duplicates = find_duplicates(scan_obj)
        except Exception:
            pass
        try:
            from ghostslice.secrets_scan import scan_scan_result
            findings = scan_scan_result(scan_obj)
            secret_findings = findings
            by_type = Counter(x.get("type", "unknown") for x in findings)
            by_file = Counter(x.get("path", "") for x in findings)
            secrets_summary = {"count": len(findings),
                               "by_type": dict(sorted(by_type.items())),
                               "by_file": dict(sorted(by_file.items()))}
        except Exception:
            pass
        try:
            from ghostslice.lint import lint_project
            payload = lint_project(root, scan_result=scan_obj, graph=graph)
            lint_findings = payload.get("findings", []) or []
        except Exception:
            lint_findings = []
        try:
            recs = recommendations(scan_obj, graph)
            dead = [{"path": r.get("path"), "reason": r.get("reason", ""),
                     "tokens": r.get("tokens", 0)} for r in recs]
        except Exception:
            dead = []
        call_chains, call_counts = _sample_call_chains(gs, scan_obj, graph)
    else:
        scan_obj = engine.fallback_scan(root)
        files = [f.to_dict() for f in scan_obj.files]
        for f in files:
            f.pop("abspath", None)
        packages = scan_obj.packages
        graph = engine.fallback_graph(scan_obj)
        entries = engine.fallback_entries(scan_obj, graph)

    # hidden paths from the atlas config are removed from every surface
    removed: set = set()
    if cfg["hidden_paths"]:
        keep = [f for f in files if not is_hidden(f["path"], cfg["hidden_paths"])]
        removed = {f["path"] for f in files} - {f["path"] for f in keep}
        files = keep
        graph = {k: {"imports": [i for i in v.get("imports", []) if i not in removed],
                     "external": v.get("external", [])}
                 for k, v in graph.items() if k not in removed}
        entries = [e for e in entries if e["path"] not in removed]
        dead = [d for d in dead if d.get("path") not in removed]
        # The surfaces below used to leak hidden paths (and, for
        # packages, stale pre-filter counts that disagreed with the
        # filtered totals - a consistency-bar violation):
        def _visible(group):
            g = dict(group)
            g["files"] = [p for p in group.get("files", []) if p not in removed]
            return g

        exact = []
        for group in duplicates.get("exact", []) or []:
            g = _visible(group)
            if len(g["files"]) >= 2:
                if "tokens_each" in g and "potential_savings" in g:
                    g["potential_savings"] = g["tokens_each"] * (len(g["files"]) - 1)
                exact.append(g)
        near = []
        for pair in duplicates.get("near", []) or []:
            pair_files = pair.get("files") or [pair.get("a"), pair.get("b")]
            if pair_files and all(p not in removed for p in pair_files if p):
                near.append(pair)
        duplicates = {"exact": exact, "near": near}
        lint_findings = [f for f in lint_findings
                         if f.get("path") not in removed
                         and not any(rp in json.dumps(f, default=str)
                                     for rp in removed)]
        # A dead candidate's reason text can likewise name a hidden
        # file (e.g. "duplicate of <hidden path>").
        dead = [d for d in dead
                if not any(rp in (d.get("reason") or "") for rp in removed)]
        if secret_findings:
            kept_findings = [x for x in secret_findings
                             if x.get("path", "") not in removed]
            by_type = Counter(x.get("type", "unknown") for x in kept_findings)
            by_file = Counter(x.get("path", "") for x in kept_findings)
            secrets_summary = {"count": len(kept_findings),
                               "by_type": dict(sorted(by_type.items())),
                               "by_file": dict(sorted(by_file.items()))}
        call_chains = [
            c for c in call_chains
            if not any(s.rsplit(":", 1)[0] in removed
                       for s in c.get("symbols", []))]
        if packages:
            agg: dict = {}
            for f in files:
                key = f.get("package") or (
                    f["path"].rsplit("/", 1)[0] if "/" in f["path"] else "")
                a = agg.setdefault(key, {"files": 0, "tokens": 0})
                a["files"] += 1
                a["tokens"] += f.get("tokens", 0)
            pkg_total = sum(a["tokens"] for a in agg.values())
            new_packages = []
            for p in packages:
                a = agg.get(p.get("path"))
                if not a:
                    continue
                p2 = dict(p)
                p2["files"] = a["files"]
                p2["tokens"] = a["tokens"]
                if "share" in p2:
                    p2["share"] = (round(100.0 * a["tokens"] / pkg_total, 2)
                                   if pkg_total else 0.0)
                new_packages.append(p2)
            packages = new_packages

    # per-file enrichment: docstring first line, top symbols, importers
    importers: dict[str, list] = defaultdict(list)
    for src, data in graph.items():
        for dst in data.get("imports", []):
            importers[dst].append(src)
    root_by_rel = {}
    if gs is not None and scan_obj is not None:
        root_by_rel = {f.path: f.abspath for f in scan_obj.files}
    elif scan_obj is not None and hasattr(scan_obj, "files"):
        root_by_rel = {f.path: f.abspath for f in scan_obj.files}
    for f in files:
        ap = root_by_rel.get(f["path"], str(root / f["path"]))
        text = _read(ap)
        f["doc"] = docstring_first_line(text, f.get("language", ""))
        f["symbols"] = top_symbols(text, f.get("language", ""))
        f["importer_count"] = len(importers.get(f["path"], []))
        f["package"] = f.get("package") or (
            f["path"].rsplit("/", 1)[0] if "/" in f["path"] else "")

    # Static test linkage over the (hidden-path filtered) graph and
    # file set, so hidden files never appear here either.
    test_cov = test_linkage(files, graph)

    if not packages:
        agg: dict[str, dict] = {}
        for f in files:
            p = agg.setdefault(f["package"], {"path": f["package"], "files": 0,
                                              "tokens": 0, "size": 0})
            p["files"] += 1
            p["tokens"] += f.get("tokens", 0)
            p["size"] += f.get("size", 0)
        packages = sorted(agg.values(), key=lambda p: (-p["tokens"], p["path"]))

    file_objs = [type("F", (), {"path": f["path"], "abspath": root_by_rel.get(f["path"], str(root / f["path"]))})() for f in files]
    licenses = sorted(
        f["path"] for f in files
        if PurePosixPath(f["path"]).name.lower() in _LICENSE_NAMES)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = AtlasData(
        root=str(root),
        title=cfg["title"] or root.name,
        run_stamp=stamp,
        generated_at=stamp,
        engine=eng,
        audience=audience,
        config=cfg,
        files=files,
        packages=packages,
        graph=graph,
        importers={k: sorted(v) for k, v in importers.items()},
        entries=entries,
        call_chains=call_chains,
        call_counts=call_counts,
        duplicates=duplicates,
        dead_candidates=dead,
        git=git_activity(root),
        secrets_summary=secrets_summary,
        lint_findings=lint_findings,
        dependencies=dependency_surface(root, file_objs),
        licenses=licenses,
        test_coverage=test_cov,
        total_tokens=sum(f.get("tokens", 0) for f in files),
        total_size=sum(f.get("size", 0) for f in files),
    )
    if removed:
        per_file = data.git.get("per_file") or {}
        data.git = {**data.git, "per_file": {
            k: v for k, v in per_file.items()
            if k not in removed and not is_hidden(k, cfg["hidden_paths"])}}
    return data
