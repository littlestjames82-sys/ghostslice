"""Report writers: replay-report.json + REPLAY.md.

Both are deterministic: the same transcript + manifest produce
byte-identical files on re-run (JSON sorted keys, no wall-clock
timestamps anywhere in either artifact; session times come from
the transcript itself). REPLAY.md is derived from the same dict,
so the two can never disagree.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import secrets


def report_json_text(report: dict) -> str:
    """Serialise a report deterministically (sorted keys, no timestamps)."""
    return json.dumps(report, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


def render_md(report: dict) -> str:
    """Render ``REPLAY.md`` from the same dict as the JSON report."""
    t = report["totals"]
    lines = [
        "# GhostReplay session report",
        "",
        f"Session: {report['session_id']}",
        f"Turns: {report['turn_count']}  |  Entries: {report['entry_count']}",
        f"Models: {', '.join(report['models']) or 'not recorded'}",
        "",
        "Token counts are estimates (GhostSlice method v2), not "
        "exact tokenizer counts. Provider-reported usage is listed "
        "separately and never blended with estimates.",
        "",
        f"Reported usage (from transcript): input "
        f"{report['reported_input_tokens']}, output "
        f"{report['reported_output_tokens']}",
        "",
        "## Totals (estimated)",
        "",
        f"- Sent (bundle sliced total): {t['sent_sliced_estimated_tokens']}",
        f"- Not referenced in transcript: {t['not_referenced_estimated_tokens']}",
        f"- Re-read waste: {t['reread_waste_estimated_tokens']}",
        f"- Estimated waste: {t['estimated_waste_tokens']} "
        f"({t['estimated_waste_percent_of_sent']}% of sent)",
        "",
    ]
    if report["bundle"] is None:
        lines += ["No GhostSlice bundle manifest was joined, so "
                  "sent-vs-referenced, re-read cost, and mode "
                  "friction are unavailable for this session. "
                  "Pass --bundle or place a bundle at "
                  ".claude_context/ in the project.", ""]
    lines += ["## Not referenced in transcript", ""]
    lines.append("Qualifier: this means the transcript contains no "
                 "reference to the file. It does NOT prove the file "
                 "was not needed; transcripts can omit silent reads.")
    lines.append("")
    if report["not_referenced_in_transcript"]:
        lines.append("| File | Mode | Sliced tokens (est.) |")
        lines.append("|---|---|---|")
        for f in report["not_referenced_in_transcript"]:
            lines.append(f"| {f['path']} | {f['mode']} | {f['sliced_tokens']} |")
    else:
        lines.append("None.")
    lines += ["", "## Re-reads", ""]
    if report["rereads"]:
        lines.append("| File | Distinct turns | Extra reads | Re-read tokens (est.) |")
        lines.append("|---|---|---|---|")
        for r in report["rereads"]:
            lines.append(f"| {r['path']} | {r['distinct_turns']} | "
                         f"{r['extra_reads']} | {r['estimated_reread_tokens']} |")
    else:
        lines.append("None.")
    if report.get("turn_timeline"):
        lines += ["", "## Turn timeline", "",
                  "One row per turn. Re-read tokens are charged "
                  "only when a turn names a file as a tool input "
                  "that an earlier turn already named; they sum to "
                  "the re-read waste total above.", ""]
        lines.append("| Turn | Direct reads | Edits | Re-read files | "
                     "Re-read tokens (est.) | Cumulative (est.) |")
        lines.append("|---|---|---|---|---|---|")
        for row in report["turn_timeline"]:
            lines.append(
                f"| {row['turn']} | "
                f"{', '.join(row['direct_read_files']) or '-'} | "
                f"{', '.join(row['edited_files']) or '-'} | "
                f"{', '.join(row['reread_files']) or '-'} | "
                f"{row['reread_estimated_tokens']} | "
                f"{row['cumulative_reread_estimated_tokens']} |")
    lines += ["", "## Mode friction", "",
              "Files sent in a non-full mode that the session later "
              "pulled in directly with a Read (the agent asking for "
              "the body it was not given).", ""]
    if report["mode_friction"]["files"]:
        lines.append("| File | Sent as | Direct-read turns |")
        lines.append("|---|---|---|")
        for f in report["mode_friction"]["files"]:
            lines.append(f"| {f['path']} | {f['mode']} | "
                         f"{', '.join(str(x) for x in f['direct_read_turns'])} |")
        if report["mode_friction"]["symbols"]:
            lines += ["", "Symbols mentioned in a direct-read turn:", ""]
            for s in report["mode_friction"]["symbols"]:
                lines.append(f"- {s['path']}: {s['symbol']} "
                             f"(sent as {s['mode']}, turns "
                             f"{', '.join(str(x) for x in s['turns'])})")
    else:
        lines.append("None.")
    lines += ["", "## Rule repetition (GhostRecall candidates)", "",
              "Near-duplicate user instruction blocks (3-line "
              "shingles, Jaccard >= 0.85). Fingerprints only; the "
              "text itself is never quoted here.", ""]
    if report["rule_repetition"]:
        lines.append("| Fingerprint | Lines | Tokens each (est.) | Occurrences | Sessions |")
        lines.append("|---|---|---|---|---|")
        for c in report["rule_repetition"]:
            lines.append(f"| {c['fingerprint']} | {c['line_count']} | "
                         f"{c['estimated_tokens_each']} | {c['occurrences']} | "
                         f"{', '.join(c['sessions'])} |")
    else:
        lines.append("None.")
    lines += ["", "## Secret-shaped findings in the transcript", "",
              "Recorded as source + line + type only; values are "
              "never quoted.", ""]
    if report["secret_findings"]:
        for f in report["secret_findings"]:
            lines.append(f"- {f['source']} line {f['line']}: {f['type']}")
    else:
        lines.append("None.")
    lines += ["", "## Qualifiers", ""]
    for q in report["qualifiers"]:
        lines.append(f"- {q}")
    lines.append("")
    return secrets.sanitize("\n".join(lines))


def write_reports(report: dict, out_dir: str | Path) -> tuple[Path, Path]:
    """Write ``replay-report.json`` + ``REPLAY.md``; return ``(json, md)``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "replay-report.json"
    md_path = out_dir / "REPLAY.md"
    json_path.write_text(report_json_text(report), encoding="utf-8")
    md_path.write_text(render_md(report), encoding="utf-8")
    return json_path, md_path
