"""Cross-reference declarations against imports and build the pack.

Sections produced:
  declared_and_used     - declared, and an import was found
  declared_not_imported - declared, no import found in scanned code.
                          Evidence wording only: this can be entry
                          points, plugins, type-only or runtime-loaded
                          packages, or code paths the scanners cannot
                          see. It is never a removal recommendation.
  imported_not_declared - a third-party import with no declaration.
                          Evidence: the importing files are named.
  pins                  - versions as recorded in local files. Direct
                          pins are listed in full; transitive lockfile
                          pins are recorded compactly (a name=version
                          list per lockfile), never dropped.
  build_requirements    - build tooling recorded in a manifest's build
                          section (pyproject [build-system] requires).
                          Reported separately, never counted as
                          declared dependencies and never compared
                          against imports (PLAN scope).

Wording guard: BANNED strings are checked against the rendered DEPS.md
before it is written; a hit is a bug and raises.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from . import __version__
from .imports_scan import METHOD_LABELS, ImportIndex
from .names import norm, py_dist_for_import

BANNED_WORDING = [
    "safe to remove",
    "vulnerable",
    "vulnerability",
    "outdated",
    "latest version",
    "security risk",
]

_EXACT_PIN = re.compile(r"^(?:==|=|)\s*([0-9][\w.!+-]*)$")
_RANGE_HINT = re.compile(r"^[~^><]")
_WILDCARD_SEGMENT = re.compile(r"(?:^|\.)[xX](?:\.|$)")


def _spec_pin(spec: str) -> str | None:
    """Version string if a manifest spec is one exact pin, else None.

    A bare `1.2.3`, `==1.2.3`, or `=1.2.3` is an exact pin as recorded.
    Ranges (~, ^, >=, wildcards with operators) are not pins. A
    wildcard is a range even when it wears no operator: `1.2.*`,
    `==1.2.*`, and `1.2.x` name a family of versions, and recording
    them as exact pins misstates the local evidence.
    """
    s = (spec or "").strip()
    if not s or "," in s or "*" in s or _RANGE_HINT.match(s):
        return None
    m = _EXACT_PIN.match(s)
    if not m:
        return None
    version = m.group(1)
    if _WILDCARD_SEGMENT.search(version):
        return None
    return version


def _source_groups(sources: list) -> list[dict]:
    """Group source evidence by the directory holding the manifest.

    The cross-reference remains project-wide (that is the pack's job),
    but a monorepo reader needs to see whether evidence came from the
    project root, a package, an example, or another nested directory.
    """
    groups: dict[str, dict] = {}
    for src in sources:
        directory = Path(src.rel).parent.as_posix()
        if directory == ".":
            directory = "."
        group = groups.get(directory)
        if group is None:
            group = {"directory": directory, "source_count": 0,
                     "files": [], "status_counts": {}}
            groups[directory] = group
        group["source_count"] += 1
        group["files"].append(src.rel)
        group["status_counts"][src.status] = \
            group["status_counts"].get(src.status, 0) + 1
    return [groups[key] for key in
            sorted(groups, key=lambda d: (d != ".", d))]


def build_pack(root_label: str, sources: list, idx: ImportIndex) -> dict:
    """Cross-reference parsed sources against scanned imports.

    ``sources`` are :class:`~ghostdeps.manifests.SourceResult` objects
    and ``idx`` is the import index from the scanner. Returns the pack
    dict that is written verbatim to ``deps-manifest.json`` and rendered
    by :func:`render_deps_md`. Declared and imported names are matched
    on ``(ecosystem, normalised name)`` keys, so an entry only counts as
    used when the import belongs to the same ecosystem.
    """
    declarations: list[dict] = []
    pins: list[dict] = []
    build_requirements: list[dict] = []
    eco_of_source = {s.rel: s.ecosystem for s in sources}
    for src in sources:
        declarations.extend(src.declarations)
        pins.extend(src.pins)
        for b in getattr(src, "build_requirements", []) or []:
            build_requirements.append(
                {"name": b["name"], "spec": b["spec"], "source": b["source"]})
        for d in src.declarations:
            # Cargo version strings are requirements (caret semantics),
            # not pins; Cargo's recorded pins live in Cargo.lock, which
            # is parsed at summary level for exactly that reason. So
            # manifest pins are only taken from Python/JS specs where
            # ==/bare is exact.
            if eco_of_source.get(d["source"]) == "rust":
                continue
            pin = _spec_pin(d["spec"])
            if pin:
                pins.append({"name": d["name"], "version": pin,
                             "source": d["source"], "via": "manifest",
                             "direct": True})

    # Declared side, keyed by (ecosystem, normalised name).
    declared: dict[tuple[str, str], dict] = {}
    for d in declarations:
        eco = eco_of_source.get(d["source"], "")
        key = (eco, norm(d["name"]))
        entry = declared.get(key)
        if entry is None:
            entry = {"name": d["name"], "norm": key[1], "ecosystem": eco,
                     "kinds": set(), "specs": [], "declared_in": set()}
            declared[key] = entry
        entry["kinds"].add(d["kind"] + (f":{d['group']}" if d.get("group") else ""))
        if d["spec"]:
            entry["specs"].append({"spec": d["spec"], "source": d["source"]})
        entry["declared_in"].add(d["source"])

    # Imported side: third-party candidates only, keyed the same way.
    imported: dict[tuple[str, str], dict] = {}
    other_imports = {"local": [], "stdlib": []}
    for rec in idx.records.values():
        eco = rec["ecosystem"]
        module = rec["module"]
        if rec["class"] in ("local", "stdlib"):
            other_imports[rec["class"]].append(
                {"module": module, "ecosystem": eco,
                 "files": sorted(rec["files"])})
            continue
        if eco == "python":
            dist, mapped = py_dist_for_import(module)
        else:
            dist, mapped = module, False
        key = (eco, norm(dist))
        entry = imported.get(key)
        if entry is None:
            entry = {"name": dist, "norm": key[1], "ecosystem": eco,
                     "import_name": module, "name_mapping_applied": mapped,
                     "method": rec["method"], "files": set()}
            imported[key] = entry
        entry["files"].update(rec["files"])

    used, not_imported, not_declared = [], [], []
    for key, d in sorted(declared.items()):
        base = {"name": d["name"], "ecosystem": d["ecosystem"],
                "kinds": sorted(d["kinds"]), "specs": d["specs"],
                "declared_in": sorted(d["declared_in"])}
        hit = imported.get(key)
        if hit:
            base["imported_in"] = sorted(hit["files"])
            base["import_name"] = hit["import_name"]
            base["name_mapping_applied"] = hit["name_mapping_applied"]
            used.append(base)
        else:
            not_imported.append(base)
    for key, im in sorted(imported.items()):
        if key not in declared:
            not_declared.append(
                {"name": im["name"], "ecosystem": im["ecosystem"],
                 "import_name": im["import_name"],
                 "name_mapping_applied": im["name_mapping_applied"],
                 "method": im["method"],
                 "imported_in": sorted(im["files"])})

    # Direct pins keep full per-pin records. Transitive lockfile pins
    # are recorded compactly: one group per (source, via) carrying a
    # sorted name=version list, so every pin is still in the manifest
    # without a full record per transitive entry.
    pin_rows = []
    transitive_groups: dict[tuple[str, str], list[str]] = {}
    n_transitive = 0
    for p in sorted(pins, key=lambda p: (norm(p["name"]), p["source"])):
        if p.get("direct", True):
            pin_rows.append({"name": p["name"], "version": p["version"],
                             "source": p["source"], "via": p["via"],
                             "direct": True})
        else:
            transitive_groups.setdefault((p["source"], p["via"]), []) \
                .append(f"{p['name']}={p['version']}")
            n_transitive += 1
    transitive_rows = [
        {"source": source, "via": via, "count": len(entries),
         "pins": sorted(entries)}
        for (source, via), entries in sorted(transitive_groups.items())
    ]
    build_rows = sorted(build_requirements,
                        key=lambda b: (norm(b["name"]), b["source"]))

    pack = {
        "tool": "ghostdeps",
        "version": __version__,
        "generated_at": _dt.datetime.now(_dt.timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": root_label,
        "sources": [s.record() for s in sources],
        "source_groups": _source_groups(sources),
        "parser_confidence": METHOD_LABELS,
        "files_scanned": idx.files_scanned,
        "import_scan": {
            "ignored_files": getattr(idx, "ignored_files", []),
            "ignored_file_count": len(getattr(idx, "ignored_files", [])),
            "ignore_sources": getattr(idx, "ignore_sources", []),
            "warnings": getattr(idx, "ignore_warnings", []),
        },
        "python_parse_failures": idx.parse_failures,
        "sections": {
            "declared_and_used": used,
            "declared_not_imported": not_imported,
            "imported_not_declared": not_declared,
            "pins": pin_rows,
            "transitive_pins": transitive_rows,
        },
        "build_requirements": build_rows,
        "local_imports": sorted(other_imports["local"],
                                key=lambda r: (r["ecosystem"], r["module"])),
        "stdlib_imports": sorted(other_imports["stdlib"],
                                 key=lambda r: (r["ecosystem"], r["module"])),
        "counts": {
            "declared": len(declared),
            "declared_and_used": len(used),
            "declared_not_imported": len(not_imported),
            "imported_not_declared": len(not_declared),
            "pins_recorded": len(pin_rows) + n_transitive,
            "pins_transitive_recorded": n_transitive,
            "build_requirements": len(build_rows),
        },
        "notes": [
            "Evidence only: sections record what local files declare and "
            "what scanned code imports. No network was used and no "
            "registry or advisory data was consulted.",
            "Versions are reported as recorded in the local files.",
            "declared_not_imported can be entry points, plugins, "
            "type-only packages, runtime-loaded modules, or code the "
            "scanners cannot see. It is a lead for a human, not a verdict.",
        ],
    }
    return pack


# ------------------------------------------------------------- DEPS.md

def _fmt_specs(specs: list[dict]) -> str:
    if not specs:
        return "no spec recorded"
    return "; ".join(f"`{s['spec']}` in {s['source']}" for s in specs)


def render_deps_md(pack: dict) -> str:
    """Render a pack dict (see :func:`build_pack`) as the ``DEPS.md`` text.

    Raises ``ValueError`` if any banned verdict wording would appear in
    the rendered report; that guard is a bug check, not user-facing
    validation, because the wording here is fixed copy.
    """
    c = pack["counts"]
    lines: list[str] = []
    lines.append("# GhostDeps pack")
    lines.append("")
    lines.append(f"Project: `{pack['root']}`  ")
    lines.append(f"Generated: {pack['generated_at']} by ghostdeps {pack['version']}")
    lines.append("")
    lines.append("Built from local files only. No network was used. Versions "
                 "below are as recorded in the local files.")
    lines.append("")
    lines.append("## Sources read")
    lines.append("")
    groups = pack.get("source_groups", [])
    if len(groups) > 1:
        rendered = []
        for group in groups:
            label = "project root" if group["directory"] == "." \
                else f"`{group['directory']}`"
            rendered.append(f"{label}: {group['source_count']}")
        lines.append("Manifest locations: " +
                     f"{len(groups)} ({'; '.join(rendered)}).")
        lines.append("")
    for s in pack["sources"]:
        note = f" - {s['note']}" if s["note"] else ""
        lines.append(f"- `{s['file']}` ({s['kind']}, {s['ecosystem']}): "
                     f"{s['status']}{note}")
    if not pack["sources"]:
        lines.append("- none found")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Declared dependencies: {c['declared']}")
    lines.append(f"- Declared and imported: {c['declared_and_used']}")
    lines.append(f"- Declared, no import found: {c['declared_not_imported']}")
    lines.append(f"- Imported, no declaration found: {c['imported_not_declared']}")
    lines.append(f"- Version pins recorded: {c['pins_recorded']}")
    if c.get("build_requirements"):
        lines.append(f"- Build requirements recorded separately (not "
                     f"counted as declared dependencies): "
                     f"{c['build_requirements']}")
    lines.append("")

    lines.append("## Declared and imported")
    lines.append("")
    if pack["sections"]["declared_and_used"]:
        for e in pack["sections"]["declared_and_used"]:
            lines.append(f"- **{e['name']}** ({e['ecosystem']}, "
                         f"{', '.join(e['kinds'])}): {_fmt_specs(e['specs'])}")
            lines.append(f"  - imported in: {', '.join(e['imported_in'])}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Declared, no import found in scanned code")
    lines.append("")
    lines.append("No import of these names was found in the scanned code. "
                 "That is all this section records. Common explanations "
                 "include command-line entry points, plugins loaded by "
                 "name at runtime, type-only packages, and modules loaded "
                 "dynamically. A human decides what, if anything, follows "
                 "from it.")
    lines.append("")
    if pack["sections"]["declared_not_imported"]:
        for e in pack["sections"]["declared_not_imported"]:
            lines.append(f"- **{e['name']}** ({e['ecosystem']}, "
                         f"{', '.join(e['kinds'])}): {_fmt_specs(e['specs'])}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Imported, no declaration found")
    lines.append("")
    lines.append("These imports were found in code but no matching "
                 "declaration was found in the parsed manifests. Common "
                 "explanations include packages available through another "
                 "declared package, sibling packages in a monorepo, and "
                 "name-mapping limits recorded per entry.")
    lines.append("")
    if pack["sections"]["imported_not_declared"]:
        for e in pack["sections"]["imported_not_declared"]:
            mapped = " (import name mapped to this distribution name)" \
                if e["name_mapping_applied"] else ""
            lines.append(f"- **{e['name']}** ({e['ecosystem']}){mapped}")
            lines.append(f"  - imported in: {', '.join(e['imported_in'])}")
            lines.append(f"  - extraction: {e['method']}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Version pins as recorded")
    lines.append("")
    lines.append("Direct pins (packages the project itself declares) are "
                 "listed in full. Transitive pins from a lockfile are "
                 "recorded under their lockfile as a count plus a compact "
                 "name=version list; every pin is also in "
                 "deps-manifest.json.")
    lines.append("")
    if pack["sections"]["pins"]:
        for p in pack["sections"]["pins"]:
            lines.append(f"- {p['name']}: `{p['version']}` as recorded in "
                         f"{p['source']} (via {p['via']})")
    elif not pack["sections"]["transitive_pins"]:
        lines.append("- no exact pins recorded in the parsed files")
    for g in pack["sections"]["transitive_pins"]:
        lines.append(f"- Transitive pins as recorded in {g['source']} "
                     f"(via {g['via']}): {g['count']} pin(s), listed "
                     f"compactly: " +
                     ", ".join(f"`{entry}`" for entry in g["pins"]))
    lines.append("")

    if pack["build_requirements"]:
        lines.append("## Build requirements as recorded")
        lines.append("")
        lines.append("These names come from a manifest's build section "
                     "(for example the [build-system] requires list in "
                     "pyproject.toml). They are build tooling recorded "
                     "for completeness: they are not counted in the "
                     "declared dependencies above and are not compared "
                     "against imports.")
        lines.append("")
        for b in pack["build_requirements"]:
            spec = f"`{b['spec']}`" if b["spec"] else "no spec recorded"
            lines.append(f"- **{b['name']}**: {spec} in {b['source']}")
        lines.append("")

    lines.append("## Limits")
    lines.append("")
    lines.append(f"- Python imports: {METHOD_LABELS['python']}.")
    lines.append(f"- JS/TS imports: {METHOD_LABELS['javascript']}; "
                 "computed specifiers and some re-export forms can be "
                 "missed. Comments are stripped with a string-aware "
                 "scanner, but this remains parser-lite, not a full "
                 "JavaScript parser.")
    lines.append("- Import scanning honours .gitignore files and the "
                 "root .ghostslice.json ignore list; manifest and "
                 "lockfile discovery is not filtered by those rules. "
                 "Ignored source files are listed in deps-manifest.json "
                 "under import_scan.")
    lines.append("- Manifest and lockfile evidence is grouped by "
                 "holding directory in source_groups; the dependency "
                 "cross-reference itself remains project-wide.")
    lines.append(f"- Rust imports: {METHOD_LABELS['rust']}; macro-generated "
                 "paths are not visible.")
    lines.append("- package-lock.json is read at summary level: direct "
                 "pins are listed in full, transitive pins are recorded "
                 "as a compact name=version list per lockfile, and "
                 "nested entries are counted, not reproduced.")
    lines.append("- Cargo.lock is read at summary level: local "
                 "(source-less) packages are the project itself and are "
                 "excluded from pins, packages a local package lists as "
                 "dependencies are direct pins listed in full, and all "
                 "other pins are recorded as a compact name=version "
                 "list per lockfile. Checksums and the full dependency "
                 "graph are not reproduced.")
    lines.append("- Import name to distribution name mapping uses a small "
                 "built-in table plus normalisation; unmapped names are "
                 "compared as written.")
    lines.append("")
    for note in pack["notes"]:
        lines.append(f"> {note}")
    lines.append("")
    text = "\n".join(lines)
    lowered = _scrub_evidence(text, pack)
    for banned in BANNED_WORDING:
        if banned in lowered:
            raise ValueError(f"banned wording reached DEPS.md: {banned!r}")
    return text


def _evidence_strings(pack: dict) -> list[str]:
    """User-controlled strings rendered into DEPS.md as evidence:
    the project path, package names, file names, specs, versions, and
    source notes. The banned-wording guard judges the tool's own
    prose, not this evidence: a dependency literally named
    ``outdated-thing``, or a project checked out under a directory
    containing ``vulnerable``, is a fact to report, and it used to
    make rendering raise and the whole pack fail.
    """
    out: set[str] = set()

    def add(value):
        if isinstance(value, str) and len(value.strip()) >= 2:
            out.add(value)

    add(pack.get("root"))
    for src in pack.get("sources", []):
        add(src.get("file"))
        add(src.get("note"))
    for group in pack.get("source_groups", []):
        add(group.get("directory"))
        for fname in group.get("files", []):
            add(fname)
    sections = pack.get("sections", {})
    for key in ("declared_and_used", "declared_not_imported"):
        for entry in sections.get(key, []):
            add(entry.get("name"))
            for fname in entry.get("imported_in", []):
                add(fname)
            for fname in entry.get("declared_in", []):
                add(fname)
            for spec in entry.get("specs", []):
                add(spec.get("spec"))
                add(spec.get("source"))
    for entry in sections.get("imported_not_declared", []):
        add(entry.get("name"))
        add(entry.get("import_name"))
        for fname in entry.get("imported_in", []):
            add(fname)
    for pin in sections.get("pins", []):
        add(pin.get("name"))
        add(pin.get("version"))
        add(pin.get("source"))
    for group in sections.get("transitive_pins", []):
        add(group.get("source"))
        for entry in group.get("pins", []):
            add(entry)
    for req in pack.get("build_requirements", []):
        add(req.get("name"))
        add(req.get("spec"))
        add(req.get("source"))
    return sorted(out, key=len, reverse=True)


def _scrub_evidence(text: str, pack: dict) -> str:
    """Lowercased ``text`` with evidence strings blanked out.

    Only standalone occurrences are blanked (a name character on
    either side means the match is inside a larger word, which is
    prose, not the evidence rendering), so tool prose is still
    checked whole.
    """
    scrubbed = text.lower()
    for evidence in _evidence_strings(pack):
        pattern = re.compile(
            r"(?<![A-Za-z0-9._-])" + re.escape(evidence.lower()) +
            r"(?![A-Za-z0-9._-])")
        scrubbed = pattern.sub(" ", scrubbed)
    return scrubbed
