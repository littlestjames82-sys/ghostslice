"""Hardening regression tests (Oct 18, 2026 improvement pass).

Each test pins a bug found by auditing the build / check / MCP /
closure / secrets code paths against the hard rules in PLAN.md:

- a bundle path is data this tool did not write: it must never be
  able to steer a copy outside the output tree, or onto the source
  file itself, or onto the fixture's own record files;
- a symlinked output directory must not smuggle writes into the
  source project;
- ``check`` on a malformed fixture manifest is "could not check"
  (exit 2 / CheckError), never a traceback;
- the MCP server must survive malformed JSON-RPC lines;
- the Go module cache must follow go.mod edits in a long-lived
  process;
- the secret scan must see .env-style unquoted assignments,
  current provider token shapes, and UTF-16 content, without
  flagging bare identifier references in code.

Unlike the black-box suite, these import the package internals
(from ``src/``) because several bugs live below the CLI surface.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

from ghostfixture.build import (  # noqa: E402
    CheckError, FixtureError, build_fixture, check_fixture)
from ghostfixture.closure import imports_of  # noqa: E402
from ghostfixture.mcp_server import serve  # noqa: E402
from ghostfixture.secrets import scan_bytes  # noqa: E402


def _project(tmp_path, files, name="proj"):
    proj = tmp_path / name
    for rel, text in files.items():
        f = proj / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return proj


def _bundle(tmp_path, proj, entries, name="bundle"):
    bundle = tmp_path / name
    bundle.mkdir(parents=True, exist_ok=True)
    files = [{"path": rel, "mode": mode, "sha256": ""}
             for rel, mode in entries]
    (bundle / "manifest.json").write_text(
        json.dumps({"files": files, "root": str(proj)}), encoding="utf-8")
    return bundle


# ------------------------------------------------------- path steering

def test_dotdot_bundle_path_cannot_write_outside_the_output_tree(tmp_path):
    # Project nested deeper than the output dir: "../proj/file.py"
    # resolves INSIDE the project but would land OUTSIDE the output
    # tree if joined to it naively.
    proj = _project(tmp_path, {"file.py": "X = 1\n"}, name="a/b/proj")
    bundle = _bundle(tmp_path, proj, [("../proj/file.py", "full")])
    out = tmp_path / "out"
    manifest = build_fixture(proj, bundle, out)
    assert manifest["included"] == []
    assert [(e["path"], e["reason"]) for e in manifest["left_out"]] == [
        ("../proj/file.py", "outside-root")]
    assert not (tmp_path / "proj").exists()  # nothing escaped the out tree
    assert sorted(p.name for p in out.iterdir()) == [
        "FIXTURE.md", "fixture-manifest.json"]


def test_absolute_bundle_path_never_touches_the_source_file(tmp_path):
    proj = _project(tmp_path, {"abs.py": "Z = 3\n"})
    src = proj / "abs.py"
    before_bytes, before_mtime = src.read_bytes(), src.stat().st_mtime_ns
    bundle = _bundle(tmp_path, proj, [(str(src), "full")])
    out = tmp_path / "out"
    manifest = build_fixture(proj, bundle, out)
    assert manifest["included"] == []
    assert manifest["left_out"][0]["reason"] == "outside-root"
    assert src.read_bytes() == before_bytes
    assert src.stat().st_mtime_ns == before_mtime  # never rewritten in place
    assert not list(out.rglob("abs.py"))


def test_record_file_names_are_left_out_and_fresh_fixture_checks_clean(tmp_path):
    proj = _project(tmp_path, {
        "FIXTURE.md": "MY OWN NOTES\n",
        "fixture-manifest.json": "{\"mine\": true}\n",
        "real.py": "R = 1\n",
    })
    bundle = _bundle(tmp_path, proj, [
        ("FIXTURE.md", "full"), ("fixture-manifest.json", "full"),
        ("real.py", "full")])
    out = tmp_path / "out"
    manifest = build_fixture(proj, bundle, out)
    assert [e["path"] for e in manifest["included"]] == ["real.py"]
    assert {(e["path"], e["reason"]) for e in manifest["left_out"]} == {
        ("FIXTURE.md", "reserved-output-name"),
        ("fixture-manifest.json", "reserved-output-name"),
    }
    assert check_fixture(out)["ok"]  # a fresh fixture must verify


# ------------------------------------------------------- output location

def test_output_path_that_is_a_file_is_a_clean_fixture_error(tmp_path):
    proj = _project(tmp_path, {"g.py": "G = 1\n"})
    bundle = _bundle(tmp_path, proj, [("g.py", "full")])
    out = tmp_path / "outfile"
    out.write_text("i am a file", encoding="utf-8")
    with pytest.raises(FixtureError, match="not a directory"):
        build_fixture(proj, bundle, out)


def test_symlinked_output_into_the_project_is_refused(tmp_path):
    proj = _project(tmp_path, {"s.py": "S = 1\n"})
    (proj / "inner").mkdir()
    bundle = _bundle(tmp_path, proj, [("s.py", "full")])
    link = tmp_path / "linkout"
    link.symlink_to(proj / "inner", target_is_directory=True)
    with pytest.raises(FixtureError, match="inside the project"):
        build_fixture(proj, bundle, link)
    assert list((proj / "inner").iterdir()) == []  # project untouched


# ------------------------------------------------------- check robustness

@pytest.mark.parametrize("content", [
    '["not", "an", "object"]',
    '"just a string"',
    '{"included": "oops"}',
    '{"included": {"a": 1}}',
    '{"excluded_flagged": 42}',
])
def test_check_on_structurally_bad_manifest_raises_check_error(tmp_path, content):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "fixture-manifest.json").write_text(content, encoding="utf-8")
    with pytest.raises(CheckError):
        check_fixture(fixture)


def test_check_never_reads_an_escaping_included_path(tmp_path):
    # A manifest entry pointing outside the fixture at a real file
    # whose hash DOES match must still be reported, not verified.
    import hashlib
    secret = tmp_path / "secret.py"
    secret.write_text("S = 1\n", encoding="utf-8")
    sha = hashlib.sha256(secret.read_bytes()).hexdigest()
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "fixture-manifest.json").write_text(json.dumps(
        {"included": [{"path": "../secret.py", "sha256": sha}]}),
        encoding="utf-8")
    result = check_fixture(fixture)
    assert not result["ok"]
    assert any("../secret.py" in p for p in result["problems"])


def test_cli_check_on_bad_manifest_exits_2_without_traceback(
        tmp_path, requires_cli):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "fixture-manifest.json").write_text(
        '["not", "an", "object"]', encoding="utf-8")
    proc = helpers.check_fixture(fixture)
    assert proc.returncode == 2, helpers.combined(proc)
    assert "Traceback" not in helpers.combined(proc)


# ------------------------------------------------------- MCP robustness

def test_mcp_server_survives_malformed_jsonrpc_lines():
    lines = (
        '["not", "a", "request", "object"]\n'
        '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": [1, 2]}\n'
        '{"jsonrpc": "2.0", "id": 2, "method": "tools/call", '
        '"params": {"name": "check_fixture", "arguments": "oops"}}\n'
        '{"jsonrpc": "2.0", "id": 3, "method": "tools/list"}\n'
    )
    out = io.StringIO()
    serve(stdin=io.StringIO(lines), stdout=out)  # must not raise
    replies = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
    by_id = {r["id"]: r for r in replies}
    assert by_id[2]["result"]["isError"] is True  # bad arguments, cleanly
    assert by_id[3]["result"]["tools"]  # server still alive afterwards


# ------------------------------------------------------- Go closure cache

def test_go_module_resolution_follows_go_mod_edits(tmp_path):
    root = tmp_path / "goproj"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "s.go").write_text("package sub\n", encoding="utf-8")
    (root / "go.mod").write_text("module example.com/one\n", encoding="utf-8")
    found, _ = imports_of(root, "main.go",
                          'package main\nimport "example.com/one/sub"\n')
    assert found == ["sub/s.go"]
    (root / "go.mod").write_text("module example.com/two\n", encoding="utf-8")
    found, external = imports_of(
        root, "main.go", 'package main\nimport "example.com/two/sub"\n')
    assert found == ["sub/s.go"]  # no stale module path from the cache
    assert external == []


# ------------------------------------------------------- secret scan

def test_env_style_unquoted_assignment_is_flagged():
    assert scan_bytes(b"API_SECRET=Zx9Qw8Er7Ty2Ui5Op3As6Df1Gh\n") == [
        "sensitive-assignment"]
    assert scan_bytes(b"export DB_PASSWORD=9f86d081884c7d659a2feaa0c55ad015\n") == [
        "sensitive-assignment"]


def test_bare_identifier_reference_is_not_flagged():
    # Code that REFERENCES a value is not a literal secret, quoted
    # or not; flagging it would exclude ordinary source files.
    assert scan_bytes(b"api_token=some_configured_token_value_here\n") == []
    assert scan_bytes(b"token = get_token()\n") == []


@pytest.mark.parametrize("blob,expected", [
    (b"github_pat_11ABCDEFG0aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcd\n",
     "github-token"),
    (b"glpat-AbCdEfGhIjKlMnOpQrStUv\n", "gitlab-token"),
    (b"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
     b"dozjgNryP4J3jVmNHl0w5N_XgL0n3AAA\n", "jwt"),
])
def test_current_token_shapes_are_flagged(blob, expected):
    assert expected in scan_bytes(blob)


def test_utf16_encoded_secret_is_flagged():
    line = "t = 'ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'\n"
    assert "github-token" in scan_bytes(line.encode("utf-16"))  # with BOM
    assert "github-token" in scan_bytes(line.encode("utf-16-le"))  # without
