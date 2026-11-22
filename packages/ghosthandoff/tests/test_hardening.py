"""Hardening regressions (Oct 18, 2026 improvement wave, harden lane).

Each test pins a bug reproduced against the pristine build:

1. ``--base`` option injection: a base value shaped like a git option
   (``--output=<path>``) was passed through to ``git diff`` as an
   option, and git wrote the diff to a file outside the output
   directory. The tool's contract is that it writes only the two pack
   files, only in the output directory.
2. A repo with no commits yet: git's status header reads
   ``## No commits yet on <branch>``, and the pack stated that whole
   sentence as the branch name.
3. Redaction bypass: the GhostVerify verdict value and commit author
   names reached both pack files raw, without the redaction pass
   every other quoted field goes through.
4. Symlink escape: the marker scan followed a symlink planted inside
   the project and quoted marker text from a file outside the project
   tree; the pack claims to scan the project's own files.
5. MCP robustness: a valid-JSON non-object line, a ``tools/call``
   with non-dict params, and a call with a non-string ``since`` each
   crashed the stdio server outright instead of being answered or
   skipped, killing every later request on the connection.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402

import helpers  # noqa: E402

pytestmark = pytest.mark.skipif(
    not helpers.cli_available(),
    reason="ghosthandoff CLI not discoverable (see REPORT_B.md)")

CANARY = "hunter2hunter2"


def build_pack(project: Path, tmp_path: Path, *extra: str,
               name: str = "pack-out") -> Path:
    outdir = tmp_path / name
    proc = helpers.run_cli(
        ["pack", str(project), "-o", str(outdir), *extra], cwd=tmp_path)
    assert proc.returncode == 0, (
        f"pack exited {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    return outdir


def pack_raw_texts(outdir: Path) -> tuple[str, str]:
    md, js = helpers.find_pack(outdir)
    assert md is not None and js is not None
    return (md.read_text(encoding="utf-8"),
            js.read_text(encoding="utf-8"))


# ---------------------------------------------------------- 1. --base

def test_pack_base_option_shaped_value_writes_nothing(clean_repo, tmp_path):
    """--base=--output=<path> must not make git write a file anywhere."""
    target = tmp_path / "injected"
    build_pack(clean_repo, tmp_path, f"--base=--output={target}")
    leftovers = [p for p in tmp_path.iterdir()
                 if p.name.startswith("injected")]
    assert leftovers == [], (
        f"pack run wrote files outside the output directory: {leftovers}")


def test_pack_base_valid_ref_still_reports_diff(fixture_repo, tmp_path):
    """The guard must not break a legitimate --base."""
    outdir = build_pack(fixture_repo, tmp_path, "--base", "HEAD")
    md_text, _ = pack_raw_texts(outdir)
    assert "Diff vs HEAD" in md_text


# ------------------------------------------------- 2. empty-repo branch

def test_pack_empty_repo_reports_real_branch_name(tmp_path):
    """A repo with no commits: the branch is the initial branch name,
    not git's whole 'No commits yet on ...' header sentence."""
    repo = tmp_path / "empty-project"
    repo.mkdir()
    helpers.git(repo, "init", "-q", "-b", "fresh-start")
    outdir = build_pack(repo, tmp_path)
    data = helpers.load_pack_json(outdir)
    strings = helpers.all_strings(data)
    assert any(s == "fresh-start" for s in strings), strings
    md_text, _ = pack_raw_texts(outdir)
    assert "- Branch: fresh-start" in md_text
    assert "No commits yet on" not in md_text


# ------------------------------------------------------- 3. redaction

def test_pack_redacts_secret_shape_in_verdict(tmp_path):
    """The verify verdict is quoted into both pack files (report entry
    and open-loop detail): it must pass the redaction pass."""
    project = tmp_path / "verdict-project"
    project.mkdir()
    (project / "app.py").write_text("x = 1\n", encoding="utf-8")
    (project / "verify-report.json").write_text(json.dumps({
        "tool": "ghostverify",
        "verdict": f"failed password={CANARY}",
    }), encoding="utf-8")
    outdir = build_pack(project, tmp_path)
    md_text, json_text = pack_raw_texts(outdir)
    assert CANARY not in md_text
    assert CANARY not in json_text
    # The cleaned verdict is still a failing verdict, so the loop fires.
    assert "latest recorded GhostVerify verdict" in md_text


def test_pack_redacts_secret_shape_in_commit_author(tmp_path):
    """Commit author names are free text quoted into both pack files:
    they must pass the redaction pass like subjects already do."""
    repo = tmp_path / "author-project"
    repo.mkdir()
    helpers.git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("hi\n", encoding="utf-8")
    evil = {"GIT_AUTHOR_NAME": f"Evil password={CANARY}",
            "GIT_COMMITTER_NAME": f"Evil password={CANARY}"}
    helpers.git(repo, "add", "-A")
    helpers.git(repo, "commit", "-q", "-m", "one", env_extra=evil)
    outdir = build_pack(repo, tmp_path)
    md_text, json_text = pack_raw_texts(outdir)
    assert CANARY not in md_text
    assert CANARY not in json_text
    assert "one" in md_text  # the commit itself is still reported


# --------------------------------------------------- 4. symlink escape

def test_pack_marker_scan_does_not_follow_symlink_out_of_project(tmp_path):
    """A symlink inside the project pointing outside it must not let
    the scan quote files that are not part of the project."""
    project = tmp_path / "link-project"
    project.mkdir()
    (project / "real.py").write_text(
        "# TODO: inside marker\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text(
        "# TODO: outside canary marker\n", encoding="utf-8")
    try:
        (project / "link.py").symlink_to(outside / "secret.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    outdir = build_pack(project, tmp_path)
    md_text, json_text = pack_raw_texts(outdir)
    assert "outside canary marker" not in md_text
    assert "outside canary marker" not in json_text
    assert "inside marker" in md_text  # real project files still scan


def test_pack_report_files_do_not_follow_symlink_out_of_project(tmp_path):
    """The named report files are read from the project root; a planted
    symlink there must not pull an outside file's verdict into the pack."""
    project = tmp_path / "report-link-project"
    project.mkdir()
    (project / "app.py").write_text("x = 1\n", encoding="utf-8")
    outside = tmp_path / "outside-report.json"
    outside.write_text(json.dumps({
        "tool": "ghostverify", "verdict": "outside-verdict-canary",
    }), encoding="utf-8")
    try:
        (project / "verify-report.json").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    outdir = build_pack(project, tmp_path)
    md_text, json_text = pack_raw_texts(outdir)
    assert "outside-verdict-canary" not in md_text
    assert "outside-verdict-canary" not in json_text


# ------------------------------------------------------ 5. MCP server

def test_mcp_survives_malformed_requests(clean_repo, tmp_path):
    """Malformed requests get an answer or a skip, never a dead server:
    a later ping on the same connection must still be answered."""
    prefix = helpers.cli_prefix()
    env = helpers.cli_env()
    out_dir = tmp_path / "mcp-out"
    lines = [
        "[]",  # valid JSON, not an object
        '"just a string"',
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": []}),  # non-dict params
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "build_handoff",
                               "arguments": {"project": str(clean_repo),
                                             "out": str(out_dir),
                                             "since": 123}}}),  # non-string arg
        json.dumps({"jsonrpc": "2.0", "id": 99, "method": "ping"}),
    ]
    proc = subprocess.Popen(
        prefix + ["mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env=env)
    try:
        out, err = proc.communicate("\n".join(lines) + "\n", timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError("mcp server did not finish within 20s")
    assert proc.returncode == 0, f"mcp server died:\n{err}"
    answered = set()
    for line in out.splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict) and "id" in msg:
            answered.add(msg["id"])
    assert 99 in answered, f"ping after malformed requests unanswered: {out}"
    assert 2 in answered, f"bad tools/call produced no response: {out}"
