"""Scope audits for v0.1: no execution surface, no auto-approval.

These read Agent A's src/** READ-ONLY (never edited by Agent B) and
drive only --help output. They encode the PLAN's hard gates:
  * no executor: approving never runs, deploys, sends, or dispatches
  * no auto-approval: no flag, rule, timeout, config, or env var that
    produces a decision without an explicit approve/deny + exact hash
  * no delete / clear / undo command that could rewrite history
"""
import os
import subprocess

from conftest import ENTRYPOINT, REPO, run_ga


def _src_text():
    parts = []
    src = REPO / "src" / "ghostapprove"
    for p in sorted(src.glob("*.py")):
        parts.append(p.read_text(errors="replace"))
    return "\n".join(parts)


def _help_text(args, tmp_path):
    if ENTRYPOINT is None:
        import pytest
        pytest.fail("GhostApprove core not ready: no entrypoint")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "src") + os.pathsep + env.get(
        "PYTHONPATH", "")
    proc = subprocess.run(
        ENTRYPOINT + [str(a) for a in args],
        capture_output=True, text=True, timeout=60, env=env,
        cwd=str(tmp_path))
    return (proc.stdout or "") + (proc.stderr or "")


def test_no_execution_machinery_in_core_source():
    text = _src_text()
    for forbidden in ("subprocess", "os.system", "popen", "eval(",
                      "exec(", "socket", "urllib", "requests."):
        assert forbidden not in text, (
            f"core source mentions {forbidden!r}: v0.1 must contain no "
            "execution or network machinery at all")


def test_no_auto_approval_surface_in_core_source():
    text = _src_text().lower()
    for forbidden in ("auto_approve", "autoapprove", "auto-approve",
                      "--yes", "--all", "approve_all", "timeout_approv"):
        assert forbidden not in text, (
            f"core source mentions {forbidden!r}: no auto-approval "
            "path, flag, or rule may exist in v0.1")


def test_cli_has_no_execute_or_delete_verbs(tmp_path):
    help_text = _help_text(["--help"], tmp_path).lower()
    for verb in ("ingest", "list", "show", "approve", "deny", "history"):
        assert verb in help_text
    for verb in ("execute", "run", "deploy", "send", "dispatch",
                 "delete", "clear", "undo", "remove"):
        # Verbs appear as subcommand choices; a bare mention in prose
        # ("executes nothing") is fine and expected.
        assert f"{{{verb}" not in help_text and f",{verb}}}" not in help_text
    approve_help = _help_text(["approve", "--help"], tmp_path).lower()
    assert "--hash" in approve_help
    assert "--yes" not in approve_help and "--all" not in approve_help


def test_auto_approve_env_vars_do_nothing(tmp_path):
    """Even with suggestive env vars set, a request stays pending."""
    from conftest import ingest_example, make_queue, status_of
    queue = make_queue(tmp_path)
    old = dict(os.environ)
    os.environ["GHOSTAPPROVE_AUTO_APPROVE"] = "1"
    os.environ["GHOSTAPPROVE_APPROVE_ALL"] = "true"
    try:
        _, req_id, _ = ingest_example(queue, "ghostbridge-request.json")
    finally:
        os.environ.clear()
        os.environ.update(old)
    assert status_of(queue, req_id) == "pending"
