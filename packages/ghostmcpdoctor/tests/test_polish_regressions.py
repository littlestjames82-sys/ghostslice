"""Polish-round regressions (Oct 14, 2026) - one test per fixed defect.

Fixed in this round (see POLISH.md for the audit trail):
  1. Info-only findings (a lone DISABLED server) exited 1; PLAN.md
     defines exit 0 as "no findings above info". Disabled-only now
     exits 0, a warning/error alongside the info still exits 1, and
     the `report` re-render recomputes the code instead of trusting a
     stale stored one.
  2. A present-but-non-object server container (`mcpServers: [...]`)
     scanned as a clean exit 0; PLAN.md calls it a PARSE-ERROR. It is
     one now, and well-formed containers / other files still scan
     (parse-error recovery, not abort).
  3. A UTF-8 BOM turned a valid config into a PARSE-ERROR; BOM is
     tolerated now.
  4. A DUPLICATE finding for an in-file scope duplicate named only
     the file (the same file); the scope is named in the detail now.
  5. The URL field kept the port (`host:8443`) although the rule is
     host only; userinfo, port, query and fragment are all dropped.
"""
import json
from pathlib import Path

from conftest import copy_fixture, load_report_json, out_text, run_cli, scan_path

URL_CANARY = "FAKE-URL-CANARY-DOCTOR-9d41-never-print"


def _scan_json(tmp_path, target, *extra):
    """Run `scan --json --no-report` directly and parse the report."""
    proc = run_cli(["scan", target, "--no-report", "--json", *extra],
                   cwd=tmp_path)
    return proc, json.loads(proc.stdout)


def _write(tmp_path, name, data, bom=False):
    p = Path(tmp_path) / name
    raw = json.dumps(data).encode()
    p.write_bytes((b"\xef\xbb\xbf" + raw) if bom else raw)
    return p


# 1. Exit-code rule ---------------------------------------------------

def test_disabled_only_fixture_scans_exit_0(tmp_path):
    cfg = copy_fixture(tmp_path, "disabled_only")
    proc, report = _scan_json(tmp_path, cfg / "mcp.json")
    assert proc.returncode == 0, out_text(proc)
    assert report["exit_code"] == 0
    findings = report["findings"]
    assert [(f["server"], f["issue"], f["severity"]) for f in findings] == [
        ("retired-server", "DISABLED", "info")]
    assert report["summary"]["by_severity"] == {"info": 1}


def test_info_plus_error_still_exits_1(tmp_path):
    cfg = _write(tmp_path, "mixed.json", {"mcpServers": {
        "retired": {"command": "python3", "disabled": True},
        "gone": {"command": "ghostmcp-nonexistent-binary-9f3k"},
    }})
    proc, report = _scan_json(tmp_path, cfg)
    assert proc.returncode == 1
    assert {f["issue"] for f in report["findings"]} == {
        "DISABLED", "MISSING-COMMAND"}


def test_disabled_only_report_rerender_exits_0(tmp_path):
    cfg = copy_fixture(tmp_path, "disabled_only")
    scan_path(cfg / "mcp.json", tmp_path)
    report = load_report_json(tmp_path)
    assert report is not None and report["exit_code"] == 0
    src = Path(tmp_path) / "_work" / "mcpdoctor-report.json"
    out_dir = Path(tmp_path) / "rerender"
    proc = run_cli(["report", src, "--out-dir", out_dir])
    assert proc.returncode == 0, out_text(proc)
    rerendered = json.loads((out_dir / "mcpdoctor-report.json").read_text())
    assert rerendered["exit_code"] == 0


def test_report_rerender_recomputes_a_stale_stored_exit_code(tmp_path):
    """A report written before the fix stores exit_code 1 for an
    info-only scan; re-rendering must correct it to 0, not inherit."""
    stale = {
        "tool": "ghostmcpdoctor", "version": "0.1.0",
        "configs": [{"path": "x.json", "client": "generic",
                     "status": "ok", "server_count": 1}],
        "servers": [], "missing_explicit_paths": [],
        "findings": [{"server": "old", "config_path": "x.json",
                      "path": "", "issue": "DISABLED",
                      "severity": "info", "stale": True,
                      "detail": "entry is marked disabled"}],
        "summary": {}, "notes": [], "exit_code": 1,
    }
    src = _write(tmp_path, "stale-report.json", stale)
    out_dir = Path(tmp_path) / "out"
    proc = run_cli(["report", src, "--out-dir", out_dir])
    assert proc.returncode == 0, out_text(proc)
    fixed = json.loads((out_dir / "mcpdoctor-report.json").read_text())
    assert fixed["exit_code"] == 0


# 2/3. Parse-error shape + recovery ------------------------------------

def test_non_object_container_is_a_parse_error(tmp_path):
    cfg = copy_fixture(tmp_path, "bad_container")
    proc, report = _scan_json(tmp_path, cfg / "mcp.json")
    assert proc.returncode == 1, out_text(proc)
    assert report["servers"] == []
    assert [(f["issue"], f["severity"]) for f in report["findings"]] == [
        ("PARSE-ERROR", "error")]
    assert report["configs"][0]["status"] == "parse-error"


def test_bad_container_recovers_wellformed_container_in_same_file(tmp_path):
    cfg = _write(tmp_path, "mixed-shape.json", {
        "mcpServers": ["not", "an", "object"],
        "servers": {"good-server": {"command": "python3",
                                    "args": ["-m", "example_good"]}},
    })
    proc, report = _scan_json(tmp_path, cfg)
    assert proc.returncode == 1
    assert [f["issue"] for f in report["findings"]] == ["PARSE-ERROR"]
    assert [s["name"] for s in report["servers"]] == ["good-server"]


def test_parse_error_in_one_file_does_not_block_another(tmp_path):
    broken = copy_fixture(tmp_path, "invalid") / "broken.json"
    clean = copy_fixture(tmp_path, "clean") / "mcp.json"
    proc = run_cli(["scan", broken, clean, "--no-report", "--json"],
                   cwd=tmp_path)
    report = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert "PARSE-ERROR" in {f["issue"] for f in report["findings"]}
    assert [s["name"] for s in report["servers"]] == ["docs-reader"]


def test_bom_prefixed_config_parses(tmp_path):
    cfg = _write(tmp_path, "bom.json",
                 {"mcpServers": {"a": {"command": "python3"}}}, bom=True)
    proc, report = _scan_json(tmp_path, cfg)
    assert proc.returncode == 0, out_text(proc)
    assert [s["name"] for s in report["servers"]] == ["a"]
    assert report["findings"] == []


# 4. Duplicate scope detail ---------------------------------------------

def test_duplicate_scope_detail_names_the_scope(tmp_path):
    cfg = copy_fixture(tmp_path, "duplicate_scopes")
    scan_path(cfg / "mcp.json", tmp_path)
    report = load_report_json(tmp_path)
    assert report is not None
    dups = [f for f in report["findings"] if f["issue"] == "DUPLICATE"]
    assert len(dups) == 1, report["findings"]
    assert dups[0]["server"] == "scoped-server"
    assert "projects." in dups[0]["detail"], dups[0]["detail"]


# 5. URL redaction --------------------------------------------------------

def test_url_keeps_host_only(tmp_path):
    url = (f"https://user:{URL_CANARY}@api.example.com:8443/mcp"
           f"?token={URL_CANARY}#frag={URL_CANARY}")
    cfg = _write(tmp_path, "url.json", {"mcpServers": {"remote": {"url": url}}})
    proc, report = _scan_json(tmp_path, cfg)
    assert proc.returncode == 0, out_text(proc)
    assert URL_CANARY not in out_text(proc)
    assert URL_CANARY not in json.dumps(report)
    assert [s["url_host"] for s in report["servers"]] == ["api.example.com"]
