"""Manifest and lockfile parsers. Local files only, stdlib only.

Every parser returns declarations and/or pins as recorded in the file.
A file that exists but is not parsed in v0.1 (or whose shape is not
recognised) is reported as detected-not-parsed, never silently skipped
and never guessed at.

Declaration: {name, spec, kind, group, source}
  kind: runtime | dev | optional | peer | build
  spec: the requirement text exactly as recorded ("" when none recorded)
Pin: {name, version, source, via, direct}
  via: lockfile | manifest (an exact pin written in a manifest)
  direct: True for pins of packages the project itself declares (for a
  lockfile, the packages named in the lockfile's root entry); False for
  transitive lockfile pins, which are recorded compactly downstream.

Build requirements are NOT declarations: a pyproject [build-system]
requires list is build tooling, kept on SourceResult.build_requirements
and surfaced separately so it never enters the declared/imported
comparison (PLAN scopes pyproject parsing to project dependencies,
optional-dependencies, and dependency-groups).
"""
from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path

from .names import norm

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "env", ".tox", ".nox", "target", "dist", "build", ".eggs", "vendor",
    ".mypy_cache", ".pytest_cache", ".idea", ".vscode",
}

# Files GhostDeps knows how to detect. Parsed in v0.1: pyproject.toml,
# requirements*.txt, package.json, package-lock.json (summary), Cargo.toml,
# Cargo.lock (summary).
DETECTED_ONLY_NAMES = {
    "gemfile": "Ruby (Gemfile)",
    "go.mod": "Go (go.mod)",
    "composer.json": "PHP (composer.json)",
    "pipfile": "Python (Pipfile)",
    "setup.py": "Python (setup.py, imperative: not parsed)",
    "setup.cfg": "Python (setup.cfg)",
    "yarn.lock": "JS (yarn.lock: summary parse not in v0.1)",
    "pnpm-lock.yaml": "JS (pnpm-lock.yaml: summary parse not in v0.1)",
    "poetry.lock": "Python (poetry.lock: full pin list not in v0.1)",
}


class SourceResult:
    """Parse outcome for one manifest or lockfile found in the tree.

    ``status`` is ``"parsed"``, ``"detected-not-parsed"``, or
    ``"error"``; ``note`` carries the human-readable reason or summary.
    ``declarations`` and ``pins`` hold the evidence extracted from the
    file, in the shapes described in the module docstring.
    """

    def __init__(self, path: Path, rel: str, kind: str, ecosystem: str):
        self.path = path
        self.rel = rel
        self.kind = kind  # manifest | lockfile
        self.ecosystem = ecosystem
        self.status = "parsed"  # parsed | detected-not-parsed | error
        self.note = ""
        self.declarations: list[dict] = []
        self.pins: list[dict] = []
        # Build tooling requirements (pyproject [build-system] requires).
        # Kept apart from declarations on purpose: they are not project
        # dependencies and are never compared against imports.
        self.build_requirements: list[dict] = []

    def record(self) -> dict:
        """Return the JSON-ready summary of this source for the pack manifest."""
        return {
            "file": self.rel,
            "kind": self.kind,
            "ecosystem": self.ecosystem,
            "status": self.status,
            "note": self.note,
            "build_requirements": self.build_requirements,
        }


def _decl(name, spec, kind, source, group=""):
    return {"name": name, "spec": spec or "", "kind": kind,
            "group": group, "source": source}


def _as_dict(value) -> dict:
    """The table at ``value``, or {} when it is not a table at all.

    Manifests in the wild carry wrong-typed fields (a TOML string where
    a table belongs, a JSON array as package.json). Treating a non-table
    as a table used to raise AttributeError and crash discovery; a
    non-dict simply contributes no entries here, and callers that need
    to say so record a note via ``_note``.
    """
    return value if isinstance(value, dict) else {}


def _as_list(value) -> list:
    """The list at ``value``, or [] when it is not a list.

    Iterating a bare string field (``dependencies = "requests"``) used
    to yield one bogus one-character declaration per character.
    """
    return value if isinstance(value, list) else []


def _note(res: "SourceResult", text: str) -> None:
    res.note = (res.note + "; " if res.note else "") + text


# ---------------------------------------------------------------- Python

_PEP508_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]|[A-Za-z0-9])")

# Characters that can legitimately open what follows a requirement
# name (after any extras): a version operator, a direct-reference "@",
# a marker ";", a parenthesised spec, a wildcard, or the first digit
# of a bare version. Anything else ("git+https://..." opens with "+")
# is not a requirement shape at all.
_SPEC_OPENERS = "<>=!~@;(*"


def parse_pep508(text: str) -> tuple[str, str] | None:
    """(name, spec) from a PEP 508 requirement string, as recorded.

    Extras are dropped from the name (Pillow[all] declares Pillow) and
    environment markers are dropped from the spec; the requirement core
    is kept verbatim. Text whose post-name remainder cannot start a
    version spec, a direct reference, or a marker is not a requirement
    and returns None (a bare VCS line such as ``git+https://...`` in a
    requirements file used to be misread as a package named "git").
    """
    m = _PEP508_NAME.match(text or "")
    if not m:
        return None
    name = m.group(0).strip()
    rest = text[m.end():].strip()
    if rest.startswith("["):
        end = rest.find("]")
        rest = rest[end + 1:].strip() if end >= 0 else ""
    if rest and not (rest[0] in _SPEC_OPENERS or rest[0].isdigit()):
        return None
    spec = rest.split(";", 1)[0].strip()
    return name, spec


def _req_list(res: SourceResult, value, where: str) -> list[str]:
    """String entries of a requirement list field.

    A field that is not a list, and entries that are not strings, are
    malformed evidence: they are skipped and counted in a note rather
    than iterated character by character or stringified into bogus
    requirement names (``str(True)`` used to declare a package "True").
    """
    if value is None:
        return []
    if not isinstance(value, list):
        _note(res, f"{where} is not a list; it was not parsed")
        return []
    out = []
    skipped = 0
    for entry in value:
        if isinstance(entry, str):
            out.append(entry)
        else:
            skipped += 1
    if skipped:
        _note(res, f"{skipped} non-string entr{'y' if skipped == 1 else 'ies'} "
                   f"in {where} skipped")
    return out


def _poetry_spec(val) -> str:
    """Poetry version text as recorded, without stringifying tables.

    A dict contributes its ``version`` key; a list of constraint tables
    (Poetry's multiple-constraints form) contributes the first table's
    version; a plain string is the version. Anything else records no
    spec: the name still comes from the table key, so the declaration
    itself is kept with an empty spec rather than a repr.
    """
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        version = val.get("version", "")
        return version if isinstance(version, str) else ""
    if isinstance(val, list):
        for item in val:
            if isinstance(item, dict) and isinstance(item.get("version"), str):
                return item["version"]
    return ""


def _parse_pyproject(path: Path, rel: str) -> SourceResult:
    """Parse a ``pyproject.toml``: project/optional/group + Poetry deps.

    The ``[build-system]`` requires list is recorded separately on
    ``build_requirements`` and never treated as a project dependency.
    Malformed TOML yields status ``"error"`` with the reason in the note.
    """
    res = SourceResult(path, rel, "manifest", "python")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # malformed TOML is evidence, not a crash
        res.status = "error"
        res.note = f"TOML parse failed: {exc}"
        return res
    if not isinstance(data.get("project", {}), dict) and "project" in data:
        _note(res, "[project] is not a table; it was not parsed")
    project = _as_dict(data.get("project"))
    for req in _req_list(res, project.get("dependencies"),
                         "project dependencies"):
        parsed = parse_pep508(req)
        if parsed:
            res.declarations.append(_decl(parsed[0], parsed[1], "runtime", rel))
    optional = project.get("optional-dependencies")
    if optional is not None and not isinstance(optional, dict):
        _note(res, "project optional-dependencies is not a table; "
                   "it was not parsed")
    for group, reqs in _as_dict(optional).items():
        for req in _req_list(res, reqs, f"optional-dependencies '{group}'"):
            parsed = parse_pep508(req)
            if parsed:
                res.declarations.append(
                    _decl(parsed[0], parsed[1], "optional", rel, group=str(group)))
    dep_groups = data.get("dependency-groups")
    if dep_groups is not None and not isinstance(dep_groups, dict):
        _note(res, "dependency-groups is not a table; it was not parsed")
    for group, entries in _as_dict(dep_groups).items():
        if entries is not None and not isinstance(entries, list):
            _note(res, f"dependency-group '{group}' is not a list; "
                       "it was not parsed")
            continue
        for entry in entries or []:
            if isinstance(entry, str):
                parsed = parse_pep508(entry)
                if parsed:
                    res.declarations.append(
                        _decl(parsed[0], parsed[1], "dev", rel, group=str(group)))
            elif isinstance(entry, dict) and "include-group" in entry:
                _note(res, f"dependency-group '{group}' includes group "
                           f"'{entry['include-group']}' (recorded, not expanded)")
    # [build-system] requires are build tooling, not project
    # dependencies (PLAN scope). Record them separately; they never
    # enter the declared set or the declared/imported comparison.
    if "build-system" in data and not isinstance(data.get("build-system"), dict):
        _note(res, "[build-system] is not a table; it was not parsed")
    build = _as_dict(data.get("build-system"))
    for req in _req_list(res, build.get("requires"), "build-system requires"):
        parsed = parse_pep508(req)
        if parsed:
            res.build_requirements.append(
                _decl(parsed[0], parsed[1], "build", rel))
    poetry = _as_dict(_as_dict(data.get("tool")).get("poetry"))
    for name, val in _as_dict(poetry.get("dependencies")).items():
        if str(name).lower() == "python":
            continue
        res.declarations.append(
            _decl(str(name), _poetry_spec(val), "runtime", rel))
    for name, val in _as_dict(poetry.get("dev-dependencies")).items():
        res.declarations.append(
            _decl(str(name), _poetry_spec(val), "dev", rel))
    return res


_REQ_SKIP_PREFIXES = ("-", "--hash")
# pip accepts "-r file", "-r=file", "--requirement file",
# "--requirement=file" (and the same shapes for -c/--constraint). The
# whitespace-only form used to count the "=" forms as unparsed lines.
_REQ_INCLUDE = re.compile(
    r"^(?:-r|--requirement|-c|--constraint)(?:\s*=\s*|\s+)(\S+)"
    r"|^-r(\S+)")


def _parse_requirements(path: Path, rel: str) -> SourceResult:
    """Parse a ``requirements*.txt`` file, one requirement per line.

    ``-r``/``--requirement`` includes are noted, not followed. Option
    lines and lines not in requirement shape are counted in the note
    rather than guessed at; ``-e ...#egg=name`` lines record ``name``.
    """
    res = SourceResult(path, rel, "manifest", "python")
    try:
        lines = path.read_text(encoding="utf-8-sig",
                               errors="replace").splitlines()
    except OSError as exc:
        res.status = "error"
        res.note = f"read failed: {exc}"
        return res
    includes = []
    unparsed = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        inc = _REQ_INCLUDE.match(line)
        if inc:
            includes.append(inc.group(1) or inc.group(2))
            continue
        # Strip trailing comments (a # preceded by whitespace) and markers.
        line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
        if not line or line.startswith(_REQ_SKIP_PREFIXES):
            if line.startswith("-e") and "#egg=" in line:
                egg = line.split("#egg=", 1)[1].split("&")[0].strip()
                if egg:
                    res.declarations.append(_decl(egg, "editable", "runtime", rel))
                    continue
            if line:
                unparsed += 1
            continue
        parsed = parse_pep508(line)
        if parsed:
            res.declarations.append(_decl(parsed[0], parsed[1], "runtime", rel))
        else:
            unparsed += 1
    notes = []
    if includes:
        notes.append("includes noted, not followed: " + ", ".join(includes))
    if unparsed:
        notes.append(f"{unparsed} line(s) not in requirement shape, skipped")
    res.note = "; ".join(notes)
    return res


# -------------------------------------------------------------------- JS

def _js_spec(value) -> str:
    """A package.json spec as recorded, without stringifying JSON types.

    Specs are strings in a well-formed manifest. A number is kept as
    its digits; anything else (null, bool, list, object) records no
    spec rather than a Python repr such as "None" or "['1', '2']".
    The name still comes from the section key, so the declaration
    itself survives with an empty spec.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _parse_package_json(path: Path, rel: str) -> SourceResult:
    """Parse ``package.json`` dependency sections as declarations.

    Reads ``dependencies``, ``devDependencies``, ``peerDependencies``,
    and ``optionalDependencies``; specs are kept exactly as written.
    """
    res = SourceResult(path, rel, "manifest", "javascript")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        res.status = "error"
        res.note = f"JSON parse failed: {exc}"
        return res
    if not isinstance(data, dict):
        # Valid JSON, wrong shape ("[]", "null", a bare string): this is
        # a malformed manifest, recorded as an error, never a crash.
        res.status = "error"
        res.note = "JSON top level is not an object; no declarations read"
        return res
    sections = [
        ("dependencies", "runtime"),
        ("devDependencies", "dev"),
        ("peerDependencies", "peer"),
        ("optionalDependencies", "optional"),
    ]
    for key, kind in sections:
        section = data.get(key)
        if section is None:
            continue
        if not isinstance(section, dict):
            _note(res, f"{key} is not an object; it was not parsed")
            continue
        for name, spec in section.items():
            res.declarations.append(
                _decl(str(name), _js_spec(spec), kind, rel))
    return res


def _parse_package_lock(path: Path, rel: str) -> SourceResult:
    """Summary-level only: root pins and top-level package pins.

    Every top-level pin is recorded, split into direct pins (packages
    the lockfile's root entry itself declares) and transitive pins
    (everything else installed at the top level). Nested entries are
    counted, not reproduced.
    """
    res = SourceResult(path, rel, "lockfile", "javascript")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        res.status = "error"
        res.note = f"JSON parse failed: {exc}"
        return res
    if not isinstance(data, dict):
        res.status = "error"
        res.note = "JSON top level is not an object; no pins read"
        return res
    packages = data.get("packages")
    total = 0
    if isinstance(packages, dict) and packages:
        root = _as_dict(packages.get(""))
        direct_names = set()
        for key in ("dependencies", "devDependencies",
                    "peerDependencies", "optionalDependencies"):
            section = root.get(key)
            if isinstance(section, dict):
                # Only mapping keys are names. Iterating a bare string
                # section used to add every character as a "name" and
                # misclassify the matching pins as transitive.
                direct_names.update(norm(n) for n in section)
            elif isinstance(section, list):
                direct_names.update(
                    norm(n) for n in section if isinstance(n, str))
        for pkg_path, info in packages.items():
            if not pkg_path or not isinstance(info, dict):
                continue
            total += 1
            if pkg_path.count("node_modules") > 1:
                continue  # nested: counted only, not recorded as a pin
            name = pkg_path.split("node_modules/")[-1]
            version = info.get("version")
            if name and isinstance(version, (str, int, float)) \
                    and not isinstance(version, bool):
                res.pins.append({"name": name, "version": str(version),
                                 "source": rel, "via": "lockfile",
                                 "direct": norm(name) in direct_names})
        n_direct = sum(1 for p in res.pins if p["direct"])
        res.note = (f"lockfileVersion {data.get('lockfileVersion', '?')}; "
                    f"summary level: {n_direct} direct pin(s), "
                    f"{len(res.pins) - n_direct} transitive pin(s), "
                    f"{total} package entries total")
    elif isinstance(data.get("dependencies"), dict):
        # Legacy (lockfileVersion 1) shape is a flat top-level map with
        # no root entry to split direct from transitive against; its
        # entries are recorded as direct pins, as before.
        for name, info in data["dependencies"].items():
            version = info.get("version") if isinstance(info, dict) else None
            if isinstance(version, (str, int, float)) \
                    and not isinstance(version, bool):
                res.pins.append({"name": name, "version": str(version),
                                 "source": rel, "via": "lockfile",
                                 "direct": True})
        res.note = (f"lockfileVersion {data.get('lockfileVersion', '?')} "
                    f"(legacy shape); summary level")
    else:
        res.status = "detected-not-parsed"
        res.note = "lockfile shape not recognised; no pins extracted"
    return res


# ------------------------------------------------------------------ Rust

def _cargo_section(res: SourceResult, table, kind: str, rel: str):
    """Append one Cargo dependency table (string or inline-table form) to ``res``."""
    if table is not None and not isinstance(table, dict):
        _note(res, "a Cargo dependency table is not a table; "
                   "it was not parsed")
        return
    for name, val in _as_dict(table).items():
        if isinstance(val, dict):
            if "version" in val:
                version = val["version"]
                spec = version if isinstance(version, str) else ""
            elif "path" in val:
                spec = f"path: {val['path']}"
            elif "git" in val:
                spec = f"git: {val['git']}"
            else:
                spec = ""
        elif isinstance(val, str):
            spec = val
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            spec = str(val)
        else:
            # A list or other non-spec value: the crate name comes from
            # the key, so keep the declaration with no spec rather
            # than a stringified repr such as "['1']".
            spec = ""
        res.declarations.append(_decl(str(name), spec, kind, rel))


def _parse_cargo_toml(path: Path, rel: str) -> SourceResult:
    """Parse ``Cargo.toml`` dependency tables and note workspace members.

    Covers ``dependencies``, ``dev-dependencies``, ``build-dependencies``,
    per-target dependency tables, and ``[workspace.dependencies]``.
    """
    res = SourceResult(path, rel, "manifest", "rust")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        res.status = "error"
        res.note = f"TOML parse failed: {exc}"
        return res
    pkg = _as_dict(data.get("package"))
    _cargo_section(res, data.get("dependencies"), "runtime", rel)
    _cargo_section(res, data.get("dev-dependencies"), "dev", rel)
    _cargo_section(res, data.get("build-dependencies"), "build", rel)
    for target in _as_dict(data.get("target")).values():
        if isinstance(target, dict):
            _cargo_section(res, target.get("dependencies"), "runtime", rel)
    workspace = _as_dict(data.get("workspace"))
    _cargo_section(res, workspace.get("dependencies"), "runtime", rel)
    members = workspace.get("members")
    if isinstance(members, str):
        members = [members]  # a bare string is one member, not its chars
    if members:
        if isinstance(members, list):
            _note(res, f"workspace with {len(members)} member(s) noted: " +
                  ", ".join(str(m) for m in members))
        else:
            _note(res, "workspace members value is not a list; "
                       "it was not parsed")
    if pkg.get("name"):
        _note(res, f"package name as recorded: {pkg['name']}")
    return res


def _cargo_lock_dep_name(entry) -> str:
    """Name from a Cargo.lock ``dependencies`` entry, as recorded.

    Entries are strings in one of these shapes::

        "serde"
        "serde 1.0.197"
        "serde 1.0.197 (registry+https://...)"
    The name is always the first whitespace-separated token.
    """
    if isinstance(entry, str):
        parts = entry.split()
        return parts[0] if parts else ""
    if isinstance(entry, dict):
        # Not a shape Cargo itself writes, but stay evidence-only if
        # a hand-edited lockfile uses it: take the recorded name.
        return str(entry.get("name", "") or "")
    return ""


def _parse_cargo_lock(path: Path, rel: str) -> SourceResult:
    """Summary-level only: pins as recorded in ``Cargo.lock``.

    Cargo.toml records version *requirements* (caret semantics), not
    pins, so without this parser a Rust project never contributes any
    pins to a pack. ``Cargo.lock`` is a TOML file of ``[[package]]``
    entries; every non-local entry is recorded as a pin.

    Direct vs transitive follows the lockfile's own evidence: a
    package with no ``source`` is a local (workspace / root) package
    -- it is the project itself, not a dependency, so it is excluded
    from the pins. The names listed in a local package's
    ``dependencies`` are the direct pins; every other recorded pin
    is transitive. If the lockfile records no local package, no
    direct pin can be proven from the file, so every pin is recorded
    as transitive rather than guessed to be direct.

    Checksums, sources, and the full dependency graph are summary
    data: they are counted / used for the direct split, never
    reproduced in the pack. Duplicate names at different versions
    (Cargo allows both) are preserved as separate pins.
    """
    res = SourceResult(path, rel, "lockfile", "rust")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # malformed TOML is evidence, not a crash
        res.status = "error"
        res.note = f"TOML parse failed: {exc}"
        return res
    packages = data.get("package")
    if not isinstance(packages, list) or not packages:
        res.status = "detected-not-parsed"
        res.note = "lockfile shape not recognised; no pins extracted"
        return res

    local_packages: list[dict] = []
    remote_packages: list[dict] = []
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        if "source" in pkg:
            remote_packages.append(pkg)
        else:
            local_packages.append(pkg)

    direct_norms: set[str] = set()
    for local in local_packages:
        for entry in local.get("dependencies", []) or []:
            name = _cargo_lock_dep_name(entry)
            if name:
                direct_norms.add(norm(name))

    for pkg in remote_packages:
        name = pkg.get("name")
        version = pkg.get("version")
        if not name or version is None:
            continue
        res.pins.append({
            "name": str(name),
            "version": str(version),
            "source": rel,
            "via": "lockfile",
            "direct": norm(str(name)) in direct_norms,
        })
    n_direct = sum(1 for p in res.pins if p["direct"])
    lock_version = data.get("version", "?")
    res.note = (
        f"Cargo.lock version {lock_version}; summary level: "
        f"{n_direct} direct pin(s), {len(res.pins) - n_direct} "
        f"transitive pin(s), {len(packages)} package entries total, "
        f"{len(local_packages)} local package(s) excluded from pins")
    return res


# -------------------------------------------------------------- discovery

_PARSERS = {
    "pyproject.toml": _parse_pyproject,
    "package.json": _parse_package_json,
    "package-lock.json": _parse_package_lock,
    "cargo.toml": _parse_cargo_toml,
    "cargo.lock": _parse_cargo_lock,
}


def _is_requirements(name: str) -> bool:
    """True for ``requirements*.txt`` file names (case-insensitive)."""
    low = name.lower()
    return low.startswith("requirements") and low.endswith(".txt")


_FALLBACK_KIND_ECO = {
    "pyproject.toml": ("manifest", "python"),
    "package.json": ("manifest", "javascript"),
    "package-lock.json": ("lockfile", "javascript"),
    "cargo.toml": ("manifest", "rust"),
}


def _run_parser(parser, fpath: Path, rel: str, low: str) -> SourceResult:
    """Run one manifest parser, converting any unexpected failure
    into an error source instead of aborting discovery of the rest
    of the tree. Malformed input is evidence, not a crash: one bad
    manifest must not hide every other manifest in the project.
    """
    try:
        return parser(fpath, rel)
    except Exception as exc:  # a parser bug must not kill the pack
        kind, eco = _FALLBACK_KIND_ECO.get(
            low, ("manifest", "python") if _is_requirements(low)
            else ("manifest", ""))
        res = SourceResult(fpath, rel, kind, eco)
        res.status = "error"
        res.note = f"parse failed unexpectedly: {type(exc).__name__}: {exc}"
        return res


def discover_sources(root: Path) -> list[SourceResult]:
    """Find and parse every manifest/lockfile in the tree.

    Root-level manifests are the primary evidence. Manifests deeper in
    the tree are parsed too (monorepos, examples) with their relative
    path recorded as the source; node_modules and VCS dirs are skipped.
    """
    results: list[SourceResult] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in sorted(filenames):
            low = fname.lower()
            fpath = Path(dirpath) / fname
            rel = str(fpath.relative_to(root))
            parser = _PARSERS.get(fname) or _PARSERS.get(low)
            if parser is not None:
                results.append(_run_parser(parser, fpath, rel, low))
            elif _is_requirements(fname):
                results.append(
                    _run_parser(_parse_requirements, fpath, rel, low))
            elif low in DETECTED_ONLY_NAMES:
                res = SourceResult(fpath, rel, "manifest",
                                   DETECTED_ONLY_NAMES[low].split(" ")[0].lower())
                res.status = "detected-not-parsed"
                res.note = DETECTED_ONLY_NAMES[low] + ": detected, not parsed in v0.1"
                if low.endswith(".lock"):
                    res.kind = "lockfile"
                results.append(res)
    results.sort(key=lambda r: (r.rel.count("/"), r.rel))
    return results
