"""Compare mode and scoring-rule tests.

Core contract: `ghostbench compare <run-a.json> <run-b.json> [--out FILE]`
takes two bench-report.json FILES; a .md --out writes the compare table,
a .json --out writes the compare object.
"""

from conftest import EXAMPLES, load_json, requires_core, run_cli

RUN_A = EXAMPLES / "runs" / "sample-tier-a-run-a" / "bench-report.json"
RUN_B = EXAMPLES / "runs" / "sample-tier-a-run-b" / "bench-report.json"


def test_sample_pair_really_differs_for_compare_to_measure():
    a, b = load_json(RUN_A), load_json(RUN_B)
    rows_a = {r["task"]: r for r in a["tasks"]}
    rows_b = {r["task"]: r for r in b["tasks"]}
    assert set(rows_a) == set(rows_b)
    delta = (rows_b["adv-001-fix-missing-route"]["variants"]["sliced"]["tokens"]
             - rows_a["adv-001-fix-missing-route"]["variants"]["sliced"]["tokens"])
    assert delta == -100, "sample pair drifted: compare expects a -100 sliced delta"


@requires_core
def test_compare_reports_per_task_deltas(tmp_path):
    out = tmp_path / "COMPARE.md"
    proc = run_cli(["compare", RUN_A, RUN_B, "--out", out])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = out.read_text()
    assert "adv-001-fix-missing-route" in text
    assert "-100" in text, "compare did not report the -100 sliced-token delta"


@requires_core
def test_compare_json_out_carries_the_same_delta(tmp_path):
    out = tmp_path / "compare.json"
    proc = run_cli(["compare", RUN_A, RUN_B, "--out", out])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    comp = load_json(out)
    row = [r for r in comp["tasks"] if r["task"] == "adv-001-fix-missing-route"]
    assert row and row[0]["sliced_delta"] == -100
    assert comp["estimator_mismatch_warning"] is None


def test_files_touched_is_informational_in_the_sample_format():
    """Scoring rule (PLAN): files-touched is informational, extra files
    are not auto-failures. The sample rows carry the core's
    files_touched_score with informational_only set, and a passing row
    records no failures."""
    report = load_json(RUN_A)
    for row in report["tasks"]:
        assert row["files_touched_score"]["informational_only"] is True
        if row["status"] == "pass":
            assert row["failures"] == []
