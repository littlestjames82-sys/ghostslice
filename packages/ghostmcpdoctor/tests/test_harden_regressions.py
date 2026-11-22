"""Harden-round regressions (Oct 18, 2026) - one test per fixed defect.

Found by adversarial probing of the shipped core (see IMPROVE.md):

  R1. A command STRING embedding arguments ("tool --api-key=...",
      "bash -c ...") was reported verbatim as the "basename",
      leaking the embedded argument list and hiding shell wrappers.
      A secret-shaped basename now redacts, like env values do.
  R2. `cwd` bypassed every guard applied to arg paths: stored
      verbatim and copied into referenced_paths / finding paths.
  R3. A URL passed as an ARG (userinfo credentials, ".py" tail)
      became a verbatim "referenced path"; only the url FIELD was
      stripped to host.
  R4. BROAD-FILESYSTEM missed "~/", "$HOME/", "${HOME}", home with
      a trailing slash, "../", "../..", "..\\", and home's ancestors.
  R5. BROAD-ENV missed " * " / "**" env values, a bare-string
      alwaysAllow, padded allow entries, and `auto_approve`.
  R6. disabled: "false" (string) was reported DISABLED, because
      bool("false") is True.
  R7. A "$HOME/bin/tool" command was always MISSING-COMMAND:
      the existence check never expanded $HOME / ${HOME}.
  R8. `report` crashed with a traceback on valid JSON with the
      right tool tag but malformed structure.
  R9. The same config named by two spellings (relative + absolute)
      was scanned twice, inventing a DUPLICATE for every server.
"""
import json
import os
from pathlib import Path

from conftest import FAKE_SECRET_CANARIES, copy_fixture, out_text, run_cli

CANARY = FAKE_SECRET_CANARIES[0]
# A credential-shaped value with NO secret-keyword substring, so a
# keyword denylist alone cannot save it.
HEX = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8"


def _write(tmp_path, name, data):
    p = Path(tmp_path) / name
    p.write_text(json.dumps(data))
    return p


def _scan_json(tmp_path, target, *extra):
    proc = run_cli(["scan", target, "--no-report", "--json", *extra],
                   cwd=tmp_path)
    return proc, json.loads(proc.stdout)


# R1 / R3. Redaction: command strings and URL args ---------------------

def test_command_string_embedded_secret_arg_is_not_leaked(tmp_path):
    cfg = _write(tmp_path, "c.json", {"mcpServers": {
        "s": {"command": f"python3 --api-key={HEX}"}}})
    proc, report = _scan_json(tmp_path, cfg)
    assert HEX not in out_text(proc)
    assert HEX not in json.dumps(report)
    assert report["servers"][0]["command"] == "python3"
    assert report["findings"] == []  # python3 exists; nothing else wrong


def test_secret_shaped_command_basename_is_redacted(tmp_path):
    for command in (CANARY, f"/opt/tools/{CANARY}"):
        cfg = _write(tmp_path, "c.json", {"mcpServers": {
            "s": {"command": command}}})
        proc, report = _scan_json(tmp_path, cfg)
        assert CANARY not in out_text(proc), command
        assert CANARY not in json.dumps(report), command
        assert report["servers"][0]["command"] == "[redacted]"
        # The entry is still audited: its (nonexistent) command is
        # reported, by the redacted name only.
        assert [f["issue"] for f in report["findings"]] == ["MISSING-COMMAND"]
        assert CANARY not in report["findings"][0]["detail"]


def test_missing_command_name_still_reported_verbatim(tmp_path):
    """Guard against over-redaction: an ordinary missing binary name
    is an identifier, not a secret, and must still be named."""
    cfg = _write(tmp_path, "c.json", {"mcpServers": {
        "s": {"command": "ghostmcp-nonexistent-binary-9f3k"}}})
    proc, report = _scan_json(tmp_path, cfg)
    assert report["findings"][0]["issue"] == "MISSING-COMMAND"
    assert "ghostmcp-nonexistent-binary-9f3k" in \
        report["findings"][0]["detail"]


def test_url_arg_with_credentials_is_not_a_referenced_path(tmp_path):
    cfg = _write(tmp_path, "c.json", {"mcpServers": {
        "s": {"command": "python3",
              "args": [f"https://user:{HEX}@api.example.com/server.py"]}}})
    proc, report = _scan_json(tmp_path, cfg)
    assert HEX not in out_text(proc)
    assert HEX not in json.dumps(report)
    assert report["servers"][0]["referenced_paths"] == []


# R2. Redaction: cwd ----------------------------------------------------

def test_secret_shaped_cwd_is_redacted(tmp_path):
    cfg = _write(tmp_path, "c.json", {"mcpServers": {
        "s": {"command": "python3", "cwd": CANARY}}})
    proc, report = _scan_json(tmp_path, cfg)
    assert CANARY not in out_text(proc)
    assert CANARY not in json.dumps(report)
    srv = report["servers"][0]
    assert srv["cwd"] == "[redacted]"
    assert srv["referenced_paths"] == []
    assert report["findings"] == []


def test_ordinary_cwd_is_still_reported(tmp_path):
    """Segment (not substring) matching: an 'author' project path
    contains 'auth' as a substring but is not secret-shaped."""
    cfg = _write(tmp_path, "c.json", {"mcpServers": {
        "s": {"command": "python3", "cwd": "/work/author-app"}}})
    proc, report = _scan_json(tmp_path, cfg)
    assert report["servers"][0]["cwd"] == "/work/author-app"


# R1b. Shell wrapper hidden in a command string -------------------------

def test_embedded_shell_command_is_a_shell_wrapper(tmp_path):
    cfg = _write(tmp_path, "c.json", {"mcpServers": {
        "s": {"command": "bash -c 'echo hi'"}}})
    proc, report = _scan_json(tmp_path, cfg)
    assert report["servers"][0]["command"] == "bash"
    assert [f["issue"] for f in report["findings"]] == ["SHELL-WRAPPER"]


# R4. Broad filesystem spellings -----------------------------------------

def test_broad_path_spelling_variants(tmp_path):
    home = Path(tmp_path) / "home" / "user"
    broad_args = ["~/", "$HOME/", "${HOME}", "${HOME}/", "../", "../..",
                  "..\\", str(home) + "/", str(home.parent)]
    for arg in broad_args:
        cfg = _write(tmp_path, "c.json", {"mcpServers": {
            "s": {"command": "python3", "args": [arg]}}})
        proc, report = _scan_json(tmp_path, cfg, "--home", home)
        issues = [f["issue"] for f in report["findings"]]
        assert "BROAD-FILESYSTEM" in issues, (arg, report["findings"])


def test_narrow_path_args_are_not_broad(tmp_path):
    home = Path(tmp_path) / "home" / "user"
    for arg in ("../sibling/server.py", "project/*", "./local/*"):
        cfg = _write(tmp_path, "c.json", {"mcpServers": {
            "s": {"command": "python3", "args": [arg]}}})
        proc, report = _scan_json(tmp_path, cfg, "--home", home)
        issues = [f["issue"] for f in report["findings"]]
        assert "BROAD-FILESYSTEM" not in issues, (arg, report["findings"])


# R5. Broad env spellings -------------------------------------------------

def test_env_wildcard_whitespace_and_globstar(tmp_path):
    for value in (" * ", "**"):
        cfg = _write(tmp_path, "c.json", {"mcpServers": {
            "s": {"command": "python3", "env": {"A": value}}}})
        proc, report = _scan_json(tmp_path, cfg)
        assert [f["issue"] for f in report["findings"]] == ["BROAD-ENV"], \
            (value, report["findings"])


def test_allow_list_string_and_snake_case_key(tmp_path):
    for extra in ({"alwaysAllow": "*"}, {"auto_approve": ["*"]},
                  {"alwaysAllow": [" * "]}):
        entry = {"command": "python3"}
        entry.update(extra)
        cfg = _write(tmp_path, "c.json", {"mcpServers": {"s": entry}})
        proc, report = _scan_json(tmp_path, cfg)
        assert [f["issue"] for f in report["findings"]] == ["BROAD-ENV"], \
            (extra, report["findings"])


# R6. Disabled flag parsing ------------------------------------------------

def test_disabled_string_false_is_not_disabled(tmp_path):
    cfg = _write(tmp_path, "c.json", {"mcpServers": {
        "s": {"command": "python3", "disabled": "false"}}})
    proc, report = _scan_json(tmp_path, cfg)
    assert proc.returncode == 0, out_text(proc)
    assert report["findings"] == []


def test_disabled_string_true_is_disabled(tmp_path):
    cfg = _write(tmp_path, "c.json", {"mcpServers": {
        "s": {"command": "python3", "disabled": "true"}}})
    proc, report = _scan_json(tmp_path, cfg)
    assert [f["issue"] for f in report["findings"]] == ["DISABLED"]


# R7. $HOME command expansion ------------------------------------------------

def test_dollar_home_command_that_exists_is_not_missing(tmp_path,
                                                        monkeypatch):
    home = Path(tmp_path) / "fakehome"
    tool = home / "bin" / "faketool-9f3k"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\n")
    monkeypatch.setenv("HOME", str(home))
    cfg = _write(tmp_path, "c.json", {"mcpServers": {
        "s": {"command": "$HOME/bin/faketool-9f3k"}}})
    proc, report = _scan_json(tmp_path, cfg)
    assert proc.returncode == 0, out_text(proc)
    assert report["findings"] == []


# R8. Report re-render robustness --------------------------------------------

def test_report_malformed_structure_exits_2_without_traceback(tmp_path):
    for raw in ('{"tool": "ghostmcpdoctor", "findings": "notalist",'
                ' "configs": []}',
                '{"tool": "ghostmcpdoctor", "findings": [[]],'
                ' "configs": []}',
                '[1, 2, 3]'):
        src = _write(tmp_path, "bad.json", {})  # placeholder, overwritten
        src.write_text(raw)
        proc = run_cli(["report", src, "--out-dir", Path(tmp_path) / "o"],
                       cwd=tmp_path)
        assert proc.returncode == 2, (raw, out_text(proc))
        assert "traceback" not in out_text(proc).lower(), raw
        assert "error" in out_text(proc).lower(), raw


# R9. Same file, two spellings -------------------------------------------------

def test_same_file_two_spellings_scans_once(tmp_path):
    cfg = copy_fixture(tmp_path, "clean")
    target = cfg / "mcp.json"
    rel = os.path.relpath(target, tmp_path)
    proc = run_cli(["scan", rel, str(target), "--no-report", "--json"],
                   cwd=tmp_path)
    assert proc.returncode == 0, out_text(proc)
    report = json.loads(proc.stdout)
    assert report["summary"]["configs_scanned"] == 1
    assert report["findings"] == []


# Windows-style path args -------------------------------------------------------

def test_windows_style_script_arg_is_a_missing_file(tmp_path):
    cfg = _write(tmp_path, "c.json", {"mcpServers": {
        "s": {"command": "python3",
              "args": ["scripts\\definitely_missing_9f3k.py"]}}})
    proc, report = _scan_json(tmp_path, cfg)
    assert [f["issue"] for f in report["findings"]] == ["MISSING-FILE"]
