"""JSONC support (deepen lane): comments + trailing commas.

Editor-written MCP configs (VS Code, Cursor) are commonly JSONC:
``//`` / ``/* */`` comments and trailing commas. Before this change
such a readable config degraded to PARSE-ERROR. Now strict JSON is
tried first and JSONC is a fallback in the scanner only.

Hard rules still hold throughout: read-only, no content echoed on a
parse error, and no secret value (in an env block OR in a comment)
ever appears on any output surface.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from conftest import out_text, run_cli  # noqa: E402

from ghostmcpdoctor.scanner import strip_jsonc  # noqa: E402

COMMENT_CANARY = "FAKE-COMMENT-CANARY-DOCTOR-a1b2-never-print"
ENV_CANARY = "FAKE-JSONC-ENV-CANARY-DOCTOR-c3d4-never-print"


def _scan_json(tmp_path, target, *extra):
    proc = run_cli(["scan", target, "--no-report", "--json", *extra],
                   cwd=tmp_path)
    return proc, json.loads(proc.stdout)


def _write(tmp_path, name, text):
    p = Path(tmp_path) / name
    p.write_text(text, encoding="utf-8")
    return p


CLEAN_JSONC = """{
  // Editor config with comments.
  "mcpServers": {
    /* the docs server
       spans two lines */
    "docs": {
      "command": "python3", // exists on this machine
      "args": ["-m", "example_docs_server",],
      "env": {"EXAMPLE_MODE": "readonly",},
    },
  },
}
"""


def test_jsonc_line_and_block_comments_parse(tmp_path):
    cfg = _write(tmp_path, "mcp.json", CLEAN_JSONC)
    proc, report = _scan_json(tmp_path, cfg)
    assert proc.returncode == 0, out_text(proc)
    assert [s["name"] for s in report["servers"]] == ["docs"]
    assert report["findings"] == []
    assert report["configs"][0]["status"] == "ok"


def test_jsonc_trailing_commas_in_objects_and_arrays_parse(tmp_path):
    cfg = _write(tmp_path, "mcp.json",
                 '{"mcpServers": {"a": {"command": "python3",'
                 ' "args": ["-m", "x",],},},}')
    proc, report = _scan_json(tmp_path, cfg)
    assert proc.returncode == 0, out_text(proc)
    assert report["servers"][0]["args_count"] == 2


def test_jsonc_commented_out_server_is_not_inventoried(tmp_path):
    cfg = _write(tmp_path, "mcp.json", """{
      "mcpServers": {
        "live": {"command": "python3"}
        // , "ghost": {"command": "ghostmcp-nonexistent-binary-9f3k"}
      }
    }""")
    proc, report = _scan_json(tmp_path, cfg)
    assert proc.returncode == 0, out_text(proc)
    assert [s["name"] for s in report["servers"]] == ["live"]
    assert report["findings"] == []


def test_jsonc_slashes_inside_url_string_are_not_a_comment(tmp_path):
    cfg = _write(tmp_path, "mcp.json",
                 '{\n// leading comment\n"mcpServers": {'
                 '"remote": {"url": "https://api.example.com/mcp"} // tail\n}}')
    proc, report = _scan_json(tmp_path, cfg)
    assert proc.returncode == 0, out_text(proc)
    assert [s["url_host"] for s in report["servers"]] == ["api.example.com"]


def test_jsonc_findings_still_fire_on_jsonc_configs(tmp_path):
    cfg = _write(tmp_path, "mcp.json", """{
      // broad grant, in JSONC clothing
      "mcpServers": {
        "fs": {"command": "npx", "args": ["-y", "server-filesystem", "/"]},
      }
    }""")
    proc, report = _scan_json(tmp_path, cfg)
    assert proc.returncode == 1
    assert "BROAD-FILESYSTEM" in {f["issue"] for f in report["findings"]}


def test_jsonc_secrets_in_env_and_comments_never_leak(tmp_path):
    cfg = _write(tmp_path, "mcp.json", f"""{{
      // old key was {COMMENT_CANARY}, rotated away
      "mcpServers": {{
        "s": {{"command": "python3",
               "env": {{"FAKE_API_KEY": "{ENV_CANARY}"}}}}
      }}
    }}""")
    proc = run_cli(["scan", cfg, "--out-dir", tmp_path / "out"],
                   cwd=tmp_path)
    surfaces = out_text(proc)
    for name in ("mcpdoctor-report.json", "MCPDOCTOR.md"):
        surfaces += (tmp_path / "out" / name).read_text()
    assert COMMENT_CANARY not in surfaces
    assert ENV_CANARY not in surfaces
    # The env key NAME is still reported as present; only values hide.
    assert "FAKE_API_KEY" in surfaces


def test_jsonc_truncated_file_is_still_a_parse_error(tmp_path):
    cfg = _write(tmp_path, "broken.json",
                 '{ // comment\n "mcpServers": { "oops": '
                 '{ "command": "python3", },\n')
    proc, report = _scan_json(tmp_path, cfg)
    assert proc.returncode == 1
    assert [f["issue"] for f in report["findings"]] == ["PARSE-ERROR"]
    assert "python3" not in report["findings"][0]["detail"]


def test_jsonc_unterminated_block_comment_is_parse_error_not_crash(tmp_path):
    cfg = _write(tmp_path, "mcp.json",
                 '{"mcpServers": {"a": {"command": "python3"}} /* oops')
    proc, report = _scan_json(tmp_path, cfg)
    assert proc.returncode == 1
    assert "PARSE-ERROR" in {f["issue"] for f in report["findings"]}


def test_jsonc_bad_container_is_still_a_parse_error(tmp_path):
    cfg = _write(tmp_path, "mcp.json",
                 '// c\n{"mcpServers": ["not", "an", "object",],}')
    proc, report = _scan_json(tmp_path, cfg)
    assert proc.returncode == 1
    assert report["servers"] == []
    assert [f["issue"] for f in report["findings"]] == ["PARSE-ERROR"]


# Direct unit tests for the string-aware stripper ----------------------

def test_strip_jsonc_preserves_comment_markers_inside_strings():
    src = '{"url": "https://h/*x*/y", "a": 1} // gone\n/* gone */'
    out = strip_jsonc(src)
    assert json.loads(out) == {"url": "https://h/*x*/y", "a": 1}


def test_strip_jsonc_preserves_comma_bracket_inside_strings():
    src = '{"a": "x,]", "b": [1, 2,],}'
    assert json.loads(strip_jsonc(src)) == {"a": "x,]", "b": [1, 2]}


def test_strip_jsonc_handles_escaped_quotes_before_comment_markers():
    # The \" does not end the string, so the // after it is still data
    # until the real closing quote; only the trailing // is a comment.
    src = r'{"a": "q\" // still string", "b": 2} // comment'
    assert json.loads(strip_jsonc(src)) == {"a": 'q" // still string', "b": 2}


def test_strip_jsonc_plain_json_is_unchanged_in_meaning():
    src = '{"mcpServers": {"a": {"command": "python3", "args": []}}}'
    assert json.loads(strip_jsonc(src)) == json.loads(src)
