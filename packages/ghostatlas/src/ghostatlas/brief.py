"""ATLAS.md architecture brief generation.

Extractive and factual only: layout, entry points with evidence,
sampled static call chains (labelled), config/data hotspots, test
layout, GhostSlice lint findings with their own messages, and - in
diligence mode - size/shape first, test presence, secrets counts and
types only, dependency surface, licence files, and git history span.
No invented module descriptions: a file's description is its
extracted docstring first line, or the brief says none was found.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from .reading import dead_zones, reading_minutes, reading_order


def checked_box_lines(data) -> list:
    """Return the "checked / not checked" lines for a run.

    Shared by the Markdown brief and the HTML map so both artifacts
    state the same limits. The list is factual about this run: it
    notes when git history was unavailable, when the fallback engine
    produced the numbers, and when no Python call graph was
    available. It never claims a security audit; that is
    GhostExposure's scope.
    """
    git_txt = ("git history (span and per-file activity, window: "
               + data.git.get("window", "") + ")" if data.git.get("available")
               else "git history (not available: no local git log)")
    lines = [
        "Checked: project file inventory and estimated token totals (GhostSlice estimator).",
        "Checked: import graph (Python parsed, other languages parser-lite, import-level only).",
        "Checked: entry-point candidates with per-file evidence.",
        f"Checked: {git_txt}.",
        "Checked: exact/near duplicate clusters.",
        "Checked: static test linkage (test imports and test naming conventions; tests themselves were not executed, so this is not measured coverage).",
        "Not checked: runtime behaviour, test execution, or profiling data (static analysis only).",
        "Not checked: security audit or vulnerability assessment (see GhostExposure for audit preparation).",
        "Not checked: any external service, registry, or network source.",
    ]
    if data.engine != "ghostslice":
        lines.append("Note: GhostSlice was not importable for this run; the labelled fallback engine produced the scan/graph numbers.")
    if not data.call_counts:
        lines.append("Not checked: Python call graph (unavailable for this run); flows show import-level information only.")
    return lines


def _file_line(f) -> str:
    doc = f.get("doc") or "No docstring first line found."
    syms = ", ".join(f.get("symbols", [])[:5])
    sym_part = f" Symbols: {syms}." if syms else ""
    return (f"- `{f['path']}` ({f.get('tokens', 0)} estimated tokens): "
            f"{doc}{sym_part}")


def _layout_lines(data) -> list:
    lines = ["## Layout", "",
             f"- Files: {len(data.files)}",
             f"- Total estimated tokens: {data.total_tokens}",
             f"- Total size: {data.total_size} bytes", ""]
    if data.packages:
        lines.append("| Package | Files | Est. tokens |")
        lines.append("|---|---:|---:|")
        for p in data.packages:
            label = p.get("label") or p.get("path") or "(root)"
            lines.append(f"| `{label}` | {p.get('files', 0)} | {p.get('tokens', 0)} |")
        lines.append("")
    langs = {}
    for f in data.files:
        langs[f.get("language", "other")] = langs.get(f.get("language", "other"), 0) + 1
    lines.append("Languages by file count: " + ", ".join(
        f"{k} {v}" for k, v in sorted(langs.items(), key=lambda kv: -kv[1])) + ".")
    lines.append("")
    return lines


def _reading_lines(data, top_n) -> list:
    order = reading_order(data, top_n)
    lines = ["## Start here: reading order", ""]
    if not order:
        lines += ["No reading order could be derived from the static analysis.", ""]
        return lines
    for i, o in enumerate(order, 1):
        doc = o.get("doc") or "No docstring first line found."
        lines.append(f"{i}. `{o['path']}`: {o['reason']} "
                     f"({o['tokens']} estimated tokens, about {o['reading_minutes']} reading minutes). {doc}")
    lines.append("")
    return lines


def _flows_lines(data) -> list:
    lines = ["## Main flows (sampled from static analysis)", ""]
    if data.call_chains:
        lines.append("Top call chains from the Python call graph, capped at 10, "
                     "sampled from static analysis (not runtime traces):")
        lines.append("")
        for c in data.call_chains:
            short = " -> ".join(s.rsplit(":", 1)[-1] for s in c["symbols"])
            lines.append(f"- {short}")
    else:
        lines.append("No Python call chains were available for this run. "
                     "Import-graph neighbours are listed in the HTML map; "
                     "no runtime flow is claimed.")
    lines.append("")
    return lines


def _hotspot_lines(data) -> list:
    cfg = [f for f in data.files
           if PurePosixPath(f["path"]).suffix.lower() in
           (".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".xml", ".sql")
           or f.get("language") in ("json", "yaml", "toml")]
    cfg.sort(key=lambda f: -f.get("tokens", 0))
    lines = ["## Data and config hotspots", ""]
    if cfg:
        for f in cfg[:10]:
            lines.append(_file_line(f))
    else:
        lines.append("No config/data files found by extension.")
    lines.append("")
    return lines


def _test_lines(data) -> list:
    tests = [f for f in data.files if f.get("is_test")]
    non_tests = len(data.files) - len(tests)
    lines = ["## Test layout", "",
             f"- Test files: {len(tests)} of {len(data.files)} files "
             f"({non_tests} non-test files)."]
    for f in sorted(tests, key=lambda x: x["path"])[:15]:
        lines.append(f"- `{f['path']}` ({f.get('tokens', 0)} estimated tokens)")
    if not tests:
        lines.append("- No test files were detected by the scanner's test-file rules.")
    cov = getattr(data, "test_coverage", None) or {}
    sources = cov.get("sources") or []
    if sources:
        s = cov.get("summary", {})
        lines += ["", "Covering shape (static test linkage, not measured "
                  "coverage): tests were not executed. Directly linked "
                  "means a test file imports the source file or follows "
                  "its test naming convention; indirectly linked means "
                  "reachable from a directly linked file through the "
                  "import graph.", "",
                  f"- Source files: {s.get('source_files', len(sources))}: "
                  f"{s.get('direct', 0)} directly linked, "
                  f"{s.get('indirect', 0)} indirectly linked, "
                  f"{s.get('unlinked', 0)} with no test link found."]
        for src in sources:
            if src["status"] == "direct":
                linked = ", ".join(f"`{t}`" for t in src.get("test_files", []))
                lines.append(f"- `{src['path']}`: directly linked from "
                             f"test file(s) {linked}.")
            elif src["status"] == "indirect":
                via = src.get("via")
                root = src.get("direct_source")
                if via and root and via != root:
                    how = f"via `{root}` through `{via}`"
                else:
                    how = f"via `{root or via}`"
                lines.append(f"- `{src['path']}`: indirectly linked {how} "
                             "in the import graph.")
        unlinked = [src for src in sources if src["status"] == "unlinked"]
        if unlinked:
            lines.append("")
            lines.append("Source files with no test link found "
                         "(observations for a human to judge, in "
                         "depended-on order):")
            for src in unlinked:
                lines.append(
                    f"- `{src['path']}` ({src.get('tokens', 0)} estimated "
                    f"tokens, depended on by {src.get('importer_count', 0)} "
                    "file(s)): no test link found.")
    lines.append("")
    return lines


def _dead_lines(data) -> list:
    zones = dead_zones(data)
    lines = ["## Dead zones: worth asking about", "",
             "Observations for a human to judge, not delete instructions.", ""]
    if zones["dead_files"]:
        lines.append("Files or symbols with no callers/importers found statically:")
        for d in zones["dead_files"][:20]:
            lines.append(f"- `{d['path']}`: {d.get('reason') or 'no importers found'}")
    else:
        lines.append("No dead-code candidates found by static analysis.")
    if zones["unreferenced_docs"]:
        lines += ["", "Documentation files not referenced by the import graph:"]
        for d in zones["unreferenced_docs"][:15]:
            lines.append(f"- `{d['path']}` ({d['tokens']} estimated tokens)")
    if zones["duplicate_clusters"]:
        lines += ["", "Duplicate clusters:"]
        for c in zones["duplicate_clusters"][:10]:
            lines.append(f"- {c['kind']}: " + ", ".join(f"`{p}`" for p in c["files"]))
    lines.append("")
    return lines


def _lint_lines(data) -> list:
    lines = ["## Known warnings (GhostSlice lint)", ""]
    if data.lint_findings:
        for f in data.lint_findings[:25]:
            lines.append(
                f"- {f.get('rule', '')} [{f.get('severity', '')}] "
                f"`{f.get('path', '')}`: {f.get('message', '')} "
                f"Action: {f.get('action', '')}")
    else:
        lines.append("No lint findings were carried into this run "
                     "(lint unavailable or no findings).")
    lines.append("")
    return lines


def _diligence_lines(data) -> list:
    s = data.secrets_summary or {}
    by_type = s.get("by_type") or {}
    type_txt = (", ".join(f"{k}: {v}" for k, v in sorted(by_type.items()))
                if by_type else "none")
    git = data.git or {}
    span = ("not available (no local git log)" if not git.get("available")
            else f"{git.get('first_date') or 'unknown'} to {git.get('last_date') or 'unknown'} "
                 f"({git.get('total_commits', 0)} commits in the local log)")
    cov_summary = (getattr(data, "test_coverage", None) or {}).get("summary")
    if cov_summary:
        linkage_txt = (
            f"{cov_summary.get('direct', 0) + cov_summary.get('indirect', 0)} of "
            f"{cov_summary.get('source_files', 0)} source file(s) directly or "
            f"indirectly linked to a test file; {cov_summary.get('unlinked', 0)} "
            "with no test link found.")
    else:
        linkage_txt = "not computed for this run."
    lines = ["## Diligence ordering", "",
             "This Atlas is an orientation aid, not an audit opinion.", "",
             f"- Project size: {len(data.files)} files, {data.total_tokens} estimated tokens, {data.total_size} bytes.",
             f"- Test presence: {sum(1 for f in data.files if f.get('is_test'))} test file(s) detected.",
             f"- Test linkage (static, not measured coverage): {linkage_txt}",
             f"- Secrets guard result (counts and types only, no values): {s.get('count', 0)} finding(s); types: {type_txt}.",
             "- Dependency surface from manifests: " +
             (", ".join(data.dependencies) if data.dependencies else "none declared in the manifests read") + ".",
             "- Licence files found: " +
             (", ".join(f"`{p}`" for p in data.licenses) if data.licenses else "none found") + ".",
             f"- History span (local git): {span}.",
             ""]
    lines.append("## Checked / not checked")
    lines.append("")
    for ln in checked_box_lines(data):
        lines.append(f"- {ln}")
    lines.append("")
    return lines


def _module_lines(data) -> list:
    lines = ["## Modules (extracted docstring first lines)", ""]
    for f in sorted(data.files, key=lambda x: (-x.get("tokens", 0), x["path"]))[:30]:
        lines.append(_file_line(f))
    lines.append("")
    return lines


def build_brief(data, top_n: int = 10) -> str:
    """Render the ``ATLAS.md`` architecture brief for a run.

    Section order depends on ``data.audience``: diligence leads with
    the diligence summary (size, tests, secrets counts, dependencies,
    licences, history) and its checked / not-checked box; onboarding
    leads with layout and the reading order and puts the box last.
    All sections are extractive and factual (see the module
    docstring); ``top_n`` caps the reading-order length.
    """
    title = data.title
    head = [f"# Atlas: {title}", "",
            f"Generated {data.generated_at} by GhostAtlas {__import__('ghostatlas').__version__} "
            f"(engine: {data.engine}; run stamp: {data.run_stamp}).",
            "Token counts are estimates from the GhostSlice estimator, "
            "not exact tokenizer counts.", ""]
    for note in (data.config or {}).get("audience_notes", []):
        head.append(f"Note: {note}")
    if (data.config or {}).get("audience_notes"):
        head.append("")
    body = []
    if data.audience == "diligence":
        body += _diligence_lines(data)
        body += _layout_lines(data)
        body += _reading_lines(data, top_n)
        body += _test_lines(data)
        body += _module_lines(data)
        body += _flows_lines(data)
        body += _hotspot_lines(data)
        body += _dead_lines(data)
        body += _lint_lines(data)
    else:
        body += _layout_lines(data)
        body += _reading_lines(data, top_n)
        body += _flows_lines(data)
        body += _module_lines(data)
        body += _hotspot_lines(data)
        body += _test_lines(data)
        body += _dead_lines(data)
        body += _lint_lines(data)
        body += ["## Checked / not checked", ""]
        body += [f"- {ln}" for ln in checked_box_lines(data)]
        body.append("")
    return "\n".join(head + body).rstrip() + "\n"
