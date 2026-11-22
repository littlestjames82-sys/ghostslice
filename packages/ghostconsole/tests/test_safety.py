"""Safety tests: the offline bar, the hostile-content bar, exact
numbers, and unreadable reports degrading visibly instead of crashing.
(PLAN verification bars: hostile content, offline.)"""
from __future__ import annotations

import re

import conftest
from conftest import (APPROVE_PENDING, BENCH_TASKS_FAILED, BENCH_TASKS_TOTAL,
                      LEDGER_LOOP_WARNINGS, SLICE_AFTER, SLICE_BEFORE,
                      VERIFY_HARD_GAPS, combined, healthy_project, run_cli,
                      write_json)

PAYLOAD_SCRIPT = "<script>alert('xss-probe')</script>"
PAYLOAD_IMG = '"><img src=x onerror=alert(2)>'
PAYLOAD_URL = "https://evil.example/steal"


def _board(cli, tmp_path, projects):
    out = tmp_path / "board.html"
    proc = run_cli(cli, ["build", *projects, "-o", out])
    assert proc.returncode == 0, combined(proc)
    return out.read_text(encoding="utf-8")


def test_offline_bar_no_external_refs_no_scripts(cli, tmp_path):
    html = _board(cli, tmp_path, [healthy_project(tmp_path)])
    low = html.lower()
    assert "http://" not in low and "https://" not in low
    assert "<script" not in low
    assert "src=" not in low.replace("src=\"#\"", "")  # no external assets
    assert "<link" not in low and "<iframe" not in low


def test_hostile_content_is_escaped_not_injected(cli, tmp_path):
    """Report files carrying markup, a script payload, and a URL must
    render as visible text only. The raw payloads never appear; their
    escaped forms do (or the strings are dropped whole, which is also
    safe but must not break the board)."""
    p = tmp_path / "hostile"
    p.mkdir()
    conftest.slice_history(p)
    # A Verify report whose task name carries the payloads.
    conftest.verify_report(p, verdict="sufficient")
    rep = p / "bundle" / "verify-report.json"
    data = rep.read_text(encoding="utf-8")
    data = data.replace("fixture task",
                        f"{PAYLOAD_SCRIPT} {PAYLOAD_IMG} {PAYLOAD_URL}")
    rep.write_text(data, encoding="utf-8")
    # A Scope note carrying a payload too.
    scope = conftest.scope_pack(p)
    sdata = scope.read_text(encoding="utf-8").replace(
        '"notes": []',
        f'"notes": [{{"kind": "note", "detail": "{PAYLOAD_SCRIPT}"}}]')
    scope.write_text(sdata, encoding="utf-8")
    html = _board(cli, tmp_path, [p])
    low = html.lower()
    assert "<script" not in low, "script payload reached the board raw"
    assert PAYLOAD_IMG not in html, "img payload reached the board raw"
    assert PAYLOAD_URL not in html, "URL payload reached the board raw"
    # Escaped or dropped, the board is still a complete board.
    assert "hostile" in low and "no report found" in low


def test_numbers_on_board_match_fixtures_exactly(cli, tmp_path):
    p = conftest.attention_project(tmp_path)
    conftest.bench_report(p)
    conftest.bench_history(p)
    conftest.ledger_report(p, loop_warnings=LEDGER_LOOP_WARNINGS)
    conftest.scope_pack(p)
    html = _board(cli, tmp_path, [p])
    plain = re.sub(r"<[^>]+>", " ", html)
    for number in (SLICE_BEFORE, SLICE_AFTER):
        assert (str(number) in plain or f"{number:,}" in plain), (
            f"slice total {number} missing from the board")
    assert str(VERIFY_HARD_GAPS) in plain, "verify hard-gap count missing"
    assert str(APPROVE_PENDING) in plain, "pending approvals missing"
    assert str(BENCH_TASKS_TOTAL) in plain, "bench task total missing"


def test_unreadable_report_degrades_visibly(cli, tmp_path):
    """A present but corrupt report is shown as unreadable or not
    recognized, the board still completes, and the run exits 0."""
    p = tmp_path / "corrupt"
    p.mkdir()
    conftest.slice_history(p)
    bad = p / "pack" / "scope.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{ this is not json", encoding="utf-8")
    write_json(p / "watch" / "watch-report.json",
               {"tool": "ghostwatch", "verdict": "fresh"})
    out = tmp_path / "board.html"
    proc = run_cli(cli, ["build", p, "-o", out])
    assert proc.returncode == 0, combined(proc)
    html = out.read_text(encoding="utf-8").lower()
    assert "corrupt" in html
    assert any(word in html for word in
               ("unreadable", "not recognized", "could not read",
                "unrecognized", "invalid")), (
        "corrupt report not labelled as unreadable on the board")
    # Unreadable counts as attention per the plan's classification.
    from test_columns import _column_of
    assert _column_of(out.read_text(encoding="utf-8"), "corrupt") == \
        "attention"


def test_report_path_and_age_shown(cli, tmp_path):
    p = healthy_project(tmp_path)
    html = _board(cli, tmp_path, [p])
    # The card names the report file used, so a wrong pick is visible.
    assert "verify-report.json" in html or ".ghostverify-history.jsonl" \
        in html
    assert "manifest.json" in html or ".ghostslice-history.jsonl" in html
