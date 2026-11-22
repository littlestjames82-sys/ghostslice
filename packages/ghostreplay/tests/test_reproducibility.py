"""Reproducibility contract test (PLAN verification bar).

Same transcript + same bundle manifest -> identical report totals on a
re-run. Compares the totals of two independent analyse runs (the whole
file may carry a timestamp; the totals must not drift).
"""
import json

from conftest import BUNDLE, SESSIONS, load_report, run_cli


def _totals(report):
    for key in ("totals", "summary", "total"):
        if isinstance(report.get(key), dict):
            return report[key]
    # Fall back: every top-level int field is a total for this purpose.
    return {k: v for k, v in report.items() if isinstance(v, int)}


def test_analyse_totals_are_reproducible(tmp_path, require_core, project_copy):
    reports = []
    for i in (1, 2):
        out = tmp_path / f"run{i}"
        res = run_cli(
            ["analyse", project_copy, SESSIONS / "planted_waste_1.jsonl",
             "--bundle", BUNDLE, "--out", out],
            cwd=tmp_path,
        )
        assert res.returncode == 0, f"run {i} failed: {res.stdout}\n{res.stderr}"
        reports.append(load_report(out))
    assert _totals(reports[0]), "report carries no totals to compare"
    assert _totals(reports[0]) == _totals(reports[1]), (
        "totals drifted between identical runs:\n"
        + json.dumps(_totals(reports[0]), sort_keys=True)
        + "\nvs\n"
        + json.dumps(_totals(reports[1]), sort_keys=True)
    )
