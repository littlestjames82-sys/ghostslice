"""Report writers: BENCH.md + bench-report.json, and compare mode.

A valid Bench report (PLAN.md) always carries: corpus version,
Slice version, estimator version, price table date, per-task rows,
and ALL failures. A summary percentage with no per-task rows is not
a valid Bench report, so the writer refuses a report with no rows.
"""
from __future__ import annotations

import json
import os


def write_json_report(report: dict, path: str) -> str:
    """Write ``report`` as ``bench-report.json`` (sorted keys). Returns ``path``."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def _fmt(value, suffix=""):
    return "-" if value is None else f"{value}{suffix}"


#: Plain-words rendering of the evidence contract's
#: verification_level enum, so the first screen of BENCH.md cannot
#: be skim-read as stronger evidence than it is.
_LEVEL_WORDS = {
    "static-analysis": "static analysis only (no tests executed, "
                       "no live agent run)",
    "tests-executed": "tests executed in the contained runner "
                      "(no live agent run)",
    "live-agent": "live agent run (a real agent attempted the tasks)",
    "none": "no usable evidence (nothing was measured)",
}


def _level_words(level) -> str:
    return _LEVEL_WORDS.get(level, "not recorded (pre-contract report)")


def render_bench_md(report: dict) -> str:
    """Render a report dict as the human ``BENCH.md`` text.

    Raises ``ValueError`` for a report with no per-task rows: a
    summary with no rows is not a valid Bench report.
    """
    if not report.get("tasks"):
        raise ValueError("a Bench report with no per-task rows is not "
                         "a valid report (PLAN.md section 4)")
    t = report["totals"]
    lines = []
    if report.get("sample"):
        lines.append("# *** SAMPLE REPORT - NOT A REAL RUN ***")
        lines.append("")
        lines.append("This is sample material shipped with GhostBench "
                     "to show the report shape. It is not evidence "
                     "from a real bench run.")
        if report.get("sample_note"):
            lines.append(f"Sample note: {report['sample_note']}")
        lines.append("")
    lines.append(f"# GhostBench Report - {report['corpus']['name']}")
    lines.append("")
    lines.append(f"- Run: {report['run_id']}")
    lines.append(f"- Tier: {report['tier']} | Suite: {report['suite']}")
    level = report.get("verification_level")
    lines.append(f"- Verification level: {_fmt(level)} - "
                 f"{_level_words(level)}")
    if "budget_cap" in report:
        cap = report.get("budget_cap")
        if cap is None:
            lines.append("- Budget cap: none set (this live run "
                         "was not budget-gated)")
        else:
            line = (f"- Budget cap: {cap} tokens | Estimated run "
                    f"context: {_fmt(report.get('budget_estimate'))} "
                    "tokens (Bench's token-estimator estimate of "
                    "the run's context size; NOT the agent's billed "
                    "cost, which Bench does not meter)")
            if report.get("budget_confirmed") \
                    and (report.get("budget_estimate") or 0) > cap:
                line += (" | Cap exceeded - run proceeded under "
                         "--confirm")
            lines.append(line)
    lines.append(f"- Tool: ghostbench {report['tool_version']}")
    lines.append(f"- Corpus: {report['corpus']['name']} "
                 f"v{report['corpus']['version']}")
    if report["subset"]["labelled"]:
        lines.append(f"- SUBSET RUN (labelled): tasks "
                     f"{', '.join(report['subset']['task_ids'])}")
    lines.append(f"- GhostSlice version: {_fmt(report.get('slice_version'))}")
    lines.append(f"- Estimator: {report['estimator_version']} "
                 f"(source: {report['estimator_source']})")
    lines.append(f"- Price table date: {_fmt(report.get('price_table_date'))} "
                 "(estimates only, never billed amounts)")
    lines.append(f"- Tests run: {report['run_tests']}")
    lines.append("")
    lines.append("## Honest scope")
    lines.append("")
    lines.append(f"- Measured: {report['honest_scope']['tier']}, "
                 f"{report['honest_scope']['tasks_measured']} task(s).")
    for item in report["honest_scope"]["what_was_not_measured"]:
        lines.append(f"- Not measured: {item}")
    lines.append("")
    sandbox = report.get("sandbox")
    if sandbox:
        lines.append("## Test execution containment")
        lines.append("")
        lines.append("Task tests ran in the contained runner. It "
                     "enforces:")
        for item in sandbox.get("enforced") or []:
            lines.append(f"- Enforced: {item}")
        lines.append("It does NOT enforce:")
        for item in sandbox.get("not_enforced") or []:
            lines.append(f"- Not enforced: {item}")
        lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append(f"- Full tokens (estimated): {t['full_tokens']}")
    for name, var in sorted(t["variants"].items()):
        lines.append(f"- {name}: {var['tokens']} tokens, "
                     f"saving vs full: {_fmt(var['saving_pct_vs_full'], '%')}, "
                     f"fit success rate: {_fmt(var['fit_success_rate'], '%')}"
                     + (f" (PARTIAL: tokens for "
                        f"{var.get('tasks_with_tokens')}/{t['tasks']} tasks)"
                        if var.get("partial") else ""))
    lines.append(f"- Tasks: {t['tasks']} (pass {t['pass']}, "
                 f"fail {t['fail']}, unknown {t['unknown']})")
    lines.append(f"- Hard gaps predicted (Verify): {t['hard_gaps_predicted']}")
    if t.get("expected_symbols"):
        lines.append(
            f"- Expected symbols found in expected files: "
            f"{t.get('symbols_found')}/{t['expected_symbols']} "
            f"({_fmt(t.get('symbol_coverage_pct'), '%')}), "
            f"tasks with missing symbols: "
            f"{t.get('tasks_with_missing_symbols')}")
    lines.append("")
    lines.append("## Per-task results")
    lines.append("")
    lines.append("| Project | Task | Status | Level | Full | Sliced | Saving % | "
                 "Hard gaps | Symbols | Patch files | Manifest (sliced) |")
    lines.append("|---|---|---|---|---:|---:|---:|---:|---|---|---|")
    for row in report["tasks"]:
        sliced = row["variants"].get("sliced", {})
        patch_files = ", ".join(
            (row.get("patch") or {}).get("files_touched") or []) or "-"
        symbols = row.get("symbols_score") or {}
        symbols_cell = (
            f"{len(symbols.get('found_in_expected_files') or [])}/"
            f"{len(symbols.get('expected_symbols') or [])}"
            if symbols.get("expected_symbols") else "-")
        lines.append(
            f"| {row['project']} | {row['task']} | {row['status']} | "
            f"{_fmt(row.get('verification_level'))} | "
            f"{row['full_tokens']} | {_fmt(sliced.get('tokens'))} | "
            f"{_fmt(sliced.get('saving_pct_vs_full'))} | "
            f"{row['hard_gaps_predicted']} | {symbols_cell} | {patch_files} | "
            f"{_fmt(sliced.get('manifest_sha256'))} |")
    lines.append("")
    lines.append("## Failures (all shown)")
    lines.append("")
    if report["failures_visible"]:
        for entry in report["failures_visible"]:
            for failure in entry["failures"]:
                lines.append(f"- {entry['project']}/{entry['task']}: {failure}")
    else:
        lines.append("- None recorded in this run.")
    lines.append("")
    lines.append("## Traceability")
    lines.append("")
    lines.append("- Every token number comes from the estimator stamped "
                 "above or from a bundle manifest whose sha256 is in "
                 "bench-report.json for the same run.")
    lines.append("- Reported (provider) token figures are never blended "
                 "with estimates; Tier A has no reported figures.")
    lines.append("")
    return "\n".join(lines)


def write_bench_md(report: dict, path: str) -> str:
    """Write :func:`render_bench_md` output to ``path``. Returns ``path``."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_bench_md(report))
    return path


def _require_report_shape(rep, label: str) -> None:
    if not isinstance(rep, dict):
        raise ValueError(f"{label} is not a bench report (not a JSON object)")
    for key in ("run_id", "corpus", "estimator_version", "totals", "tasks"):
        if key not in rep:
            raise ValueError(f"{label} is not a bench report (missing {key!r})")
    if not isinstance(rep["tasks"], list) or not isinstance(rep["totals"], dict):
        raise ValueError(f"{label} is not a bench report (bad totals/tasks)")
    for key in ("full_tokens", "pass", "fail"):
        if key not in rep["totals"]:
            raise ValueError(
                f"{label} is not a bench report (totals missing {key!r})")


def compare_reports(a: dict, b: dict) -> dict:
    """Per-task and total deltas between two run reports (b - a)."""
    _require_report_shape(a, "run A")
    _require_report_shape(b, "run B")
    def by_key(rep):
        out = {}
        for r in rep["tasks"]:
            if not isinstance(r, dict) or "project" not in r or "task" not in r:
                raise ValueError("bench report task row missing project/task")
            out[(r["project"], r["task"])] = r
        return out
    ka, kb = by_key(a), by_key(b)
    rows = []
    for key in sorted(set(ka) | set(kb)):
        ra, rb = ka.get(key), kb.get(key)
        def sliced(rep):
            return (rep["variants"].get("sliced", {}).get("tokens")
                    if rep else None)
        rows.append({
            "project": key[0], "task": key[1],
            "status_a": ra["status"] if ra else None,
            "status_b": rb["status"] if rb else None,
            "full_tokens_a": ra["full_tokens"] if ra else None,
            "full_tokens_b": rb["full_tokens"] if rb else None,
            "sliced_tokens_a": sliced(ra), "sliced_tokens_b": sliced(rb),
            "sliced_delta": (
                sliced(rb) - sliced(ra)
                if sliced(ra) is not None and sliced(rb) is not None else None),
        })
    return {
        "tool": "ghostbench-compare",
        "run_a": a["run_id"], "run_b": b["run_id"],
        "corpus_a": a["corpus"], "corpus_b": b["corpus"],
        "estimator_a": a["estimator_version"],
        "estimator_b": b["estimator_version"],
        "estimator_mismatch_warning": (
            "estimator versions differ: totals are NOT directly comparable"
            if a["estimator_version"] != b["estimator_version"] else None),
        "totals": {
            "full_tokens_a": a["totals"]["full_tokens"],
            "full_tokens_b": b["totals"]["full_tokens"],
            "pass_a": a["totals"]["pass"], "pass_b": b["totals"]["pass"],
            "fail_a": a["totals"]["fail"], "fail_b": b["totals"]["fail"],
        },
        "tasks": rows,
    }


def render_compare_md(comp: dict) -> str:
    """Render a :func:`compare_reports` result as a Markdown table."""
    lines = ["# GhostBench Compare", "",
             f"- A: {comp['run_a']}", f"- B: {comp['run_b']}"]
    if comp["estimator_mismatch_warning"]:
        lines.append(f"- WARNING: {comp['estimator_mismatch_warning']}")
    lines += ["", "| Project | Task | Status A->B | Sliced A | Sliced B | Delta |",
              "|---|---|---|---:|---:|---:|"]
    for row in comp["tasks"]:
        lines.append(
            f"| {row['project']} | {row['task']} | "
            f"{_fmt(row['status_a'])}->{_fmt(row['status_b'])} | "
            f"{_fmt(row['sliced_tokens_a'])} | {_fmt(row['sliced_tokens_b'])} | "
            f"{_fmt(row['sliced_delta'])} |")
    lines.append("")
    return "\n".join(lines)
