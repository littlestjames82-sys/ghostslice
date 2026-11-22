"""The `report` command: re-render Markdown + JSON from a previous
scan's mcpdoctor-report.json without re-scanning (PLAN MVP item 4).

The re-rendered output is a sharing surface, so the redaction rule
applies to it exactly as to a fresh scan: no fake canary may appear,
and the env key names must survive the round trip.
"""
from pathlib import Path

from conftest import (FAKE_SECRET_CANARIES, copy_fixture, load_report_json,
                      out_text, run_cli, scan_path)


def test_report_rerender_round_trip_without_canaries(tmp_path):
    cfg = copy_fixture(tmp_path, "messy")
    scan_path(cfg / "mcp.json", tmp_path)
    report = load_report_json(tmp_path)
    assert report is not None, "scan wrote no mcpdoctor-report.json"
    src = Path(tmp_path) / "_work" / "mcpdoctor-report.json"
    assert src.is_file()

    out_dir = Path(tmp_path) / "rerender"
    proc = run_cli(["report", src, "--out-dir", out_dir])
    assert proc.returncode in (0, 1), out_text(proc)
    md = out_dir / "MCPDOCTOR.md"
    js = out_dir / "mcpdoctor-report.json"
    assert md.is_file(), f"no MCPDOCTOR.md re-rendered: {out_text(proc)}"
    assert js.is_file(), f"no report JSON re-rendered: {out_text(proc)}"
    combined = md.read_text(errors="replace") + js.read_text(errors="replace") \
        + out_text(proc)
    for canary in FAKE_SECRET_CANARIES:
        assert canary not in combined, f"canary leaked on re-render: {canary}"
    assert "secret-server" in combined
    assert "FAKE_API_KEY" in combined, "env key name lost on re-render"
    assert "BROAD-FILESYSTEM" in combined or "broad" in combined.lower()
