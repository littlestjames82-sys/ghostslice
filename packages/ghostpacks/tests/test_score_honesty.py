"""Score honesty tests (PLAN.md Verification bar: Score honesty test).

An unscored pack must be labelled unscored wherever it is shown, and a
pack that claims a Bench score without the Bench report file to back
it must fail lint. No silent cherry-picking.
"""
from __future__ import annotations

from conftest import combined, lint, show

SCORED_BENCH = {"score": 42.0, "report": "bench-report.json"}


def test_unscored_pack_show_labels_unscored(pack_factory):
    pack = pack_factory()  # no bench section at all
    proc = show(pack)
    assert proc.returncode == 0, combined(proc)
    assert "unscored" in proc.stdout.lower(), (
        f"`show` on an unscored pack must print 'unscored':\n{proc.stdout}")


def test_unscored_pack_passes_lint(pack_factory):
    # Unscored is a label, not an error: the pack is usable, it just
    # may not claim a number.
    pack = pack_factory()
    proc = lint(pack)
    assert proc.returncode == 0, combined(proc)


def test_scored_pack_with_bench_report_passes_lint(pack_factory):
    pack = pack_factory(bench=SCORED_BENCH, write_bench_report=True)
    proc = lint(pack)
    assert proc.returncode == 0, combined(proc)


def test_scored_pack_show_displays_its_score(pack_factory):
    pack = pack_factory(bench=SCORED_BENCH, write_bench_report=True)
    proc = show(pack)
    assert proc.returncode == 0, combined(proc)
    assert "42" in proc.stdout, (
        f"`show` on a scored pack should display the claimed score:\n{proc.stdout}")
    assert "unscored" not in proc.stdout.lower()


def test_claimed_score_without_bench_report_file_fails_lint(pack_factory):
    # Manifest names a report file that is not in the pack folder.
    pack = pack_factory(bench=SCORED_BENCH, write_bench_report=False)
    proc = lint(pack)
    out = combined(proc)
    assert proc.returncode != 0, (
        "lint accepted a claimed Bench score with no report file in the pack")
    assert "bench" in out.lower(), f"failure should mention the Bench report:\n{out}"


def test_claimed_score_without_any_report_reference_fails_lint(pack_factory):
    # A bare number with no report reference at all is still a claim.
    pack = pack_factory(bench={"score": 42.0})
    proc = lint(pack)
    out = combined(proc)
    assert proc.returncode != 0, (
        "lint accepted a Bench score claim with no report reference")
    assert "bench" in out.lower(), f"failure should mention the Bench report:\n{out}"
