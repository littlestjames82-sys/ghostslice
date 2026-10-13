"""Monorepo / workspace detection (v0.13).

From a project root, detect package boundaries so scans, bundles,
the dashboard API and the HTML report can report per-package
subtotals. Detection reads only the root's own manifests plus the
member directories those manifests name; it runs once per scan.

Declared sources (root level only, outermost wins):

  - npm:    root package.json "workspaces" (an array of globs, or
            {"packages": [...]}); "!" entries are negations.
  - pnpm:   pnpm-workspace.yaml "packages:" list (line-parsed,
            no YAML dependency); "!" entries are negations.
  - Cargo:  root Cargo.toml [workspace] "members" / "exclude"
            (TOML-lite parse: sections, quoted strings, # comments).
  - Go:     go.work "use" directives (single-line and block form).
  - Python: root pyproject.toml [tool.uv.workspace] "members".

If no declared source yields any member pattern, a fallback kicks
in: top-level directories that contain a recognised manifest
(package.json / pyproject.toml / Cargo.toml / go.mod) — and, one
level deeper, their immediate subdirectories (the common
`packages/<name>` shape) — are reported as packages of kind
"detected": visibly distinct from "declared" packages, because
the evidence is weaker (a manifest in a subdir does not prove a
workspace relationship). The fallback never recurses further.

Glob rules: `*`, `?` and `[...]` match within a single path
segment (fnmatch); a `**` segment is treated as `*` (documented
simplification). Glob-expanded members must contain the ecosystem's
manifest to count (package.json for npm/pnpm, Cargo.toml for Cargo,
pyproject.toml for uv); literally-named members only need to exist.
Declared members that do not exist on disk are reported in
`missing`, never an error. Members that escape the project root
(`..` segments, absolute paths) are skipped and reported in
`warnings` — detection never reaches outside the root.

Nested workspaces: if one package path contains another, the
outermost wins and the inner one is dropped (real member sets do
not nest; this keeps assignment unambiguous). A file's package is
the kept package whose path prefixes it; files outside every
package belong to the root package (path "", labelled "(root)").
Per-package budgets are out of scope: this module is visibility
only (counts and shares), never selection.
"""
from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .textio import read_text as _gs_read_text

MANIFEST_NAMES = ("package.json", "pyproject.toml", "Cargo.toml", "go.mod")

# Root-directory names the fallback never treats as packages even
# when a stray manifest lands inside them (mirrors the scanner's
# own top-level ignores; the scanner will not walk these anyway).
_FALLBACK_SKIP_DIRS = {
    "node_modules", "dist", "build", "out", "target", "coverage",
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv",
    ".claude_context", ".ghostslice_bundle",
}


@dataclass
class Package:
    path: str                 # posix rel path; "" is the project root
    kind: str                 # "declared" | "detected" | "root"
    source: str               # human label naming the evidence
    manifest: str | None = None   # rel path of the evidencing manifest

    def to_dict(self) -> dict:
        return {"path": self.path, "kind": self.kind,
                "source": self.source, "manifest": self.manifest}


@dataclass
class WorkspaceInfo:
    root: str
    packages: list[Package] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    declared: bool = False    # a declared source yielded member patterns

    @property
    def is_monorepo(self) -> bool:
        return any(p.path for p in self.packages)

    def package_for(self, rel: str) -> str:
        """Package path owning a posix rel file path ("" = root)."""
        rel = rel.replace("\\", "/")
        for pkg in self.packages:
            if pkg.path and (rel == pkg.path or rel.startswith(pkg.path + "/")):
                return pkg.path
        return ""

    def to_dict(self) -> dict:
        return {
            "packages": [p.to_dict() for p in self.packages],
            "missing": list(self.missing),
            "warnings": list(self.warnings),
            "declared": self.declared,
            "is_monorepo": self.is_monorepo,
        }


# ---------------------------------------------------------------------------
# small parsing helpers (stdlib only; each parser is deliberately a
# "lite" reader for one well-known shape, not a general parser)


def _read(root: Path, name: str) -> str | None:
    try:
        return _gs_read_text(root / name)
    except OSError:
        return None


def _strip_hash_comments(text: str) -> str:
    """Remove # comments that sit outside '...' / "..." strings.

    Used for the TOML-lite reads (Cargo / pyproject), where member
    lists may carry trailing comments — including comments INSIDE a
    multi-line array. A # inside a quoted string is data, not a
    comment, and survives. Backslash escapes are honoured inside
    double-quoted (basic) strings only, matching TOML.
    """
    out: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote is not None:
            out.append(ch)
            if quote == '"' and ch == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _scan_strings(text: str, start: int) -> tuple[list[str], int]:
    """Collect quoted string literals from `start` until the matching
    closing bracket of the array that opens at/after `start`.

    Returns (strings, end_index). Quote-aware: brackets inside
    strings do not count. Assumes comments were already stripped.
    """
    strings: list[str] = []
    depth = 0
    quote: str | None = None
    buf: list[str] = []
    i = start
    while i < len(text):
        ch = text[i]
        if quote is not None:
            if quote == '"' and ch == "\\" and i + 1 < len(text):
                buf.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                strings.append("".join(buf))
                buf = []
                quote = None
            else:
                buf.append(ch)
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            buf = []
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth <= 0:
                return strings, i
        i += 1
    return strings, i


def _toml_section_strings(text: str, section: str, key: str) -> list[str]:
    """String array at `key = [...]` inside a `[section]` of TOML text.

    TOML-lite: finds the section by its header line, then the key
    within that section only, then reads the (possibly multi-line)
    array. Comments are stripped first (quote-aware).
    """
    clean = _strip_hash_comments(text)
    current: str | None = None
    section_start: int | None = None
    offset = 0
    for line in clean.splitlines(keepends=True):
        m = re.match(r"\s*\[([^\]]+)\]\s*$", line)
        if m:
            if current == section and section_start is not None:
                break  # a later section began; ours ended before it
            current = m.group(1).strip()
            if current == section:
                section_start = offset + len(line)
        offset += len(line)
    if section_start is None:
        if current == section:  # section was the last in the file
            section_start = offset - 0  # unreachable guard, kept simple below
        else:
            return []
    body = clean[section_start:] if section_start is not None else ""
    # Cut the body at the next section header so keys never bleed.
    nxt = re.search(r"(?m)^\s*\[[^\]]+\]\s*$", body)
    if nxt:
        body = body[:nxt.start()]
    km = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*\[", body)
    if not km:
        return []
    strings, _ = _scan_strings(body, km.end() - 1)
    return strings


def _pnpm_packages(text: str) -> list[str]:
    """Line-parse the top-level `packages:` list of pnpm-workspace.yaml.

    Block style (items at any indentation, since YAML allows the
    sequence at the key's own indentation) plus a single-line flow
    list `packages: ['libs/*']`. Blank and comment lines never end
    the list; the next top-level key does.
    """
    out: list[str] = []
    in_list = False
    for raw in text.splitlines():
        if not in_list:
            m = re.match(r"^packages\s*:\s*(.*?)\s*$", raw)
            if not m:
                continue
            rest = m.group(1)
            if not rest or rest.startswith("#"):
                in_list = True
            elif rest.startswith("[") and "]" in rest:
                strings, _ = _scan_strings(rest, 0)
                out.extend(strings)
            # Any other inline value is not a list shape we read.
            continue
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue  # blanks/comments never terminate a sequence
        # Item match first, at ANY indentation: YAML allows the
        # sequence under a key at the key's own (zero) indentation.
        m = re.match(r"^\s*-\s+(.+?)\s*$", raw)
        if m:
            value = m.group(1)
            if value[:1] in "\"'":
                end = value.find(value[0], 1)
                out.append(value[1:end] if end > 0 else value.strip("\"'"))
            else:
                out.append(value.split(" #", 1)[0].strip())
            continue
        if not raw.startswith((" ", "\t")):
            break  # next top-level key: the list is over
    return out


def _go_work_uses(text: str) -> list[str]:
    """`use` directives of a go.work file (single-line + block form)."""
    out: list[str] = []
    in_block = False
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if in_block:
            if line.startswith(")"):
                in_block = False
                continue
            if line:
                out.append(line.split()[0].strip("\"'"))
            continue
        if re.match(r"^use\s*\($", line):
            in_block = True
            continue
        m = re.match(r"^use\s+(\S+)", line)
        if m:
            out.append(m.group(1).strip("\"'"))
    return out


# ---------------------------------------------------------------------------
# glob expansion


def _is_glob_segment(seg: str) -> bool:
    return any(c in seg for c in "*?[")


def _expand_pattern(root: Path, pattern: str) -> tuple[list[str], bool]:
    """Expand one member pattern to existing directory rel paths.

    Returns (dirs, is_glob). `**` segments behave as `*`. Glob
    segments match directory names via fnmatchcase; literal segments
    must exist as directories. Never touches anything outside root:
    callers filter escaping patterns before expanding.
    """
    segments = [s for s in pattern.split("/") if s not in ("", ".")]
    is_glob = any(_is_glob_segment(s) or s == "**" for s in segments)
    segments = ["*" if s == "**" else s for s in segments]
    current = [""]
    for seg in segments:
        nxt: list[str] = []
        for base in current:
            base_dir = root / base if base else root
            if _is_glob_segment(seg):
                try:
                    children = sorted(p for p in base_dir.iterdir() if p.is_dir())
                except OSError:
                    children = []
                for child in children:
                    if fnmatch.fnmatchcase(child.name, seg):
                        nxt.append(f"{base}/{child.name}" if base else child.name)
            else:
                cand = f"{base}/{seg}" if base else seg
                if (root / cand).is_dir():
                    nxt.append(cand)
        current = nxt
        if not current:
            break
    return current, is_glob


def _unsafe(pattern: str) -> bool:
    p = pattern.strip()
    if p.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", p):
        return True
    return any(seg == ".." for seg in p.replace("\\", "/").split("/"))


# ---------------------------------------------------------------------------
# detection


def _root_package(root: Path) -> Package:
    for name in MANIFEST_NAMES:
        if (root / name).is_file():
            return Package(path="", kind="root",
                           source=f"project root ({name})", manifest=name)
    # Workspace-root files are root evidence too (a pure Go
    # workspace root may carry nothing else). They are deliberately
    # NOT in MANIFEST_NAMES: a stray go.work in a subdirectory must
    # never make that subdirectory a "detected" package.
    for name in ("go.work", "pnpm-workspace.yaml"):
        if (root / name).is_file():
            return Package(path="", kind="root",
                           source=f"project root ({name})", manifest=name)
    return Package(path="", kind="root", source="project root", manifest=None)


def _member_manifest(root: Path, rel: str, preferred: str | None) -> str | None:
    if preferred and (root / rel / preferred).is_file():
        return f"{rel}/{preferred}"
    for name in MANIFEST_NAMES:
        if (root / rel / name).is_file():
            return f"{rel}/{name}"
    return None


def detect_workspaces(root: str | Path) -> WorkspaceInfo:
    """Detect the package layout of the project at `root`.

    Reads root manifests only; safe on any directory (a project with
    no workspace evidence yields just the root package).
    """
    root = Path(root)
    info = WorkspaceInfo(root=str(root))
    info.packages.append(_root_package(root))
    warnings: list[str] = []
    missing: list[str] = []

    # (source label, patterns, negations, ecosystem manifest,
    #  exclude_applies_to_globs_only) — the flag is Cargo's rule:
    #  its `exclude` cannot remove an explicitly listed member.
    declared_sets: list[tuple[str, list[str], list[str], str, bool]] = []

    pkg_text = _read(root, "package.json")
    if pkg_text is not None:
        try:
            data = json.loads(pkg_text)
        except ValueError:
            data = None
            warnings.append("package.json could not be parsed; npm workspaces ignored")
        if isinstance(data, dict):
            ws = data.get("workspaces")
            patterns: list[str] = []
            if isinstance(ws, list):
                patterns = [p for p in ws if isinstance(p, str)]
            elif isinstance(ws, dict) and isinstance(ws.get("packages"), list):
                patterns = [p for p in ws["packages"] if isinstance(p, str)]
            if patterns:
                pos = [p for p in patterns if not p.startswith("!")]
                neg = [p[1:] for p in patterns if p.startswith("!")]
                declared_sets.append(("npm workspaces (package.json)",
                                      pos, neg, "package.json", False))

    pnpm_text = _read(root, "pnpm-workspace.yaml")
    if pnpm_text is not None:
        patterns = _pnpm_packages(pnpm_text)
        if patterns:
            pos = [p for p in patterns if not p.startswith("!")]
            neg = [p[1:] for p in patterns if p.startswith("!")]
            declared_sets.append(("pnpm-workspace.yaml",
                                  pos, neg, "package.json", False))

    cargo_text = _read(root, "Cargo.toml")
    if cargo_text is not None:
        members = _toml_section_strings(cargo_text, "workspace", "members")
        exclude = _toml_section_strings(cargo_text, "workspace", "exclude")
        if members:
            declared_sets.append(("cargo workspace (Cargo.toml)",
                                  members, exclude, "Cargo.toml", True))

    go_text = _read(root, "go.work")
    if go_text is not None:
        uses = _go_work_uses(go_text)
        if uses:
            declared_sets.append(("go.work", uses, [], "go.mod", False))

    py_text = _read(root, "pyproject.toml")
    if py_text is not None:
        members = _toml_section_strings(py_text, "tool.uv.workspace", "members")
        if members:
            declared_sets.append(("uv workspace (pyproject.toml)",
                                  members, [], "pyproject.toml", False))

    found: dict[str, Package] = {}
    saw_patterns = False
    for source, patterns, negations, manifest_name, globs_only in declared_sets:
        if patterns:
            saw_patterns = True
        removed: set[str] = set()
        for neg in negations:
            if _unsafe(neg):
                warnings.append(f"{source}: excluded member {neg!r} escapes the "
                                  "project root; skipped")
                continue
            dirs, _ = _expand_pattern(root, neg.strip().strip("/"))
            removed.update(dirs)
        # Cargo rule (audit G08 F3): `exclude` only blocks glob
        # inclusion; dirs named by a literal member pattern of the
        # same set are immune. Other ecosystems' negations remove
        # whatever they match (immune stays empty there).
        immune: set[str] = set()
        if globs_only and removed:
            for pattern in patterns:
                raw = pattern.strip().strip("/")
                if raw.startswith("./"):
                    raw = raw[2:]
                if not raw or raw == "." or _unsafe(raw):
                    continue
                dirs, is_glob = _expand_pattern(root, raw)
                if not is_glob:
                    immune.update(dirs)
        for pattern in patterns:
            raw = pattern.strip()
            if _unsafe(raw):
                warnings.append(f"{source}: member {raw!r} escapes the project "
                                  "root; skipped")
                continue
            pat = raw.strip("/")
            if pat.startswith("./"):
                pat = pat[2:]
            if not pat or pat == ".":
                continue  # a member naming the root itself is the root package
            dirs, is_glob = _expand_pattern(root, pat)
            if is_glob:
                matched = dirs
                dirs = [d for d in dirs
                        if (root / d / manifest_name).is_file()]
                if not dirs:
                    if not matched:
                        missing.append(raw)
                    # Matched directories without the ecosystem
                    # manifest are not members (and not "missing").
                    continue
            if not dirs:
                missing.append(raw)
                continue
            for d in dirs:
                if d in found:
                    continue
                if d in removed and d not in immune:
                    continue
                found[d] = Package(
                    path=d, kind="declared", source=source,
                    manifest=_member_manifest(root, d, manifest_name))
    info.declared = saw_patterns
    info.missing = sorted(set(missing))
    info.warnings = warnings

    packages = list(found.values())
    if not packages and not saw_patterns:
        # Fallback: directories carrying a manifest, at the top
        # level or one level below it (the packages/<name> shape).
        # Bounded: two levels, never a recursive hunt.
        def _manifest_in(d: Path) -> str | None:
            for name in MANIFEST_NAMES:
                if (d / name).is_file():
                    return name
            return None

        def _dirs(d: Path) -> list[Path]:
            try:
                return sorted(p for p in d.iterdir() if p.is_dir())
            except OSError:
                return []

        for child in _dirs(root):
            if child.name in _FALLBACK_SKIP_DIRS or child.name.startswith("."):
                continue
            hit = _manifest_in(child)
            if hit is not None:
                packages.append(Package(
                    path=child.name, kind="detected",
                    source="manifest fallback",
                    manifest=f"{child.name}/{hit}"))
                continue
            for grand in _dirs(child):
                if grand.name in _FALLBACK_SKIP_DIRS or grand.name.startswith("."):
                    continue
                hit = _manifest_in(grand)
                if hit is not None:
                    rel = f"{child.name}/{grand.name}"
                    packages.append(Package(
                        path=rel, kind="detected",
                        source="manifest fallback",
                        manifest=f"{rel}/{hit}"))

    # Outermost wins: drop any package nested under another package.
    packages.sort(key=lambda p: (p.path.count("/"), p.path))
    kept: list[Package] = []
    for pkg in packages:
        if any(pkg.path.startswith(k.path + "/") for k in kept):
            continue
        kept.append(pkg)
    info.packages.extend(sorted(kept, key=lambda p: p.path))
    return info


def summarize_packages(result, sliced_tokens: dict | None = None) -> list[dict]:
    """Per-package subtotals for a ScanResult.

    Groups the scan's files by their `package` field. Each entry:
    {path, label, kind, source, files, tokens, share} where share is
    the percentage of the scan's total ORIGINAL estimated tokens.
    When `sliced_tokens` ({path: sliced estimate}) is given, entries
    also carry sliced_tokens / sliced_share. Works on hand-built
    results too (no WorkspaceInfo): kinds then fall back to "root"
    for the root bucket and "detected" elsewhere.
    """
    info = getattr(result, "workspaces", None)
    by_path: dict[str, Package] = {}
    if info is not None:
        by_path = {p.path: p for p in info.packages}
    groups: dict[str, dict] = {}
    for f in result.files:
        g = groups.setdefault(f.package, {"files": 0, "tokens": 0, "sliced": 0})
        g["files"] += 1
        g["tokens"] += f.tokens
        if sliced_tokens is not None:
            g["sliced"] += sliced_tokens.get(f.path, 0)
    total = sum(g["tokens"] for g in groups.values())
    sliced_total = sum(sliced_tokens.values()) if sliced_tokens is not None else 0
    out: list[dict] = []
    for path, g in groups.items():
        pkg = by_path.get(path)
        entry = {
            "path": path,
            "label": path or "(root)",
            "kind": pkg.kind if pkg else ("root" if path == "" else "detected"),
            "source": pkg.source if pkg else "",
            "files": g["files"],
            "tokens": g["tokens"],
            "share": round(100.0 * g["tokens"] / total, 2) if total else 0.0,
        }
        if sliced_tokens is not None:
            entry["sliced_tokens"] = g["sliced"]
            entry["sliced_share"] = (round(100.0 * g["sliced"] / sliced_total, 2)
                                      if sliced_total else 0.0)
        out.append(entry)
    out.sort(key=lambda e: (-e["tokens"], e["path"]))
    return out
