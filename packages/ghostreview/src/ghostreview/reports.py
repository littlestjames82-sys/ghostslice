"""Report writers: review.json + REVIEW.md (plain English).

REVIEW.md is generated from the same report dict as review.json, so
the numbers a human reads are the numbers a machine consumes. The
prose is templates over counted facts; no sentence states a cause,
an intention, or a quality judgement the evidence does not support.
"""
from __future__ import annotations

import json
from pathlib import Path

_VERDICT_GLOSS = {
    "straightforward": "none of the review rules found anything that "
                       "needs a second look. That is not a promise "
                       "the change is safe, only that no rule fired.",
    "needs-a-look": "one or more medium-level flags below are worth a "
                    "careful look before this change is merged.",
    "needs-attention": "at least one high-level flag below needs a "
                       "decision before this change is merged.",
    "could-not-review": "the supplied change could not be read, so no "
                        "judgement was made at all.",
}

_STATUS_WORD = {"added": "new file", "modified": "modified",
                "deleted": "deleted", "renamed": "renamed",
                "copied": "copied from another file (the original stays)"}


def write_reports(report: dict, out_dir) -> tuple:
    """Write ``review.json`` and ``REVIEW.md`` to *out_dir*.

    Creates *out_dir* if needed and returns ``(json_path, md_path)``.
    Both files come from the same *report* dict, so their numbers agree.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "review.json"
    md_path = out / "REVIEW.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n",
                         encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def render_markdown(report: dict) -> str:
    """Render *report* as the plain-English ``REVIEW.md`` text.

    Sections: verdict (with a plain-words gloss), what changed,
    dependents affected, risks, Verify and Scope citations, notes,
    and honest limits. Missing optional reports are stated as
    missing, never implied to have run.
    """
    t = report.get("totals") or {}
    lines = [
        "# GhostReview",
        "",
        f"**Verdict: {report.get('verdict', 'unknown')}** "
        f"(exit {report.get('exit_code', '?')})",
        "",
        f"In plain words: {_VERDICT_GLOSS.get(report.get('verdict'), '')}",
        "",
        report.get("verdict_summary", ""),
        "",
        f"- Project: `{report.get('project', '')}`",
        f"- Diff source: `{report.get('diff_source', '')}`",
        f"- Files changed: {t.get('files_changed', 0)} "
        f"(+{t.get('additions', 0)} / -{t.get('deletions', 0)} lines)",
        f"- Note: {report.get('honesty', '')}.",
        "",
        "## What changed",
        "",
    ]
    changes = report.get("changes") or []
    if not changes:
        lines += ["Nothing. The supplied diff contained no file changes.", ""]
    for c in changes:
        sym = c.get("symbols") or {}
        lines.append(
            f"- `{c['path']}` ({_STATUS_WORD.get(c['status'], c['status'])}): "
            f"{c['additions']} line(s) added, {c['deletions']} line(s) "
            f"deleted in {c['hunks']} hunk(s)"
            + ("; binary file, contents not reviewable from a diff"
               if c.get("is_binary") else "")
            + (f"; file mode changed from {c['old_mode']} to "
               f"{c['new_mode']} (for example, whether the file can "
               "be run as a program)"
               if c.get("mode_changed") else "") + ".")
        if sym.get("touched"):
            lines.append(
                f"  Symbols touched ({sym.get('method')}): "
                + ", ".join(f"`{s}`" for s in sym["touched"]) + ".")
    lines += ["", "## Dependents affected", ""]
    deps = report.get("dependents") or {}
    any_dep = False
    for path in sorted(deps):
        lst = deps[path].get("dependents") or []
        if lst:
            any_dep = True
            lines.append(f"- `{path}` is imported by: "
                         + ", ".join(f"`{d}`" for d in lst) + ".")
    if not any_dep:
        lines.append("No project file outside this diff was found to "
                     "import a changed file. This is a one-hop import "
                     "scan only; it is not a complete blast radius "
                     "(GhostScope builds that).")
    lines += ["", "## Risks", ""]
    risks = report.get("risks") or []
    if not risks:
        lines.append("No risks were flagged by the GhostReview rules "
                     "(test edits, config and dependency changes, "
                     "secret-shaped paths or lines, large deletions, "
                     "removed symbols, binary files).")
    for r in risks:
        loc = f":{r['line']}" if r.get("line") else ""
        lines.append(f"- [{r['level']}] {r['rule']} in `{r['file']}{loc}`: "
                     f"{r['detail']}.")
    lines += ["", "## Verify and Scope", ""]
    verify = report.get("verify") or {}
    if verify.get("present"):
        lines.append(
            f"- GhostVerify report was provided (`{verify.get('path')}`): "
            f"verdict {verify.get('verdict')}, exit "
            f"{verify.get('exit_code')}, {verify.get('hard_gaps')} hard "
            f"gap(s), {verify.get('soft_gaps')} soft gap(s)"
            + (f"; post patch verdict {verify.get('post_verdict')}, tests "
               f"{verify.get('post_tests_status')}."
               if verify.get("post_verdict") else "."))
    else:
        lines.append("- No GhostVerify report was provided. No Verify "
                     "check ran as part of this review.")
    scope = report.get("scope") or {}
    if scope.get("present"):
        lines.append(f"- GhostScope pack was provided (`{scope.get('path')}`).")
        if scope.get("pack_files") is not None \
                or scope.get("pack_tokens_estimate") is not None:
            bits = []
            if scope.get("pack_files") is not None:
                bits.append(f"{scope['pack_files']} file(s) in the pack")
            if scope.get("pack_tokens_estimate") is not None:
                bits.append(f"{scope['pack_tokens_estimate']} pack tokens "
                            "estimated by GhostScope")
            lines.append("  Pack size as recorded: " + ", ".join(bits) + ".")
        by_file = scope.get("risk_reasons_by_file") or {}
        if by_file:
            for fpath in sorted(by_file):
                for reason in by_file[fpath]:
                    lines.append(f"  Scope risk reason for `{fpath}`: "
                                 f"{reason}.")
        else:
            for reason in scope.get("risk_reasons") or []:
                lines.append(f"  Scope risk reason: {reason}.")
        if not (scope.get("risk_reasons") or []):
            lines.append("  The pack recorded no risk reasons in scope.json.")
        rec = scope.get("reconciliation") or {}
        if rec:
            if rec.get("scope_files_recorded"):
                lines.append(
                    f"  Scope reconciliation: {len(rec.get('matched') or [])} "
                    "file(s) appear in both the pack's changed-file list "
                    "and this diff"
                    + (f"; listed only in the pack: "
                       + ", ".join(f"`{p}`" for p in rec["only_in_scope"])
                       if rec.get("only_in_scope") else "")
                    + (f"; in this diff only: "
                       + ", ".join(f"`{p}`" for p in rec["only_in_diff"])
                       if rec.get("only_in_diff") else "")
                    + ". This compares the two supplied lists only; "
                      "it is not a risk flag.")
            else:
                lines.append("  The pack recorded no changed-file list, "
                             "so no file-by-file comparison with this "
                             "diff was made.")
        order = scope.get("reading_order") or []
        if order:
            lines.append("  Scope reading order: " + ", ".join(
                f"{e.get('order')}. `{e.get('path')}`"
                + (f" ({e['mode']})" if e.get("mode") else "")
                for e in order) + ".")
        detail_paths = sorted(
            set(scope.get("changed_symbols_by_file") or {})
            | set(scope.get("covering_tests_by_file") or {})
            | set(scope.get("direct_callers_by_file") or {}))
        for fpath in detail_paths:
            bits = []
            syms = (scope.get("changed_symbols_by_file") or {}).get(fpath)
            if syms:
                bits.append("changed symbols recorded: "
                            + ", ".join(f"`{s}`" for s in syms))
            if fpath in (scope.get("covering_tests_by_file") or {}):
                tests = scope["covering_tests_by_file"][fpath]
                bits.append("covering tests recorded: "
                            + (", ".join(f"`{t}`" for t in tests)
                               if tests else "none"))
            callers = (scope.get("direct_callers_by_file") or {}).get(fpath)
            if callers is not None:
                bits.append(f"direct callers recorded: {callers}")
            if bits:
                lines.append(f"  Scope detail for `{fpath}`: "
                             + "; ".join(bits) + ".")
    else:
        lines.append("- No GhostScope pack was provided. This review is "
                     "written from the diff alone; GhostScope builds the "
                     "change-centred reading pack.")
    notes = report.get("notes") or []
    if notes:
        lines += ["", "## Notes", ""]
        lines += [f"- {n}" for n in notes]
    lines += ["", "## Honest limits", "",
              "- Symbol detection is exact for Python (ast) and "
              "line-pattern based for other languages; a change inside a "
              "long function in another language may be attributed to no "
              "symbol.",
              "- Dependents come from a one-hop import scan. Dynamic, "
              "runtime, and string-based references are not found.",
              "- This review states what changed and what the rules "
              "flagged. It does not say why the change was made, does not "
              "judge quality, and does not approve or merge anything.",
              ""]
    return "\n".join(lines)
