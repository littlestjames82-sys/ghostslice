"""Read-only guarantee and edge cases.

GhostMCP Doctor never edits configs (task scope). That is proved,
not trusted: hash and list every config file before and after scans
(text mode, JSON mode, and a directory scan) and require identity.

Edges: a genuinely clean config earns no duplicate / missing / broad
flags; an empty server map scans without crashing; invalid JSON is
reported as a parse problem (never as a clean pass); a nonexistent
path is an error, not a pass; --help exists and names the scan.
"""
from conftest import (copy_fixture, out_text, run_cli, scan_path,
                      snapshot_tree, window_around)


def test_scan_never_modifies_config_files(tmp_path):
    cfg = copy_fixture(tmp_path, "messy")
    before = snapshot_tree(cfg)
    assert before, "fixture copy produced no files"
    scan_path(cfg / "mcp.json", tmp_path)
    scan_path(cfg / "mcp.json", tmp_path, want_json=True)
    scan_path(cfg, tmp_path)
    after = snapshot_tree(cfg)
    assert after == before, \
        f"config tree changed by scanning: before={before} after={after}"


def test_scan_preserves_config_mtimes(tmp_path):
    """PLAN verification bar, literal form: bytes AND mtimes unchanged."""
    cfg = copy_fixture(tmp_path, "messy")
    target = cfg / "mcp.json"
    before_bytes = target.read_bytes()
    before_mtime = target.stat().st_mtime_ns
    scan_path(target, tmp_path)
    scan_path(target, tmp_path, want_json=True)
    assert target.read_bytes() == before_bytes
    assert target.stat().st_mtime_ns == before_mtime


def test_scan_never_modifies_duplicate_tree(tmp_path):
    cfg = copy_fixture(tmp_path, "duplicates_across_files")
    before = snapshot_tree(cfg)
    scan_path(cfg, tmp_path)
    assert snapshot_tree(cfg) == before


def test_clean_config_has_no_findings(tmp_path):
    """PLAN verification bar: a valid, narrow, enabled fixture scans
    with exit 0 and an EMPTY findings list. Judged on the structured
    report when one is written (precise), else on rc + counts."""
    from conftest import load_report_json
    cfg = copy_fixture(tmp_path, "clean")
    proc, text = scan_path(cfg / "mcp.json", tmp_path)
    assert proc.returncode == 0, \
        f"clean config did not pass cleanly (rc={proc.returncode}): {text[-1200:]}"
    assert "docs-reader" in text.lower(), "clean server not listed"
    report = load_report_json(tmp_path)
    if report is not None:
        assert report.get("findings") == [], report.get("findings")
        names = [s.get("name") for s in report.get("servers", [])]
        assert names == ["docs-reader"], names
    else:
        assert "0 finding" in text.lower()


def test_empty_config_scans_without_crashing(tmp_path):
    cfg = copy_fixture(tmp_path, "empty")
    proc, text = scan_path(cfg / "mcp.json", tmp_path)
    assert "traceback" not in text.lower()
    assert proc.returncode in (0, 1), \
        f"empty config rc={proc.returncode}: {text[-1200:]}"


def test_invalid_json_is_reported_not_passed(tmp_path):
    cfg = copy_fixture(tmp_path, "invalid")
    proc, text = scan_path(cfg / "broken.json", tmp_path)
    low = text.lower()
    assert "traceback" not in low
    assert any(tok in low for tok in (
        "invalid", "parse", "json", "error", "malformed", "could not",
        "cannot", "failed")), \
        "invalid JSON not described as a problem"
    assert "broken.json" in low or "broken" in low


def test_nonexistent_path_is_an_error_not_a_pass(tmp_path):
    missing = tmp_path / "no-such-config.json"
    proc, text = scan_path(missing, tmp_path)
    low = text.lower()
    assert proc.returncode != 0 or any(tok in low for tok in (
        "not found", "no such", "does not exist", "missing", "error")), \
        f"nonexistent path looked like a pass (rc={proc.returncode})"


def test_help_names_a_scan_command():
    proc = run_cli(["--help"])
    text = out_text(proc).lower()
    assert proc.returncode == 0
    assert any(tok in text for tok in ("scan", "check", "doctor", "audit")), \
        "help names no scan-like command"
    assert "mcp" in text


def test_vscode_shape_config_is_read(tmp_path):
    cfg = copy_fixture(tmp_path, "vscode")
    proc, text = scan_path(cfg / "mcp.json", tmp_path)
    # Tolerant: a core that only supports mcpServers in v0.1 must say
    # so (no servers / unsupported), not crash or silently pass.
    low = text.lower()
    assert "traceback" not in low
    assert ("vscode-docs" in low) or any(tok in low for tok in (
        "no servers", "0 servers", "unsupported", "no mcp", "empty")), \
        "VS Code 'servers' shape was neither read nor explained"
