"""FIXTURE.md rendering: the fixture manifest in human form."""
from __future__ import annotations


def render_fixture_md(m: dict) -> str:
    """Render a fixture manifest dict as the human-readable FIXTURE.md.

    Mirrors the manifest: what was included and why, what was
    excluded or left out and why, plus any drift and upstream
    guard disagreement sections when the manifest carries them.
    """
    t = m["totals"]
    lines: list = []
    lines.append("# GhostFixture - minimal repro project")
    lines.append("")
    if m.get("task"):
        lines.append(f"Task: {m['task']}")
        lines.append("")
    lines.append(f"- Source project: {m['source_project']}")
    lines.append(f"- Source bundle: {m['source_bundle']}")
    lines.append(f"- Bundle manifest sha256: {m['source_bundle_manifest_sha256']}")
    lines.append(f"- Generated at: {m['generated_at']}")
    lines.append(f"- Size cap: {m['max_bytes']} bytes total copied content")
    lines.append(f"- Included: {t['files_included']} files, {t['bytes_copied']} bytes")
    lines.append(f"- Excluded as secret-flagged: {t['files_excluded_flagged']}")
    lines.append(f"- Left out (other reasons): {t['files_left_out']}")
    dc = m.get("drift_check") or {}
    drift = m.get("drift") or []
    if dc.get("comparable_files"):
        if drift:
            lines.append(f"- Drift check: {len(drift)} of {dc['comparable_files']} "
                         "comparable files differ from the bundle's recorded "
                         "content (see the drift warning below)")
        else:
            lines.append(f"- Drift check: all {dc['comparable_files']} comparable "
                         "files match the bundle's recorded content")
    disagreements = m.get("upstream_disagreements") or []
    if disagreements:
        lines.append(f"- Upstream guard disagreements: {len(disagreements)} copied "
                     "file(s) were flagged by GhostSlice's guard in the bundle "
                     "manifest but not confirmed by this tool's shape scan "
                     "(see the disagreement section below)")
    lines.append("")
    if drift:
        lines.append("## Drift warning: copied files that differ from the bundle")
        lines.append("")
        lines.append("These files were copied from the project as it is NOW, "
                     "but their bytes differ from the content the bundle "
                     "recorded at export time (bundle mode 'full', so the "
                     "comparison is exact). The project changed after the "
                     "bundle was exported, or the bundle text was "
                     "transformed. The fixture therefore holds the current "
                     "project state for these files, not the exact context "
                     "the bundle captured:")
        lines.append("")
        for e in drift:
            lines.append(f"- `{e['path']}` - bundle sha256 {e['bundle_sha256'][:12]}..., "
                         f"copied sha256 {e['copied_sha256'][:12]}...")
        lines.append("")
        lines.append("Only bundle entries at mode 'full' can be compared this "
                     "way; other modes store sliced text, not the file, so no "
                     "drift claim is made for them either way.")
        lines.append("")
    if disagreements:
        lines.append("## Upstream guard findings not confirmed by the shape scan")
        lines.append("")
        lines.append("GhostSlice's secret guard flagged these files when the "
                     "bundle was exported, and the bundle manifest recorded "
                     "the findings (the per-file 'redactions' and "
                     "'redaction_kinds' fields). GhostFixture's own scan is "
                     "shape-based and runs over the original project file; "
                     "it found no secret shape in these files, so they were "
                     "copied. The guard is name-based and this scan is "
                     "shape-based, so the two disagree by design: the flag "
                     "is recorded here, with the kinds the guard reported, "
                     "so a reader sees both verdicts and can judge. Nothing "
                     "about the flag was dropped; the file was copied with "
                     "the disagreement on record:")
        lines.append("")
        for e in disagreements:
            kinds = ", ".join(e["upstream_kinds"]) or "(kinds not recorded)"
            lines.append(f"- `{e['path']}` - upstream guard kinds: {kinds} "
                         f"({e['upstream_redactions']} recorded finding(s)); "
                         "shape scan found no secret shape; copied")
        lines.append("")
    lines.append("## Included files")
    lines.append("")
    if m["included"]:
        for e in m["included"]:
            via = f" (via {e['via']})" if e.get("via") else ""
            mode = f", bundle mode {e['bundle_mode']}" if e.get("bundle_mode") else ""
            lines.append(f"- `{e['path']}` - {e['reason']}{via}{mode}, {e['bytes']} bytes")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Excluded: secret-flagged (path + pattern type only, never values)")
    lines.append("")
    def _upstream_suffix(e) -> str:
        if e.get("upstream_kinds"):
            return (f"; also flagged by the bundle's guard "
                    f"({', '.join(e['upstream_kinds'])}) - both scanners agree")
        return ""

    flagged = [e for e in m["excluded_flagged"] if not e.get("included_by_override")]
    overridden = [e for e in m["excluded_flagged"] if e.get("included_by_override")]
    if flagged:
        for e in flagged:
            lines.append(f"- `{e['path']}` - {', '.join(e['types'])}{_upstream_suffix(e)}")
    else:
        lines.append("(none)")
    if overridden:
        lines.append("")
        lines.append("Flagged but included by explicit --include-flagged override:")
        for e in overridden:
            lines.append(f"- `{e['path']}` - {', '.join(e['types'])}{_upstream_suffix(e)}")
    lines.append("")
    lines.append("## Left out")
    lines.append("")
    if m["left_out"]:
        for e in m["left_out"]:
            note = ""
            if e.get("upstream_kinds"):
                note = (f"; the bundle's guard also flagged this file "
                        f"({', '.join(e['upstream_kinds'])})")
            lines.append(f"- `{e['path']}` - {e['reason']}: {e['detail']}{note}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## External references (not copied: packages and unresolved modules)")
    lines.append("")
    if m["external_references"]:
        for e in m["external_references"]:
            lines.append(f"- `{e['from']}` imports `{e['specifier']}`")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Import closure by language")
    lines.append("")
    for lang, note in sorted(m["closure_by_language"].items()):
        lines.append(f"- {lang}: {note}")
    lines.append("")
    lines.append("## Honest limits")
    lines.append("")
    for limit in m["limits"]:
        lines.append(f"- {limit}")
    lines.append("")
    return "\n".join(lines)
