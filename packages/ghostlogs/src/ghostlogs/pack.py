"""Incident pack builder: budget selection plus INCIDENT.md and
manifest.json writers.

Emission priority under the budget: timeline anchors (mandatory),
then error windows (highest severity, then file order), then
duplicate exemplars (highest count first).

Budget fit is decided on the rendered pack, not on per-item
estimates alone (those once underestimated the document scaffold
badly enough to ship an over-budget pack while a fittable selection
existed; see FIX_REPORT.md, defect D3). The builder descends a tier
ladder, rendering and measuring each candidate for real:

  full      - windows with all stored lines, plus exemplars
  trimmed   - windows trimmed to matched lines, trace/continuation
              lines, and repeat representatives, plus exemplars
  exemplars - no windows; anchors plus duplicate exemplars
  anchors   - the mandatory minimum only

The first tier whose rendered estimate lands at or under the budget
ships with a clean exit. The over-budget path (pack written, marked
over_budget, exit 1) is reached only when even the anchors tier
cannot fit, i.e. when the mandatory content alone exceeds the
budget, which is the only case the plan reserves it for.

Counts reconcile exactly by construction at every tier and are
re-checked here: total source lines = kept + collapsed + dropped,
and the dropped reasons sum to the dropped total. Anchor lines that
also fall inside a window or a duplicate group are counted once, as
kept; the by-reason arithmetic adjusts for that overlap explicitly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .analyze import Analysis
from .patterns import is_continuation
from .redact import redact_line
from .tokens import METHOD, SOURCE, estimate_tokens

# Tokens held back for the INCIDENT.md scaffolding (title, source
# line, counts line, section headers, not-shown summary). Measured
# at ~330-370 on an empty log; reserving less than the real
# scaffolding lets selection "fit" a pack whose finished estimate
# then lands over budget, which the plan forbids.
SCAFFOLD_RESERVE = 340
WINDOW_HEADER_COST = 15
EXEMPLAR_SUFFIX_COST = 8
ANCHOR_SECTION_COST = 40
MAX_GROUPS_IN_MANIFEST = 200
MAX_WINDOWS_IN_MANIFEST = 500
MAX_GROUPS_IN_DOC = 100
MAX_BUCKETS_IN_MANIFEST = 1000
MAX_BUCKETS_IN_DOC = 48

LIMITS = [
    "Evidence only: this pack shows what matched, how often, and in "
    "what order. It offers no diagnosis and no root cause.",
    "A failure written in words no pattern matches is invisible to "
    "this pack. 'No error windows matched' means no lines matched "
    "the pattern set, not that nothing went wrong.",
    "Near-duplicate grouping masks timestamps, numbers, hex ids, "
    "UUIDs, IPs, and quoted strings. Two different errors that "
    "differ only in a masked part share one exemplar; the "
    "byte-identical count is reported beside the total.",
    "Token figures are estimates from the stamped method, not a "
    "vendor tokenizer count.",
    "Window line storage is capped per run; lines past the cap are "
    "counted as dropped (window store cap), never silently lost.",
    "The first burst of an error is windowed in full context; "
    "later bursts of the same error collapse into duplicate "
    "exemplars, and consecutive repeats inside a window collapse "
    "in place. Either way the exact occurrence count is stated "
    "in the manifest and in the Repeated lines section.",
    "If a pack had to descend the budget tiers to fit, the "
    "manifest records which tier shipped (budget_tier) and what "
    "the tier means (budget_tier_meaning), and INCIDENT.md "
    "states the tier on its face. Lines trimmed from a window "
    "to fit are counted under windows not fitted, never "
    "silently lost.",
    "The evidence overview counts each matched line once, at its "
    "highest matched severity, and once per pattern it matches in "
    "the per-pattern tallies, so the per-pattern tallies can sum "
    "to more than the matched-line total. Hour buckets use the "
    "timestamps exactly as written (no timezone conversion, and "
    "syslog timestamps carry no year in the source); matched lines "
    "without a recognised timestamp are counted separately and "
    "fall in no bucket.",
    "Secret-shape redaction is exact about lengths by design: "
    "the aws-access-key shape is AKIA or ASIA plus exactly 16 "
    "characters (20 in total, the same shape GhostSlice's guard "
    "uses), so a longer or shorter look-alike is not that shape. "
    "Other provider shapes are minimum-length, and a generic "
    "assignment needs a sensitive-looking name plus a value of "
    "at least 8 characters with at least 4 distinct characters. "
    "Redaction lowers risk; it is not a guarantee that every "
    "credential form is caught.",
]


class _Redactor:
    """Applies redact_line while a pack is written, tallying hits by shape.

    A fresh instance per render attempt, so the counts in the shipped
    manifest describe the shipped pack only, never a discarded tier
    candidate. When disabled (--no-redact), text passes through
    unchanged and no counts accrue.
    """
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.counts: dict[str, int] = {}

    def apply(self, text: str) -> str:
        if not self.enabled or text is None:
            return text
        out, hits = redact_line(text)
        for shape in hits:
            self.counts[shape] = self.counts.get(shape, 0) + 1
        return out


@dataclass
class PackResult:
    """What build_pack returns: where the pack was written, the
    manifest dict exactly as written to manifest.json, and whether
    the shipped pack is over its budget."""
    out_dir: Path
    manifest: dict
    over_budget: bool


# Budget tiers, richest first. See the module docstring.
TIERS = ("full", "trimmed", "exemplars", "anchors")

# Plain-words meaning of each tier, carried in the manifest as
# budget_tier_meaning so the tier name never stands unexplained.
TIER_MEANINGS = {
    "full": "Every selected window and duplicate exemplar is "
            "shown in full.",
    "trimmed": "Windows are shown with plain context lines "
               "trimmed away; matched lines, trace lines, and "
               "repeat representatives are kept.",
    "exemplars": "Error windows are omitted to fit the budget; "
                 "timeline anchors and duplicate exemplars are "
                 "shown.",
    "anchors": "Only the mandatory timeline anchors are shown; "
               "everything else was counted as dropped.",
}

# Shorter gloss printed on the face of INCIDENT.md when a pack
# shipped below the full tier.
TIER_MD_GLOSS = {
    "trimmed": "windows trimmed of plain context lines to fit",
    "exemplars": "error windows omitted to fit; anchors and "
                 "duplicate exemplars kept",
    "anchors": "only the mandatory timeline anchors kept",
}

# Appended to INCIDENT.md when a pack ships over budget, so the
# pack file itself (the file handed to a reader or an agent) says
# so, not only the manifest and the terminal.
OVER_BUDGET_SECTION = (
    "## Pack status\n"
    "\n"
    "OVER BUDGET: this pack exceeds its token budget. It carries "
    "only the mandatory content (the timeline anchors and the "
    "pack scaffolding), and even that minimum did not fit the "
    "budget. The over-budget outcome is stated here, in the "
    "manifest (over_budget: true), and in the exit code."
)


def _trimmed_lines(win) -> set:
    """The stored lines a trimmed window keeps: lines that matched a
    pattern, trace/continuation lines, and the stored line directly
    above each in-place repeat run (so collapsed repeats stay
    represented by the line above them). Everything else in the
    window is plain context, which is what trimming gives up."""
    match_lines = {m["line"] for m in win.matches}
    representatives = {lo - 1 for lo, _ in win.repeat_ranges}
    keep = set()
    for no, text in win.stored:
        if no in match_lines or no in representatives \
                or is_continuation(text):
            keep.add(no)
    return keep


def _select(analysis: Analysis, budget: int, tier: str):
    """Greedy per-item selection for one tier. Returns (kept,
    window_lines, emitted_groups): kept is the set of kept source
    line numbers, window_lines maps an emitted window's index to the
    set of its stored line numbers to print, and emitted_groups is
    the list of routine duplicate groups whose exemplar is emitted.
    Per-item estimates with the scaffold reserve only guide the
    greedy choice; the tier ladder judges fit on the rendered pack.
    """
    total = analysis.total_lines
    kept: set[int] = set()
    if total > 0:
        kept.add(1)
        kept.add(total)

    remaining = budget - SCAFFOLD_RESERVE
    if analysis.first_line_text is not None:
        remaining -= estimate_tokens(analysis.first_line_text)
    if analysis.last_line_text is not None and total > 1:
        remaining -= estimate_tokens(analysis.last_line_text)
    remaining -= ANCHOR_SECTION_COST

    window_lines: dict[int, set] = {}
    if tier in ("full", "trimmed"):
        ordered = sorted(range(len(analysis.windows)),
                         key=lambda i: (-analysis.windows[i].severity,
                                        analysis.windows[i].start_line))
        for i in ordered:
            win = analysis.windows[i]
            if tier == "full":
                lines = {no for no, _ in win.stored}
            else:
                lines = _trimmed_lines(win)
            cost = WINDOW_HEADER_COST + sum(
                estimate_tokens(t) for no, t in win.stored if no in lines)
            if cost <= remaining:
                window_lines[i] = lines
                remaining -= cost
                kept |= lines

    emitted_groups: list = []
    if tier != "anchors":
        groups = sorted(analysis.duplicate_groups,
                        key=lambda g: (-g.occurrences, g.first_line))
        for group in groups:
            cost = estimate_tokens(group.exemplar) + EXEMPLAR_SUFFIX_COST
            if cost <= remaining:
                emitted_groups.append(group)
                remaining -= cost
                kept.add(group.exemplar_line)
    return kept, window_lines, emitted_groups


def _assemble(analysis: Analysis, budget: int, tier: str,
              red: _Redactor, win_groups: list) -> dict:
    """Select, account, and render one tier candidate. The counts
    partition every source line exactly once: a line is kept (in the
    kept set), collapsed (an emitted group's extra occurrences, or
    an in-window repeat represented by a kept stored line above it),
    or dropped under exactly one reason."""
    total = analysis.total_lines
    kept, window_lines, emitted_groups = _select(analysis, budget, tier)
    groups = sorted(analysis.duplicate_groups,
                    key=lambda g: (-g.occurrences, g.first_line))
    emitted_group_ids = {id(g) for g in emitted_groups}

    def anchor_overlap(group) -> int:
        """Members of this group that are also timeline anchors
        (line 1 or the last line, duplicate-accounted, and not the
        exemplar itself). Those lines are already counted in kept,
        so they must not also count as collapsed or dropped."""
        n = 0
        if analysis.first_dup_signature == group.signature \
                and group.exemplar_line != 1:
            n += 1
        if total > 1 and analysis.last_dup_signature == group.signature \
                and group.exemplar_line != total:
            n += 1
        return n

    collapsed = sum(g.occurrences - 1 - anchor_overlap(g)
                    for g in emitted_groups)

    # Dropped reasons, adjusted for anchor overlap.
    routine = 0
    for group in analysis.dup_groups.values():
        if group.occurrences == 1 and group.exemplar_line not in kept:
            routine += 1
    dup_not_emitted = 0
    for group in groups:
        if id(group) not in emitted_group_ids:
            dup_not_emitted += group.occurrences - (
                1 if group.exemplar_line in kept else 0) \
                - anchor_overlap(group)
    window_not_fitted = 0
    window_store_cap = 0
    for i, win in enumerate(analysis.windows):
        overflow_lines = set(range(win.end_line - win.overflow + 1,
                                   win.end_line + 1)) if win.overflow else set()
        window_store_cap += win.overflow - len(overflow_lines & kept)
        repeat_in_kept = sum(
            1 for lo, hi in win.repeat_ranges for no in kept if lo <= no <= hi)
        if i in window_lines:
            # Emitted (full or trimmed). A collapsed-in-place repeat
            # counts as collapsed only when the stored line above its
            # run is kept to represent it; on a full window that is
            # every repeat, which reduces to repeats - repeat_in_kept.
            # Stored lines the tier did not keep (trimming) count as
            # window lines that did not fit.
            for lo, hi in win.repeat_ranges:
                if (lo - 1) in kept:
                    collapsed += sum(
                        1 for no in range(lo, hi + 1) if no not in kept)
            window_not_fitted += len(win.stored) - sum(
                1 for no, _ in win.stored if no in kept)
        else:
            stored_in_kept = sum(1 for no, _ in win.stored if no in kept)
            window_not_fitted += len(win.stored) - stored_in_kept \
                + win.repeats - repeat_in_kept

    kept_count = len(kept)
    dropped = total - kept_count - collapsed
    reasons = {
        "routine": routine,
        "duplicate_not_emitted": dup_not_emitted,
        "window_not_fitted": window_not_fitted,
        "window_store_cap": window_store_cap,
    }
    reconciles = (kept_count + collapsed + dropped == total
                  and sum(reasons.values()) == dropped)

    incident_md = _render_incident(analysis, red, window_lines,
                                   emitted_groups, groups, win_groups,
                                   kept_count, collapsed, dropped,
                                   reasons, budget, tier)
    return {
        "kept": kept,
        "window_lines": window_lines,
        "emitted_groups": emitted_groups,
        "groups": groups,
        "emitted_group_ids": emitted_group_ids,
        "kept_count": kept_count,
        "collapsed": collapsed,
        "dropped": dropped,
        "reasons": reasons,
        "reconciles": reconciles,
        "incident_md": incident_md,
        "pack_tokens": estimate_tokens(incident_md),
    }


def build_pack(analysis: Analysis, out_dir, budget: int,
               patterns: list, redact: bool = True) -> PackResult:
    """Write an incident pack for `analysis` into `out_dir` and return a PackResult.

    Descends the budget tier ladder (see the module docstring),
    writes INCIDENT.md and manifest.json, and reports over_budget
    when even the anchors tier exceeds `budget`. `patterns` is the
    loaded pattern list, recorded in the manifest. With
    `redact=False` (--no-redact), excerpts are emitted unredacted
    and the manifest records that redaction was disabled.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    total = analysis.total_lines
    win_groups = analysis.window_duplicate_groups

    # Descend the tier ladder, rendering and measuring each candidate
    # for real. Each attempt gets a fresh redactor so the shipped
    # manifest's redaction counts describe the shipped pack only.
    # The first tier that fits ships; if none fits, the anchors tier
    # (the mandatory minimum) ships, marked over budget.
    tier = TIERS[-1]
    red = _Redactor(redact)
    att = _assemble(analysis, budget, tier, red, win_groups)
    for candidate in TIERS:
        cand_red = _Redactor(redact)
        cand = _assemble(analysis, budget, candidate, cand_red,
                         win_groups)
        tier, red, att = candidate, cand_red, cand
        if cand["pack_tokens"] <= budget:
            break

    kept = att["kept"]
    window_lines = att["window_lines"]
    emitted_windows = set(window_lines)
    emitted_groups = att["emitted_groups"]
    groups = att["groups"]
    emitted_group_ids = att["emitted_group_ids"]
    kept_count = att["kept_count"]
    collapsed = att["collapsed"]
    dropped = att["dropped"]
    reasons = att["reasons"]
    reconciles = att["reconciles"]
    incident_md = att["incident_md"]
    pack_tokens = att["pack_tokens"]
    over_budget = pack_tokens > budget
    if over_budget:
        # The pack file itself must say it is over budget, not only
        # the manifest and the terminal. The estimate is recomputed
        # on the final text so pack_estimated_tokens still describes
        # the pack exactly as written.
        incident_md = incident_md.rstrip("\n") + "\n\n" \
            + OVER_BUDGET_SECTION + "\n"
        pack_tokens = estimate_tokens(incident_md)
        over_budget = pack_tokens > budget

    manifest = {
        "tool": "ghostlogs",
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "path": analysis.source_path,
            "bytes": analysis.source_bytes,
            "sha256": analysis.source_sha256,
            "lines": total,
        },
        "token_method": METHOD,
        "estimator_source": SOURCE,
        "budget_tokens": budget,
        "budget_tier": tier,
        "budget_tier_meaning": TIER_MEANINGS[tier],
        "pack_estimated_tokens": pack_tokens,
        "over_budget": over_budget,
        "estimated_tokens_in": analysis.estimated_tokens_in,
        "counts": {
            "total_lines": total,
            "kept": kept_count,
            "collapsed": collapsed,
            "dropped": dropped,
            "dropped_by_reason": reasons,
            "equation": "total_lines = kept + collapsed + dropped",
            "reconciles": reconciles,
        },
        "anchors": {
            "first_line": _anchor_line(1, analysis.first_line_text, red),
            "last_line": _anchor_line(total, analysis.last_line_text, red),
            "first_timestamp": _anchor_ts(analysis.first_timestamp),
            "last_timestamp": _anchor_ts(analysis.last_timestamp),
        },
        # Evidence overview: exact tallies over the whole file,
        # counted in the analyser before any claim decision. Counts
        # only (bucket labels are timestamp prefixes, pattern ids
        # come from the loaded pattern set); no line text is carried
        # here, so the overview needs no redaction and adds none.
        "summary": {
            "matched_lines": analysis.matched_lines,
            "by_severity": {
                str(sev): analysis.severity_counts[sev]
                for sev in sorted(analysis.severity_counts)},
            "by_pattern": {
                pid: analysis.pattern_counts[pid]
                for pid in sorted(analysis.pattern_counts)},
            "lines_with_timestamp": analysis.lines_with_timestamp,
            "lines_without_timestamp":
                total - analysis.lines_with_timestamp,
            "matched_lines_without_timestamp":
                analysis.matched_lines_without_timestamp,
            "timeline": {
                "granularity": "hour, from the timestamp exactly as "
                               "written (no timezone conversion)",
                "buckets": len(analysis.timeline_buckets),
                "list_truncated":
                    len(analysis.timeline_buckets)
                    > MAX_BUCKETS_IN_MANIFEST,
                "list": analysis.timeline_buckets[
                    :MAX_BUCKETS_IN_MANIFEST],
            },
        },
        "windows": {
            "matched": len(analysis.windows),
            "emitted": len(emitted_windows),
            "suppressed_repeat_matches": analysis.suppressed_repeat_matches,
            "list_truncated": len(analysis.windows) > MAX_WINDOWS_IN_MANIFEST,
            "list": [
                {
                    "start_line": w.start_line,
                    "end_line": w.end_line,
                    "match_line": w.match_line,
                    "pattern": w.pattern_id,
                    "severity": w.severity,
                    "matches": w.matches,
                    "stored_lines": len(w.stored),
                    "overflow_lines": w.overflow,
                    "repeat_lines_collapsed_in_window": w.repeats,
                    "emitted": i in emitted_windows,
                    "trimmed_lines": (
                        len(w.stored) - len(window_lines[i])
                        if i in window_lines else 0),
                }
                for i, w in enumerate(analysis.windows[:MAX_WINDOWS_IN_MANIFEST])
            ],
        },
        "duplicates": {
            "groups": len(groups),
            "emitted_groups": len(emitted_groups),
            "list_truncated": len(groups) > MAX_GROUPS_IN_MANIFEST,
            "list": [
                {
                    "signature": red.apply(g.signature),
                    "exemplar": red.apply(g.exemplar),
                    "occurrences": g.occurrences,
                    "exact_copies": g.exact_copies,
                    "first_line": g.first_line,
                    "last_line": g.last_line,
                    "emitted": id(g) in emitted_group_ids,
                }
                for g in groups[:MAX_GROUPS_IN_MANIFEST]
            ],
            # Duplicate accounting for lines inside error windows
            # (defect D1): these lines never enter the routine table
            # above, so without this section a repeated error line's
            # exact count was stated nowhere.
            "window_groups": len(win_groups),
            "window_list_truncated":
                len(win_groups) > MAX_GROUPS_IN_MANIFEST,
            "window_list": [
                {
                    "signature": red.apply(g.signature),
                    "exemplar": red.apply(g.exemplar),
                    "occurrences": g.occurrences,
                    "exact_copies": g.exact_copies,
                    "first_line": g.first_line,
                    "last_line": g.last_line,
                    "in_window": True,
                }
                for g in win_groups[:MAX_GROUPS_IN_MANIFEST]
            ],
        },
        "patterns": [
            {"id": p.id, "regex": p.regex.pattern, "severity": p.severity,
             "kind": p.kind}
            for p in patterns
        ],
        "redaction": {
            "enabled": redact,
            "counts": dict(sorted(red.counts.items())),
            "total": sum(red.counts.values()),
            "scope": "redactions applied while writing pack outputs "
                     "(INCIDENT.md and manifest.json); the same "
                     "literal appearing in both files counts per file",
        },
        "limits": LIMITS,
    }

    (out_dir / "INCIDENT.md").write_text(incident_md, encoding="utf-8")
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return PackResult(out_dir, manifest, over_budget)


def _anchor_line(no, text, red: _Redactor):
    if text is None:
        return None
    return {"line": no, "text": red.apply(text)}


def _anchor_ts(ts):
    if ts is None:
        return None
    return {"text": ts[0], "line": ts[1]}


def _render_incident(a: Analysis, red: _Redactor, window_lines: dict,
                     emitted_groups: list, all_groups: list,
                     win_groups: list,
                     kept: int, collapsed: int, dropped: int,
                     reasons: dict, budget: int, tier: str) -> str:
    emitted_windows = set(window_lines)
    name = Path(a.source_path).name
    lines: list[str] = []
    lines.append(f"# Incident pack: {name}")
    lines.append("")
    lines.append(
        f"Source: {a.source_path} ({a.source_bytes} bytes, "
        f"sha256 {a.source_sha256[:12]}..., {a.total_lines} lines, "
        f"estimated {a.estimated_tokens_in} tokens in full).")
    lines.append(
        f"Token budget: {budget}. Estimator: {METHOD}.")
    if tier != "full":
        lines.append(
            f"Budget tier: {tier} ({TIER_MD_GLOSS[tier]}).")
    lines.append(
        f"Counts: {a.total_lines} lines in = {kept} kept + "
        f"{collapsed} collapsed + {dropped} dropped "
        f"(routine {reasons['routine']}, duplicate exemplars not "
        f"emitted {reasons['duplicate_not_emitted']}, windows not "
        f"fitted {reasons['window_not_fitted']}, window store cap "
        f"{reasons['window_store_cap']}).")
    lines.append("")
    lines.append("## Timeline anchors")
    lines.append("")
    if a.total_lines == 0:
        lines.append("The source file is empty.")
    else:
        lines.append(f"- First line (line 1): {red.apply(a.first_line_text or '')}")
        lines.append(
            f"- Last line (line {a.total_lines}): "
            f"{red.apply(a.last_line_text or '')}")
        if a.first_timestamp:
            lines.append(
                f"- First timestamp: {a.first_timestamp[0]} "
                f"(line {a.first_timestamp[1]})")
        if a.last_timestamp:
            lines.append(
                f"- Last timestamp: {a.last_timestamp[0]} "
                f"(line {a.last_timestamp[1]})")
        if not a.first_timestamp:
            lines.append("- No recognised timestamps in this log.")
    lines.append("")
    lines.append("## Evidence overview")
    lines.append("")
    # The overview is summary statistics, not selected excerpts, so
    # it renders at every tier; at the anchors tier (where only the
    # mandatory minimum ships) it compacts to the counts alone and
    # points at the manifest for the buckets and tallies, so the
    # summary never crowds out the mandatory anchors it sits beside.
    sev = ", ".join(
        f"severity {s}: {a.severity_counts[s]}"
        for s in sorted(a.severity_counts))
    if a.matched_lines == 0:
        lines.append(
            "No lines matched the pattern set (see the error windows "
            "section).")
    elif tier == "anchors":
        lines.append(
            f"Matched lines: {a.matched_lines} of {a.total_lines} "
            f"({sev}). Hour buckets and per-pattern tallies are in "
            f"manifest.json.")
    else:
        pat = ", ".join(
            f"{pid}: {a.pattern_counts[pid]}"
            for pid in sorted(a.pattern_counts))
        lines.append(
            f"Matched lines: {a.matched_lines} of {a.total_lines} "
            f"({sev}).")
        lines.append(f"By pattern: {pat}.")
        if a.timeline_buckets:
            lines.append(
                "Hour buckets (as written, no timezone conversion):")
            for b in a.timeline_buckets[:MAX_BUCKETS_IN_DOC]:
                lines.append(
                    f"- {b['bucket']}: {b['lines']} lines, "
                    f"{b['matched_lines']} matched"
                    + (f", max severity {b['max_severity']}"
                       if b['matched_lines'] else "")
                    + f" (lines {b['first_line']}-{b['last_line']})")
            if len(a.timeline_buckets) > MAX_BUCKETS_IN_DOC:
                lines.append(
                    f"- Plus {len(a.timeline_buckets) - MAX_BUCKETS_IN_DOC} "
                    f"more hour buckets in manifest.json.")
            if a.matched_lines_without_timestamp:
                lines.append(
                    f"- Plus {a.matched_lines_without_timestamp} matched "
                    f"lines with no recognised timestamp (in no bucket).")
        elif a.total_lines:
            lines.append(
                "No recognised timestamps, so no hour buckets.")
    lines.append("")
    lines.append(
        f"## Error windows ({len(emitted_windows)} emitted of "
        f"{len(a.windows)} matched)")
    lines.append("")
    if not a.windows:
        lines.append(
            "No lines matched the pattern set. That is a statement "
            "about the patterns, not about whether anything went wrong.")
    elif not emitted_windows:
        lines.append(
            "Windows matched but none fitted the remaining budget. "
            "Their lines are counted under windows not fitted.")
    for i, win in enumerate(a.windows):
        if i not in emitted_windows:
            continue
        shown = [(no, text) for no, text in win.stored
                 if no in window_lines[i]]
        trimmed = len(win.stored) - len(shown)
        lines.append(
            f"### Lines {win.start_line}-{win.end_line}: matched "
            f"{win.pattern_id} at line {win.match_line} "
            f"(severity {win.severity})")
        if win.repeats:
            lines.append(
                f"({win.repeats} consecutive repeats collapsed in "
                f"place; represented by the stored line above.)")
        if trimmed:
            lines.append(
                f"(Window trimmed to fit the budget: {trimmed} "
                f"context lines not shown; matched lines, trace "
                f"lines, and repeat representatives kept. Trimmed "
                f"lines are counted under windows not fitted.)")
        lines.append("")
        lines.append("```")
        for _, text in shown:
            lines.append(red.apply(text))
        lines.append("```")
        if win.overflow:
            lines.append(
                f"Plus {win.overflow} more lines in this window that "
                f"were not stored (window store cap).")
        lines.append("")
    lines.append(
        f"## Repeated lines: {len(emitted_groups)} of "
        f"{len(all_groups)} duplicate groups emitted (counts exact)")
    lines.append("")
    if not all_groups:
        lines.append("No repeated lines found outside the windows.")
    for group in emitted_groups[:MAX_GROUPS_IN_DOC]:
        lines.append(
            f"- x{group.occurrences} (byte-identical x"
            f"{group.exact_copies}), lines {group.first_line}-"
            f"{group.last_line}: {red.apply(group.exemplar)}")
    if len(emitted_groups) > MAX_GROUPS_IN_DOC:
        lines.append(
            f"- Plus {len(emitted_groups) - MAX_GROUPS_IN_DOC} more "
            f"emitted groups in manifest.json.")
    if win_groups:
        lines.append("")
        lines.append(
            "Repeated lines inside error windows (shown in their "
            "windows when a window is emitted; counts exact):")
        for group in win_groups[:MAX_GROUPS_IN_DOC]:
            lines.append(
                f"- x{group.occurrences} (byte-identical x"
                f"{group.exact_copies}), lines {group.first_line}-"
                f"{group.last_line}: {red.apply(group.exemplar)}")
        if len(win_groups) > MAX_GROUPS_IN_DOC:
            lines.append(
                f"- Plus {len(win_groups) - MAX_GROUPS_IN_DOC} more "
                f"window groups in manifest.json.")
    lines.append("")
    lines.append("## What was not shown")
    lines.append("")
    lines.append(f"- Routine lines dropped: {reasons['routine']}")
    lines.append(
        f"- Duplicate occurrences, exemplar not emitted: "
        f"{reasons['duplicate_not_emitted']}")
    lines.append(
        f"- Window lines not fitted: {reasons['window_not_fitted']}")
    lines.append(
        f"- Window lines past the storage cap: "
        f"{reasons['window_store_cap']}")
    if red.enabled:
        lines.append(
            "- Secret-shaped literals in emitted excerpts were "
            "redacted by shape; counts are in manifest.json. "
            "Values are never printed.")
    else:
        lines.append(
            "- Redaction was DISABLED for this run (--no-redact). "
            "Excerpts may contain secret-shaped literals.")
    lines.append("")
    return "\n".join(lines)
