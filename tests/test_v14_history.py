"""G9 (v0.14) history analytics: trend, $ saved, ASCII charts,
estimator stamping/mix warnings, corrupt-line tolerance, the HTML
report's embedded savings chart, and the /api/history payload shape.

Fixture ledgers are written line by line with known numbers so every
aggregate is asserted exactly.
"""
from __future__ import annotations

import io
import json
import time
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from ghostslice.cli import main
from ghostslice.ledger import (analytics, append_record, read_records,
                               sparkline, summary)
from ghostslice.report import build_report
from ghostslice.server import make_server

# Three runs with hand-computable analytics:
#   run1: 1000 -> 600  saved 400 (40%)
#   run2: 1200 -> 600  saved 600 (50%)   after delta 0
#   run3:  900 -> 450  saved 450 (50%)   after delta -150
# totals: before 3100, after 1650, saved 1450; mean pct 46.67, median 50
RUNS = [
    {"at": "2026-10-01T10:00:00+00:00", "kind": "export", "bundle": "b1",
     "before_tokens": 1000, "after_tokens": 600, "saved_tokens": 400,
     "estimator": "v2"},
    {"at": "2026-10-08T10:00:00+00:00", "kind": "export", "bundle": "b2",
     "before_tokens": 1200, "after_tokens": 600, "saved_tokens": 600,
     "estimator": "v2"},
    {"at": "2026-10-15T10:00:00+00:00", "kind": "export", "bundle": "b3",
     "before_tokens": 900, "after_tokens": 450, "saved_tokens": 450,
     "estimator": "v2"},
]

MODEL = {"id": "fixture", "name": "Fixture Model",
         "input_per_mtok_usd": 2.0, "output_per_mtok_usd": 99.0}
PRICES = {"as_of": "2026-01-01", "models": [MODEL]}


def write_ledger(root: Path, records) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".ghostslice-history.jsonl"
    lines = [r if isinstance(r, str) else json.dumps(r) for r in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


@pytest.fixture()
def project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    return root


# ---------------------------------------------------------------- ledger

def test_append_record_stamps_current_estimator(tmp_path):
    append_record(tmp_path, "export", 100, 40, bundle="b")
    recs = read_records(tmp_path)
    assert len(recs) == 1
    assert recs[0]["estimator"] == "v2"
    assert recs[0]["saved_tokens"] == 60


def test_analytics_exact_aggregates(project):
    write_ledger(project, RUNS)
    data = analytics(project, model=MODEL, prices=PRICES)
    assert data["runs"] == 3
    assert data["total_before_tokens"] == 3100
    assert data["total_after_tokens"] == 1650
    assert data["total_saved_tokens"] == 1450
    agg = data["aggregates"]
    assert agg["mean_saved_pct"] == 46.67
    assert agg["median_saved_pct"] == 50.0
    assert agg["best_run"]["index"] == 1
    assert agg["best_run"]["saved_tokens"] == 600
    assert agg["worst_run"]["index"] == 0
    assert agg["worst_run"]["saved_tokens"] == 400
    assert agg["first_after_tokens"] == 600
    assert agg["last_after_tokens"] == 450
    assert agg["after_change_tokens"] == -150
    assert agg["after_change_pct"] == -25.0
    assert agg["span_days"] == 14.0
    assert agg["runs_per_week"] == 1.5


def test_analytics_run_deltas_and_cumulative(project):
    write_ledger(project, RUNS)
    detail = analytics(project)["runs_detail"]
    assert [r["delta_after_tokens"] for r in detail] == [None, 0, -150]
    assert [r["cumulative_saved_tokens"] for r in detail] == [400, 1000, 1450]
    assert [r["saved_pct"] for r in detail] == [40.0, 50.0, 50.0]


def test_dollar_math_uses_input_rate_not_output(project):
    write_ledger(project, RUNS)
    data = analytics(project, model=MODEL, prices=PRICES)
    # input rate is 2.0 ($/Mtok); output rate is 99.0 and must NOT appear
    assert data["runs_detail"][0]["saved_cost_usd"] == round(400 * 2.0 / 1e6, 4)
    assert data["aggregates"]["total_saved_cost_usd"] == round(1450 * 2.0 / 1e6, 4)
    assert data["aggregates"]["total_saved_cost_usd"] != round(1450 * 99.0 / 1e6, 4)
    assert data["model"]["prices_as_of"] == "2026-01-01"
    cum = [r["cumulative_saved_cost_usd"] for r in data["runs_detail"]]
    assert cum == sorted(cum)


def test_no_model_no_dollar_fields(project):
    write_ledger(project, RUNS)
    data = analytics(project)
    assert "model" not in data
    assert "saved_cost_usd" not in data["runs_detail"][0]
    assert "cumulative_saved_cost_usd" not in data["runs_detail"][0]
    assert "total_saved_cost_usd" not in data["aggregates"]


def test_cumulative_cost_equals_total_exactly(project):
    # Per-run values chosen so display-rounding each run and summing
    # would drift from the total (G09 F1): 333 * $3/Mtok = $0.000999.
    recs = [{"at": f"2026-10-0{i + 1}T10:00:00+00:00", "kind": "export",
             "bundle": None, "before_tokens": 1000, "after_tokens": 667,
             "saved_tokens": 333, "estimator": "v2"} for i in range(3)]
    write_ledger(project, recs)
    model = {"id": "m", "name": "M", "input_per_mtok_usd": 3.0,
             "output_per_mtok_usd": 3.0}
    data = analytics(project, model=model, prices={"as_of": "x"})
    last_cum = data["runs_detail"][-1]["cumulative_saved_cost_usd"]
    assert last_cum == data["aggregates"]["total_saved_cost_usd"]


def test_runs_per_week_needs_a_day_span(project):
    soon = [dict(RUNS[0]), dict(RUNS[1], at="2026-10-01T10:20:00+00:00")]
    write_ledger(project, soon)
    agg = analytics(project)["aggregates"]
    assert agg["span_days"] is not None and agg["span_days"] < 1
    assert agg["runs_per_week"] is None


def test_estimator_mix_warning(project):
    mixed = [dict(RUNS[0]), {k: v for k, v in RUNS[1].items() if k != "estimator"},
             dict(RUNS[2], estimator="v1")]
    write_ledger(project, mixed)
    mix = analytics(project)["estimator"]
    assert mix["mixed"] is True
    assert mix["unstamped_records"] == 1
    assert mix["stamped_versions"] == ["v1", "v2"]
    assert "not directly comparable" in mix["warning"]


def test_estimator_uniform_stamped_no_warning(project):
    write_ledger(project, RUNS)
    mix = analytics(project)["estimator"]
    assert mix["mixed"] is False
    assert mix["warning"] is None


def test_estimator_all_unstamped_warns(project):
    old = [{k: v for k, v in r.items() if k != "estimator"} for r in RUNS]
    write_ledger(project, old)
    mix = analytics(project)["estimator"]
    assert mix["mixed"] is True
    assert mix["unstamped_records"] == 3
    assert "predate estimator stamping" in mix["warning"]


def test_corrupt_lines_counted_and_skipped(project):
    lines = [json.dumps(RUNS[0]), "{not json", "42", "[1,2]",
             json.dumps({"at": "x", "before_tokens": "abc", "after_tokens": 5}),
             "", json.dumps(RUNS[1])]
    write_ledger(project, lines)
    data = analytics(project)
    assert data["corrupt_lines"] == 4
    assert data["runs"] == 2
    assert data["total_saved_tokens"] == 1000
    assert summary(project)["corrupt_lines"] == 4


def test_empty_ledger_analytics(project):
    data = analytics(project, model=MODEL, prices=PRICES)
    assert data["runs"] == 0
    assert data["runs_detail"] == []
    assert data["aggregates"]["best_run"] is None
    assert data["charts"]["saved_tokens_sparkline"] == ""
    assert data["estimator"]["mixed"] is False


def test_huge_ledger_stays_correct(project):
    recs = []
    for i in range(5000):
        recs.append({"at": f"2026-10-{(i % 28) + 1:02d}T10:00:00+00:00",
                     "kind": "export", "bundle": None,
                     "before_tokens": 1000, "after_tokens": 500,
                     "saved_tokens": 500, "estimator": "v2"})
    write_ledger(project, recs)
    start = time.monotonic()
    data = analytics(project, model=MODEL, prices=PRICES)
    elapsed = time.monotonic() - start
    assert data["runs"] == 5000
    assert data["total_saved_tokens"] == 5000 * 500
    assert data["aggregates"]["best_run"]["saved_tokens"] == 500
    assert len(data["charts"]["saved_tokens_sparkline"]) == 60
    assert elapsed < 10.0


def test_best_worst_ties_pick_earliest_run(project):
    recs = [dict(r, saved_tokens=500, before_tokens=1000, after_tokens=500)
            for r in RUNS]
    write_ledger(project, recs)
    agg = analytics(project)["aggregates"]
    assert agg["best_run"]["index"] == 0
    assert agg["worst_run"]["index"] == 0


def test_cli_json_empty_ledger(project):
    rc, out = _run_history([str(project), "--json"])
    assert rc == 0
    data = json.loads(out)
    assert data["runs"] == 0
    assert data["aggregates"]["best_run"] is None
    assert data["runs_detail"] == []


def test_negative_saving_run_is_honest(project):
    write_ledger(project, [{"at": "2026-10-01T10:00:00+00:00", "kind": "export",
                            "bundle": None, "before_tokens": 100,
                            "after_tokens": 130, "saved_tokens": -30,
                            "estimator": "v2"}])
    data = analytics(project, model=MODEL, prices=PRICES)
    assert data["runs_detail"][0]["saved_tokens"] == -30
    assert data["runs_detail"][0]["saved_cost_usd"] < 0


# -------------------------------------------------------------- sparkline

def test_sparkline_exact_levels():
    assert sparkline([400, 600, 450]) == "▁█▃"
    assert sparkline([7]) == "▄"          # single run, zero variance
    assert sparkline([5, 5, 5]) == "▄▄▄"   # zero variance
    assert sparkline([]) == ""


def test_sparkline_downsamples_to_width():
    out = sparkline(list(range(200)), width=40)
    assert len(out) == 40
    assert out[0] == "▁" and out[-1] == "█"


# -------------------------------------------------------------------- CLI

def _run_history(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["history", *argv])
    return rc, buf.getvalue()


def test_cli_default_block_unchanged_shape(project):
    write_ledger(project, RUNS)
    rc, out = _run_history([str(project)])
    assert rc == 0
    assert f"Savings ledger for {project}: 3 recorded run(s)" in out
    assert "  Total before: 3,100  after: 1,650  saved: 1,450 estimated tokens" in out
    assert "Trend (" not in out


def test_cli_trend_table_deltas_and_labels(project):
    write_ledger(project, RUNS)
    rc, out = _run_history([str(project), "--trend"])
    assert rc == 0
    assert "1,200" in out and "450" in out          # run rows present
    assert "-150" in out                            # Δafter for run 3
    assert "mean 46.67%" in out and "median 50.00%" in out
    assert "Saved tokens per run:" in out
    assert "After tokens per run:" in out
    assert "prices as of 2026-10-12" in out         # dated, local snapshot
    assert "not live" in out


def test_cli_trend_single_run(project):
    write_ledger(project, RUNS[:1])
    rc, out = _run_history([str(project), "--trend"])
    assert rc == 0
    assert "Saved tokens per run:  ▄" in out


def test_cli_trend_empty(project):
    rc, out = _run_history([str(project), "--trend"])
    assert rc == 0
    assert "No recorded runs yet" in out


def test_cli_json_is_analytics_and_additive(project):
    write_ledger(project, RUNS)
    rc, out = _run_history([str(project), "--json"])
    assert rc == 0
    data = json.loads(out)
    for key in ("runs", "total_before_tokens", "total_after_tokens",
                "total_saved_tokens", "records"):   # old summary keys
        assert key in data
    for key in ("runs_detail", "aggregates", "estimator", "charts",
                "corrupt_lines", "model"):
        assert key in data
    assert data["aggregates"]["after_change_tokens"] == -150


def test_cli_corrupt_and_mix_warnings_printed(project):
    lines = [json.dumps(RUNS[0]), "{broken",
             json.dumps({k: v for k, v in RUNS[1].items() if k != "estimator"})]
    write_ledger(project, lines)
    rc, out = _run_history([str(project)])
    assert rc == 0
    assert "skipped 1 corrupt ledger line(s)" in out
    assert "Estimator mix:" in out


def test_cli_unknown_model_is_usage_error(project):
    write_ledger(project, RUNS)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["history", str(project), "--model", "no-such-model"])
    assert rc == 2


# ------------------------------------------------------------------ report

def test_report_embeds_history_chart(project):
    write_ledger(project, RUNS)
    html = build_report(project)
    assert "Savings history" in html
    assert "<svg" in html
    assert "after tokens (own scale)" in html
    assert "1,450 estimated tokens" in html


def test_report_without_ledger_has_no_history_section(project):
    html = build_report(project)
    assert "Savings history" not in html
    assert "<svg" not in html


def test_report_history_shows_estimator_warning(project):
    old = [{k: v for k, v in RUNS[0].items() if k != "estimator"}]
    write_ledger(project, old)
    html = build_report(project)
    assert "Estimator mix:" in html
    assert "<svg" in html   # 1-run chart still renders


# -------------------------------------------------------------------- API

def test_api_history_shape(project):
    import threading
    write_ledger(project, RUNS)
    server, _ = make_server(str(project), port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/history", timeout=10) as r:
            data = json.loads(r.read())
    finally:
        server.shutdown()
        server.server_close()
    for key in ("runs", "total_before_tokens", "total_after_tokens",
                "total_saved_tokens", "records"):
        assert key in data
    for key in ("runs_detail", "aggregates", "estimator", "charts", "model"):
        assert key in data
    assert data["runs"] == 3
    assert data["aggregates"]["median_saved_pct"] == 50.0
    assert data["model"]["prices_as_of"] == "2026-10-12"
