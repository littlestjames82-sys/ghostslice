"""v1.0 (G20): doctor, completions, the scan/fit layout polish,
and the release-readiness pins.

Doctor fixtures are engineered per check: the payload's counts,
the CLI's exit code, and the printed remedies must agree, and
doctor must never write. Completions are pinned twice over: every
subcommand the parser knows appears in both generated scripts,
and the shipped copies in examples/completions/ are byte-equal
to fresh output (drift is a test failure, not a surprise).
The scan/fit layouts are output-only changes; the pins below are
the deliberate new layout (recorded in audits/G20_audit.md), and
the scan --json key set is pinned unchanged.
"""
import json
import re
from pathlib import Path

import pytest

from ghostslice import __version__
from ghostslice.cli import main as cli_main
from ghostslice.doctor import checkout_pyproject, run_doctor
from ghostslice.scanner import scan as scan_project

REPO = Path(__file__).resolve().parent.parent


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture()
def proj(tmp_path):
    _write(tmp_path, "main.py", "def main():\n    return 1\n")
    _write(tmp_path, "util.py", "def helper():\n    return 42\n")
    return tmp_path


def _cli(argv, capsys):
    code = cli_main(argv)
    out, err = capsys.readouterr()
    return code, out, err


def _tree_snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): p.stat().st_size
            for p in sorted(root.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------
# version agreement (the drift doctor exists to catch)

def test_version_is_1_0_0_and_pyproject_agrees():
    assert __version__ == "1.0.0"
    py = checkout_pyproject()
    assert py is not None, "tests run from the source checkout"
    from ghostslice.doctor import _project_section_version
    name, version = _project_section_version(py)
    assert name == "ghostslice"
    assert version == __version__


# ---------------------------------------------------------------
# doctor

def test_doctor_healthy_project(proj, capsys):
    code, out, _ = _cli(["doctor", str(proj)], capsys)
    assert code == 0
    payload = run_doctor(proj)
    assert payload["ok"] and payload["counts"]["fail"] == 0
    for label in ("Python runtime", "GhostSlice version",
                  "Token estimator", "Price table", "Profile",
                  "Content cache", "Savings ledger", "Plugins",
                  "Git", "Workspaces"):
        assert label in out
    assert "healthy" in out


def test_doctor_json_shape_and_exit_agreement(proj, capsys):
    code, out, _ = _cli(["doctor", str(proj), "--json"], capsys)
    payload = json.loads(out)
    assert code == (0 if payload["ok"] else 1)
    assert {c["id"] for c in payload["checks"]} == {
        "python", "version", "estimator", "prices", "profile",
        "cache", "ledger", "plugins", "git", "workspace"}
    for c in payload["checks"]:
        assert c["status"] in ("ok", "warn", "fail")
        if c["status"] != "ok":
            assert c["remedy"]


def test_doctor_broken_profile_fails_with_remedy(proj, capsys):
    _write(proj, ".ghostslice.json", '{"budget_tokens": {"x": 1}}')
    code, out, _ = _cli(["doctor", str(proj)], capsys)
    assert code == 1
    assert "[FAIL] Profile" in out
    assert "remedy:" in out
    payload = run_doctor(proj)
    prof = next(c for c in payload["checks"] if c["id"] == "profile")
    assert prof["status"] == "fail" and "budget_tokens" in prof["detail"]


def test_doctor_valid_profile_lists_keys(proj):
    _write(proj, ".ghostslice.json",
           '{"budget_tokens": 5000, "model": "claude-sonnet"}')
    payload = run_doctor(proj)
    prof = next(c for c in payload["checks"] if c["id"] == "profile")
    assert prof["status"] == "ok"
    assert "budget_tokens" in prof["detail"] and "model" in prof["detail"]


def test_doctor_survives_broken_prices(tmp_path, proj, monkeypatch, capsys):
    # find_prices_file prefers <cwd>/prices.json; a corrupt one
    # there must not kill doctor before it can report (the CLI's
    # early exit-2 path steps aside for doctor by design).
    _write(tmp_path, "prices.json", "{not json")
    monkeypatch.chdir(tmp_path)
    code, out, _ = _cli(["doctor", str(proj)], capsys)
    assert code == 1
    assert "[FAIL] Price table" in out
    assert "Python runtime" in out  # the full report still printed
    payload = run_doctor(proj)
    prices = next(c for c in payload["checks"] if c["id"] == "prices")
    assert prices["status"] == "fail" and "remedy" in prices


def test_doctor_ledger_corrupt_and_mix_warn(proj):
    _write(proj, ".ghostslice-history.jsonl",
           '{"before_tokens": 100, "after_tokens": 40}\n'
           "this is not json\n")
    payload = run_doctor(proj)
    led = next(c for c in payload["checks"] if c["id"] == "ledger")
    assert led["status"] == "warn"
    assert "corrupt" in led["detail"]
    assert "estimator mix" in led["detail"]
    assert payload["ok"]  # warnings never fail the run


def test_doctor_gitignore_gap_warns_then_ok(proj):
    (proj / ".git").mkdir()
    payload = run_doctor(proj)
    git = next(c for c in payload["checks"] if c["id"] == "git")
    assert git["status"] == "warn"
    assert ".claude_context" in git["detail"]
    _write(proj, ".gitignore", ".claude_context/\n.ghostslice-cache/\n")
    git = next(c for c in run_doctor(proj)["checks"] if c["id"] == "git")
    assert git["status"] == "ok"


def test_doctor_cache_stats_after_scan(proj):
    payload = run_doctor(proj)
    cache = next(c for c in payload["checks"] if c["id"] == "cache")
    assert "no cache yet" in cache["detail"]
    from ghostslice.cache import open_cache
    cache_obj = open_cache(proj)
    assert cache_obj is not None
    result = scan_project(proj, cache=cache_obj)
    assert result.files
    payload = run_doctor(proj)
    cache = next(c for c in payload["checks"] if c["id"] == "cache")
    assert cache["status"] == "ok"
    assert "entr(ies)" in cache["detail"]


def test_doctor_plugin_missing_fails_and_valid_loads(proj, capsys):
    _write(proj, ".ghostslice.json", '{"plugins": ["nope.py"]}')
    code, out, _ = _cli(["doctor", str(proj)], capsys)
    assert code == 1
    assert "[FAIL] Plugins" in out
    _write(proj, "lua_lite.py",
           'LANGUAGE = "lua"\nEXTENSIONS = [".lua"]\n\n\n'
           "def slice_text(path, text, mode):\n    return text\n")
    _write(proj, ".ghostslice.json", '{"plugins": ["lua_lite.py"]}')
    payload = run_doctor(proj)
    plug = next(c for c in payload["checks"] if c["id"] == "plugins")
    assert plug["status"] == "ok" and "lua" in plug["detail"]


def test_doctor_never_writes(proj):
    _write(proj, ".ghostslice.json", '{"budget_tokens": 100}')
    _write(proj, ".ghostslice-history.jsonl",
           '{"before_tokens": 10, "after_tokens": 5}\n')
    (proj / ".git").mkdir()
    before = _tree_snapshot(proj)
    payload = run_doctor(proj)
    assert payload["checks"]
    assert _tree_snapshot(proj) == before
    assert not (proj / ".ghostslice-cache").exists()


def test_doctor_missing_project_is_usage_error(capsys):
    code, _, err = _cli(["doctor", "/nonexistent/gs-path"], capsys)
    assert code == 2
    assert "no such project" in err


def test_doctor_on_this_repo_is_healthy():
    # Dogfood pin: the release tree itself must pass its own
    # doctor (this is what catches version drift like the
    # pyproject 0.16.0 the readiness audit found).
    payload = run_doctor(REPO)
    fails = [c for c in payload["checks"] if c["status"] == "fail"]
    assert payload["ok"], fails


# ---------------------------------------------------------------
# completions

def _help_commands(capsys) -> set:
    with pytest.raises(SystemExit):
        cli_main(["--help"])
    out = capsys.readouterr().out
    m = re.search(r"\{([^}]+)\}", out)
    assert m, "argparse help lists subcommands in braces"
    return set(m.group(1).split(","))


def test_completions_cover_every_command_and_flag(capsys):
    commands = _help_commands(capsys)
    assert len(commands) >= 25
    for shell in ("bash", "zsh"):
        code, out, _ = _cli(["completions", shell], capsys)
        assert code == 0
        for name in commands:
            assert name in out, (shell, name)
        for flag in ("--fit", "--trend", "--strict", "--pr-comment",
                     "--allow-plugin-override", "--top", "--json"):
            assert flag in out, (shell, flag)
        # nested subcommands ride along
        assert "stats" in out and "clear" in out


def test_completions_deterministic_and_match_shipped(capsys):
    for shell, fname in (("bash", "ghostslice.bash"),
                         ("zsh", "ghostslice.zsh")):
        _, first, _ = _cli(["completions", shell], capsys)
        _, second, _ = _cli(["completions", shell], capsys)
        assert first == second
        shipped = (REPO / "examples" / "completions" / fname).read_text(
            encoding="utf-8")
        assert shipped == first, (
            f"examples/completions/{fname} drifted from the parser; "
            f"regenerate with: ghostslice completions {shell}")


# ---------------------------------------------------------------
# scan layout (v1.0 polish; --json pinned unchanged)

def _many_files(root: Path, n=20) -> Path:
    for i in range(n):
        words = " ".join(f"tok{j}" for j in range((i + 1) * 40))
        _write(root, f"file{i:02d}.py", f"# {words}\nVALUE = {i}\n")
    return root


def test_scan_top_n_tail_and_summary_box(tmp_path, capsys):
    root = _many_files(tmp_path)
    result = scan_project(root)
    code, out, _ = _cli(["scan", str(root)], capsys)
    assert code == 0
    row_re = r"^\s+\d[\d,]*\s+\d+\s+[\d.]+%\s+█*\s+file\d\d\.py"
    rows = [ln for ln in out.splitlines() if re.match(row_re, ln)]
    assert len(rows) == 15
    tail = next(ln for ln in out.splitlines() if "more files" in ln)
    rest = result.files[15:]
    assert f"and {len(rest)} more files" in tail
    assert f"{sum(f.tokens for f in rest):,} estimated tokens" in tail
    # largest file's heat bar fills the width
    assert "█" * 16 in rows[0]
    assert "Largest file:" in out and result.files[0].path in out
    assert "Estimated tokens:" in out
    # the summary box closes the output
    last = out.rstrip().splitlines()[-1].strip()
    assert last.startswith("+") and set(last) <= set("+-")


def test_scan_top_flag_and_validation(tmp_path, capsys):
    root = _many_files(tmp_path)
    code, out, _ = _cli(["scan", str(root), "--top", "3"], capsys)
    assert code == 0
    row_re = r"^\s+\d[\d,]*\s+\d+\s+[\d.]+%\s+█*\s+file\d\d\.py"
    rows = [ln for ln in out.splitlines() if re.match(row_re, ln)]
    assert len(rows) == 3
    assert "and 17 more files" in out
    code, _, err = _cli(["scan", str(root), "--top", "0"], capsys)
    assert code == 2 and "--top" in err


def test_scan_small_project_no_tail(tmp_path, capsys):
    _write(tmp_path, "only.py", "x = 1\n")
    code, out, _ = _cli(["scan", str(tmp_path)], capsys)
    assert code == 0
    assert "more files" not in out
    assert "Top 1 of 1 files" in out
    assert "Largest file: only.py" in out


def test_scan_empty_project(tmp_path, capsys):
    code, out, _ = _cli(["scan", str(tmp_path)], capsys)
    assert code == 0
    assert "Files: 0" in out


def test_scan_json_keys_unchanged(tmp_path, capsys):
    _write(tmp_path, "a.py", "x = 1\n")
    code, out, _ = _cli(["scan", str(tmp_path), "--json"], capsys)
    assert code == 0
    payload = json.loads(out)
    for key in ("root", "files", "total_tokens", "token_method",
                "recommendations", "secrets", "duplicates",
                "profile", "history"):
        assert key in payload


# ---------------------------------------------------------------
# fit report layout (content identical, table layout new)

def test_fit_report_table_layout(tmp_path, capsys):
    for i in range(6):
        body = "\n".join(f"def fn{i}_{j}():\n    return {j}\n"
                         for j in range(30))
        _write(tmp_path, f"mod{i}.py", body)
    bundle = tmp_path / "bundle"
    code, out, _ = _cli(
        ["export", str(tmp_path), "-o", str(bundle), "--fit", "300"],
        capsys)
    assert "Fit report (target: 300 estimated tokens):" in out
    assert "before" in out and "after" in out and "result" in out
    assert "downgrade steps:" in out
    manifest = json.loads((bundle / "manifest.json").read_text(
        encoding="utf-8"))
    fit = manifest["fit"]
    assert f"{fit['before_tokens']:,}" in out
    assert f"{fit['after_tokens']:,}" in out
    for step, count in fit["steps"].items():
        assert step in out and str(count) in out


def test_no_fit_report_without_fit(tmp_path, capsys):
    _write(tmp_path, "a.py", "x = 1\n")
    code, out, _ = _cli(
        ["export", str(tmp_path), "-o", str(tmp_path / "b")], capsys)
    assert code == 0
    assert "Fit report" not in out


# ---------------------------------------------------------------
# README coverage: every command documented, feature map honest

def test_readme_documents_every_command(capsys):
    commands = _help_commands(capsys)
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    missing = [c for c in commands if f"ghostslice {c}" not in readme]
    assert not missing, missing
    assert "## Quickstart" in readme
    assert "## What's in 1.0" in readme
    assert "## Troubleshooting" in readme


def test_feature_map_lists_only_real_commands(capsys):
    commands = _help_commands(capsys)
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    section = readme.split("## What's in 1.0", 1)[1].split("## ", 1)[0]
    listed = set(re.findall(r"\| `ghostslice ([a-z-]+)`", section))
    assert listed == commands, (listed ^ commands)
