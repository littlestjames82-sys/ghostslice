"""Bench report *content* verification tests (DEEPEN lane).

Before this change, lint only checked that a file with the report's
name existed in the pack folder: an empty file, a report for a
different score, or a path pointing outside the pack all backed a
claimed score. These tests pin the stronger rule: lint opens the
report, the report's own score must equal the claimed score, it must
name the reference project it measured, and it must actually live
inside the pack folder. Unscored packs are untouched by all of this.
"""
from __future__ import annotations

import json
from pathlib import Path

from conftest import combined, lint, show

SCORED_BENCH = {"score": 42.0, "report": "bench-report.json"}

GOOD_REPORT = {
    "tool": "ghostbench",
    "tier": "A",
    "reference_project": "fixture-project",
    "score": 42.0,
    "savings_percent": 42.0,
}


def _overwrite_report(pack: Path, content, name="bench-report.json"):
    target = pack / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        target.write_text(content)
    else:
        target.write_text(json.dumps(content, indent=2) + "\n")
    return target


def test_matching_report_still_passes_lint(pack_factory):
    pack = pack_factory(bench=SCORED_BENCH, write_bench_report=True)
    proc = lint(pack)
    assert proc.returncode == 0, combined(proc)


def test_report_score_mismatch_fails_lint(pack_factory):
    pack = pack_factory(bench=SCORED_BENCH, write_bench_report=True)
    _overwrite_report(pack, {**GOOD_REPORT, "score": 99.0})
    proc = lint(pack)
    out = combined(proc)
    assert proc.returncode != 0, "lint accepted a report for a different score"
    assert "does not match" in out, out
    assert "42" in out and "99" in out, out


def test_report_without_score_field_fails_lint(pack_factory):
    pack = pack_factory(bench=SCORED_BENCH, write_bench_report=True)
    report = {k: v for k, v in GOOD_REPORT.items() if k != "score"}
    _overwrite_report(pack, report)
    proc = lint(pack)
    out = combined(proc)
    assert proc.returncode != 0
    assert "no" in out.lower() and "score" in out.lower(), out


def test_report_without_reference_project_fails_lint(pack_factory):
    pack = pack_factory(bench=SCORED_BENCH, write_bench_report=True)
    report = {k: v for k, v in GOOD_REPORT.items()
              if k != "reference_project"}
    _overwrite_report(pack, report)
    proc = lint(pack)
    out = combined(proc)
    assert proc.returncode != 0, (
        "a score with no stated reference project is uncheckable and "
        "must not pass lint")
    assert "reference_project" in out, out


def test_report_that_is_not_json_fails_lint(pack_factory):
    pack = pack_factory(bench=SCORED_BENCH, write_bench_report=True)
    _overwrite_report(pack, "score: definitely 42, trust me\n")
    proc = lint(pack)
    assert proc.returncode != 0
    assert "bench" in combined(proc).lower()


def test_report_that_is_not_a_json_object_fails_lint(pack_factory):
    pack = pack_factory(bench=SCORED_BENCH, write_bench_report=True)
    _overwrite_report(pack, [42.0, "fixture-project"])
    proc = lint(pack)
    assert proc.returncode != 0
    assert "object" in combined(proc), combined(proc)


def test_empty_report_file_no_longer_backs_a_score(pack_factory):
    # The pre-change behaviour this lane removes: an empty file with
    # the right name used to satisfy the honesty rule.
    pack = pack_factory(bench=SCORED_BENCH, write_bench_report=True)
    _overwrite_report(pack, "")
    proc = lint(pack)
    assert proc.returncode != 0


def test_non_numeric_claimed_score_fails_lint(pack_factory):
    pack = pack_factory(bench={"score": "42", "report": "bench-report.json"},
                        write_bench_report=True)
    proc = lint(pack)
    out = combined(proc)
    assert proc.returncode != 0, "a string is not a Bench score"
    assert "finite number" in out or "does not match" in out, out


def test_out_of_range_savings_percent_fails_lint(pack_factory):
    pack = pack_factory(bench=SCORED_BENCH, write_bench_report=True)
    _overwrite_report(pack, {**GOOD_REPORT, "savings_percent": 142.0})
    proc = lint(pack)
    assert proc.returncode != 0
    assert "savings_percent" in combined(proc)


def test_report_outside_pack_via_dotdot_fails_lint(pack_factory, tmp_path):
    # A perfectly good report that lives OUTSIDE the pack must not
    # back the claim: the pack would change meaning with its folder.
    outside = tmp_path / "outside-report.json"
    outside.write_text(json.dumps(GOOD_REPORT, indent=2) + "\n")
    pack = pack_factory(
        bench={"score": 42.0, "report": "../../outside-report.json"})
    proc = lint(pack)
    out = combined(proc)
    assert proc.returncode != 0, (
        "lint let a pack borrow a Bench report from outside its folder")
    assert "outside" in out, out


def test_report_symlinked_from_outside_pack_fails_lint(pack_factory, tmp_path):
    outside = tmp_path / "outside-report.json"
    outside.write_text(json.dumps(GOOD_REPORT, indent=2) + "\n")
    pack = pack_factory(bench=SCORED_BENCH)
    (pack / "bench-report.json").symlink_to(outside)
    proc = lint(pack)
    out = combined(proc)
    assert proc.returncode != 0, (
        "lint let a symlink borrow a Bench report from outside the pack")
    assert "outside" in out, out


def test_report_in_subfolder_inside_pack_passes_lint(pack_factory):
    pack = pack_factory(
        bench={"score": 42.0, "report": "reports/bench.json"})
    _overwrite_report(pack, GOOD_REPORT, name="reports/bench.json")
    proc = lint(pack)
    assert proc.returncode == 0, combined(proc)


def test_report_with_int_score_equal_to_float_claim_passes(pack_factory):
    pack = pack_factory(bench=SCORED_BENCH, write_bench_report=True)
    _overwrite_report(pack, {**GOOD_REPORT, "score": 42})
    proc = lint(pack)
    assert proc.returncode == 0, combined(proc)


def test_mismatched_pack_is_not_shown_as_scored(pack_factory):
    pack = pack_factory(bench=SCORED_BENCH, write_bench_report=True)
    _overwrite_report(pack, {**GOOD_REPORT, "score": 7.0})
    proc = show(pack)
    assert proc.returncode != 0, (
        "show presented a pack as usable/scored when its Bench report "
        "does not back the claimed score")
    assert "(kind: context, scored)" not in proc.stdout


def test_unscored_pack_with_no_report_still_passes_lint(pack_factory):
    pack = pack_factory()  # no bench section at all
    proc = lint(pack)
    assert proc.returncode == 0, combined(proc)
    assert "unscored" in show(pack).stdout.lower()
