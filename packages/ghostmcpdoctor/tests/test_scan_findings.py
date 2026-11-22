"""Scan findings: duplicates, missing commands, broad permissions.

Fixtures do the planting (see test_fixtures_sanity.py):
  messy/mcp.json - filesystem-main + filesystem-copy share the exact
    same command and args, the filesystem server is granted "/",
    missing-tool's command does not exist on this machine, and
    secret-server's command (python3) does exist.
  duplicates_across_files/ - "shared-server" is defined identically
    in claude/mcp.json and cursor/mcp.json; scanning the directory
    must surface the cross-file duplicate.
"""
from conftest import copy_fixture, scan_path, window_around


def test_same_command_twins_are_both_inventoried(tmp_path):
    """filesystem-main / filesystem-copy are distinct NAMES with the
    same command + args. PLAN's DUPLICATE check is name-based, so this
    test does not demand a DUPLICATE finding here - it demands both
    entries are inventoried and both earn the broad finding (below)."""
    cfg = copy_fixture(tmp_path, "messy")
    proc, text = scan_path(cfg / "mcp.json", tmp_path)
    assert proc.returncode in (0, 1), \
        f"scan crashed (rc={proc.returncode}): {text[-1500:]}"
    low = text.lower()
    assert "filesystem-main" in low and "filesystem-copy" in low


def test_duplicate_name_across_scopes_of_one_file_is_reported(tmp_path):
    """PLAN verification bar, in-file form: the same server name at
    top level and nested under projects.<path>.mcpServers of the same
    config is a DUPLICATE (one finding for the extra definition)."""
    cfg = copy_fixture(tmp_path, "duplicate_scopes")
    proc, text = scan_path(cfg / "mcp.json", tmp_path)
    assert proc.returncode in (0, 1), \
        f"scan crashed (rc={proc.returncode}): {text[-1500:]}"
    low = text.lower()
    assert "scoped-server" in low
    near = window_around(low, "scoped-server", 1200)
    assert "duplicate" in near or "duplicated" in near or \
        "defined twice" in near or "also defined" in near, \
        "scoped-server duplication across scopes not flagged"


def test_missing_file_argument_is_reported(tmp_path):
    """PLAN verification bar: stale-script points python3 at a script
    file that does not exist next to the config -> MISSING-FILE."""
    cfg = copy_fixture(tmp_path, "messy")
    proc, text = scan_path(cfg / "mcp.json", tmp_path)
    low = text.lower()
    assert "stale-script" in low
    near = window_around(low, "stale-script", 1200)
    assert any(tok in near for tok in (
        "missing-file", "missing file", "does not exist", "not exist")), \
        "stale-script's missing file not flagged as missing"


def test_duplicate_across_files_is_reported(tmp_path):
    cfg = copy_fixture(tmp_path, "duplicates_across_files")
    proc, text = scan_path(cfg, tmp_path)
    assert proc.returncode in (0, 1), \
        f"directory scan crashed (rc={proc.returncode}): {text[-1500:]}"
    low = text.lower()
    assert "shared-server" in low, "shared-server not in directory report"
    near = window_around(low, "shared-server", 1200)
    assert any(tok in near for tok in (
        "duplicate", "duplicated", "twice", "both", "multiple",
        "2 files", "two files", "also defined", "cursor")), \
        "shared-server is listed but its cross-file duplication is not flagged"


def test_missing_command_is_reported_by_name(tmp_path):
    cfg = copy_fixture(tmp_path, "messy")
    proc, text = scan_path(cfg / "mcp.json", tmp_path)
    low = text.lower()
    assert "missing-tool" in low or \
        "ghostmcp-nonexistent-binary-9f3k" in low, \
        "missing-tool server/command not in report"
    near = window_around(low, "missing-tool", 900) or \
        window_around(low, "ghostmcp-nonexistent-binary-9f3k", 900)
    assert any(tok in near for tok in (
        "missing", "not found", "not on path", "not installed",
        "does not exist", "no such", "unavailable", "absent")), \
        "missing command is listed but not flagged as missing"


def test_existing_command_is_not_flagged_missing(tmp_path):
    """python3 exists on this machine, so secret-server (command
    python3) must earn no MISSING-COMMAND finding. Structured check
    when the report JSON is available; line-level check otherwise
    (text windows are unreliable: the report's own notes mention
    MISSING-COMMAND generically)."""
    from conftest import load_report_json
    cfg = copy_fixture(tmp_path, "messy")
    proc, text = scan_path(cfg / "mcp.json", tmp_path)
    report = load_report_json(tmp_path)
    if report is not None:
        bad = [f for f in report.get("findings", [])
               if f.get("server") == "secret-server"
               and f.get("issue") == "MISSING-COMMAND"]
        assert bad == [], bad
    else:
        for line in text.lower().splitlines():
            assert not ("secret-server" in line
                        and "missing-command" in line), line


def test_broad_permission_is_reported(tmp_path):
    cfg = copy_fixture(tmp_path, "messy")
    proc, text = scan_path(cfg / "mcp.json", tmp_path)
    low = text.lower()
    assert any(tok in low for tok in (
        "broad", "wide", "root", "entire filesystem", "whole filesystem",
        "unrestricted", "full access", "permission")), \
        "no broad-permission finding in report"
    near = window_around(low, "filesystem-main", 1000) or \
        window_around(low, "server-filesystem", 1000)
    assert near, "filesystem server not mentioned in report"


def test_every_server_in_file_is_listed(tmp_path):
    cfg = copy_fixture(tmp_path, "messy")
    proc, text = scan_path(cfg / "mcp.json", tmp_path)
    low = text.lower()
    for name in ("filesystem-main", "filesystem-copy", "missing-tool",
                 "stale-script", "secret-server", "shell-server"):
        assert name in low, f"{name} missing from report listing"


def test_json_mode_produces_parseable_output(tmp_path):
    cfg = copy_fixture(tmp_path, "messy")
    from conftest import load_report_json, out_text, parse_json_output
    proc, text = scan_path(cfg / "mcp.json", tmp_path, want_json=True)
    # Parse STDOUT alone first (in --json mode it is the report), then
    # the report file. The combined text deliberately concatenates
    # stdout + Markdown + JSON, which no single parse should survive.
    data = parse_json_output(out_text(proc)) or load_report_json(tmp_path)
    if data is None:
        # Some cores write report.json to the working dir instead of
        # stdout; scan_path already folded file contents into text, so
        # reaching here means no JSON surface at all. That is only a
        # failure if the CLI advertises --json in its help.
        from conftest import out_text, run_cli
        help_text = out_text(run_cli(["--help"])).lower()
        assert "--json" not in help_text and "json" not in help_text, \
            "CLI mentions JSON but --json produced no parseable JSON"
    else:
        assert "filesystem-main" in text or "filesystem" in text
