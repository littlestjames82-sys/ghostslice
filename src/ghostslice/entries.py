"""Entry-point candidate discovery (v0.15, for `ghostslice init`).

graph.find_entry_points answers a yes/no question for the prune
engine: it returns the profile's entry points, or every file whose
basename is in a fixed heuristic set. The init wizard needs something
richer: CANDIDATES, ranked, each carrying the evidence that nominated
it, so the generated profile can print *why* a file is listed.

Signals (points are documented weights, not probabilities):

  +60  a package manifest names the file as a command: an npm
       package.json "bin" entry, or a pyproject [project.scripts] /
       [project.gui-scripts] entry resolving to this module.
  +50  package.json "main" names the file (the package's entry
       module — a library entry rather than a command, hence less
       than "bin").
  +40  basename is in graph.ENTRY_BASENAMES (main / cli / app /
       server / index / __main__ / handler ...) — the same heuristic
       set the prune engine uses, so init and recommendations agree
       on what "looks like an entry point" means.
  +35  a Python file with an `if __name__ == "__main__":` guard.
  +25  the file starts with a shebang line (an executable script).
  +10  nothing in the project imports it (from the import graph) —
       applied ONLY to files that already carry a signal above; an
       unimported library file is not an entry point on that fact
       alone, so this is a tie-breaker, never a nomination.

Hard exclusions (a false entry point in a generated profile is worse
than a missing one: fit.py protects entry points from downgrades):

  - test files (scanner.is_test): a test module with a __main__
    guard is a test runner, not the project's entry point;
  - files detect.py flags as vendored or generated: a vendored
    package's own main is not *this* project's entry point.

Manifest parsing is stdlib-only and defensive: package.json via
json; pyproject.toml via tomllib where available (3.11+) with a
section-scoped regex fallback for 3.10. Only root manifests are
read for npm (plus each workspace package's own package.json —
its "bin"/"main" name files inside that package), and the root
pyproject.toml for scripts. Manifest *contents* never appear in
signal strings — only the manifest field and the command name, both
of which are the manifest's public interface.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path, PurePosixPath

from .graph import ENTRY_BASENAMES, build_graph, importers_of

SCORE_BIN = 60
SCORE_SCRIPTS = 60
SCORE_MAIN = 50
SCORE_NAME = 40
SCORE_MAIN_GUARD = 35
SCORE_SHEBANG = 25
SCORE_NO_IMPORTERS = 10

_MAIN_GUARD_RE = re.compile(r"""if\s+__name__\s*==\s*['"]__main__['"]""")
_CODE_FOR_SHEBANG = {
    "python", "typescript", "javascript", "ruby", "shell", "powershell",
    "php", "perl", "go", "rust",
}


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _norm_rel(p: str) -> str:
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def _npm_signals(root: Path, scan_paths: set[str]) -> dict[str, list[tuple[int, str]]]:
    """{relpath: [(score, signal)]} from package.json bin/main fields.

    Reads the root package.json and — for workspace layouts — each
    scanned package.json one or two levels down (their bin/main name
    files inside their own directory)."""
    out: dict[str, list[tuple[int, str]]] = {}

    def add(rel: str, score: int, signal: str) -> None:
        if rel in scan_paths:
            out.setdefault(rel, []).append((score, signal))

    manifests = [root / "package.json"]
    manifests += sorted(root.glob("*/package.json"))
    manifests += sorted(root.glob("*/*/package.json"))
    for manifest in manifests:
        text = _read_text(manifest)
        if text is None:
            continue
        try:
            data = json.loads(text)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        base = manifest.parent.relative_to(root).as_posix()
        base = "" if base == "." else base + "/"
        bin_field = data.get("bin")
        if isinstance(bin_field, str):
            name = data.get("name") or "the package"
            add(base + _norm_rel(bin_field), SCORE_BIN,
                f'package.json "bin" names it as the {name!r} command')
        elif isinstance(bin_field, dict):
            for cmd, target in bin_field.items():
                if isinstance(target, str):
                    add(base + _norm_rel(target), SCORE_BIN,
                        f'package.json "bin" maps {cmd!r} to this file')
        main_field = data.get("main")
        if isinstance(main_field, str) and main_field:
            add(base + _norm_rel(main_field), SCORE_MAIN,
                'package.json "main" names this file')
    return out


def _pyproject_scripts(root: Path) -> dict[str, str]:
    """{command: "module:attr"} from [project.scripts]/[gui-scripts].

    tomllib when available; a section-scoped line parser otherwise
    (3.10). The fallback understands the common one-entry-per-line
    shape only — exotic TOML (inline tables spanning lines, dotted
    keys) yields fewer scripts, never wrong ones: every candidate
    module is existence-checked against the scan before it scores."""
    text = _read_text(root / "pyproject.toml")
    if text is None:
        return {}
    try:
        import tomllib
    except ImportError:  # Python 3.10
        tomllib = None
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except Exception:
            return {}
        project = data.get("project") or {}
        out: dict[str, str] = {}
        for section in ("scripts", "gui-scripts"):
            entries = project.get(section) or {}
            if isinstance(entries, dict):
                for cmd, target in entries.items():
                    if isinstance(target, str):
                        out[cmd] = target
        return out
    out = {}
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            section = line.strip("[]").strip()
            continue
        if section in ("project.scripts", "project.gui-scripts"):
            m = re.match(r"""^["']?([\w.-]+)["']?\s*=\s*["']([^"']+)["']""", line)
            if m:
                out[m.group(1)] = m.group(2)
    return out


def _scripts_signals(root: Path, scan_paths: set[str]) -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    for cmd, target in _pyproject_scripts(root).items():
        module = target.split(":", 1)[0].strip()
        if not module:
            continue
        base = module.replace(".", "/")
        for cand in (f"{base}.py", f"{base}/__init__.py",
                     f"src/{base}.py", f"src/{base}/__init__.py"):
            if cand in scan_paths:
                out.setdefault(cand, []).append((
                    SCORE_SCRIPTS,
                    f"[project.scripts] maps {cmd!r} to this module"))
                break
    return out


def _head_and_text(entry) -> tuple[str, str]:
    """(first line, full text) of a scanned file, "" on read error.

    Only Python files get their full text read (the __main__-guard
    check needs it); every other language pays for one line — the
    shebang check (audit G10 F5)."""
    try:
        with open(entry.abspath, "rb") as fh:
            first = fh.readline().decode("utf-8", errors="replace").rstrip("\r\n")
            if entry.language == "python":
                rest = fh.read().decode("utf-8", errors="replace")
                return first, first + "\n" + rest if rest else first
    except OSError:
        return "", ""
    return first, ""


def _is_main_compare(test) -> bool:
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 \
            or not isinstance(test.ops[0], ast.Eq):
        return False
    sides = [test.left, *test.comparators]
    has_name = any(isinstance(s, ast.Name) and s.id == "__name__" for s in sides)
    has_const = any(isinstance(s, ast.Constant) and s.value == "__main__"
                    for s in sides)
    return has_name and has_const


def _main_guard(text: str) -> bool:
    """True for a module-level `if __name__ == "__main__":` guard.

    Parsed with ast (the house standard for Python): a guard-shaped
    comment, string, or a guard nested inside a function does NOT
    count. Files that fail to parse fall back to the textual regex —
    a broken file can still be the entry point (audit G10 F1)."""
    if not text:
        return False
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return bool(_MAIN_GUARD_RE.search(text))
    return any(isinstance(node, ast.If) and _is_main_compare(node.test)
               for node in tree.body)


def find_entry_candidates(scan_result, graph=None) -> list[dict]:
    """Ranked entry-point candidates for a scan:
    [{path, score, signals: [str]}] sorted by score desc, then path.
    Only files with at least one nominating signal appear."""
    root = Path(scan_result.root)
    scan_paths = {f.path for f in scan_result.files}
    if graph is None:
        graph = build_graph(scan_result)
    importers = importers_of(graph)

    signals: dict[str, list[tuple[int, str]]] = {}
    for source in (_npm_signals(root, scan_paths),
                   _scripts_signals(root, scan_paths)):
        for rel, hits in source.items():
            signals.setdefault(rel, []).extend(hits)

    for entry in scan_result.files:
        if entry.is_test or entry.is_vendored or entry.is_generated:
            continue
        rel = entry.path
        hits: list[tuple[int, str]] = list(signals.get(rel, []))
        if PurePosixPath(rel).name in ENTRY_BASENAMES:
            hits.append((SCORE_NAME,
                         "name matches the entry-point heuristic "
                         "(main/cli/app/server/index/...)"))
        if entry.language == "python" or entry.language in _CODE_FOR_SHEBANG:
            first, text = _head_and_text(entry)
            if first.startswith("#!"):
                hits.append((SCORE_SHEBANG,
                             f"starts with a shebang ({first.strip()[:40]})"))
            if entry.language == "python" and _main_guard(text):
                hits.append((SCORE_MAIN_GUARD,
                             'has an `if __name__ == "__main__"` guard'))
        if not hits:
            continue
        if not importers.get(rel):
            hits.append((SCORE_NO_IMPORTERS,
                         "nothing in the project imports it"))
        signals[rel] = hits

    by_path = {f.path: f for f in scan_result.files}
    out = []
    for rel, hits in signals.items():
        entry = by_path.get(rel)
        if entry is None or entry.is_test or entry.is_vendored or entry.is_generated:
            continue
        out.append({
            "path": rel,
            "score": sum(score for score, _ in hits),
            "signals": [text for _, text in hits],
        })
    out.sort(key=lambda c: (-c["score"], c["path"]))
    return out
