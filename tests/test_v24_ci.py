"""v0.24 (G19): the CI pack — `ghostslice ci` + workflow samples.

One gate command composing the budget gate, lint, the secret
guard, the fit ladder, and duplicate detection. Fixtures are
engineered per check; the exit-code/JSON agreement battery pins
that the payload's exit_code, the check statuses, and the CLI's
return value can never disagree. Fake secret literals are
assembled from parts so this file itself stays clean under
`ghostslice secrets .` (the canonical AWS example key is NOT
used: the guard deliberately treats it as a documented example,
so the fixture uses a random-shaped key the guard does flag).
"""
import hashlib
import json
from pathlib import Path

import pytest

import ghostslice.ci as ci_mod
from ghostslice.ci import CHECK_IDS, STATUSES, run_ci
from ghostslice.cli import main as cli_main

REPO = Path(__file__).resolve().parent.parent
SAMPLE = REPO / "examples" / "github-action" / "ghostslice-ci.yml"
DOGFOOD = REPO / ".github" / "workflows" / "ghostslice-ci.yml"

BODY30 = "".join(f"def f{i}():\n    return {i}\n\n\n" for i in range(30))
BIG_BODY = "".join(
    f"def g{i}(x):\n    y = x + {i}\n    return y * 2\n\n\n"
    for i in range(90))
SECRET = "AKIA" + "JX7KQ2P9Z4M8" + "W3TN"


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture()
def clean(tmp_path):
    _write(tmp_path, "main.py",
           "from util import helper\n\n\ndef main():\n"
           "    return helper()\n\n\nif __name__ == '__main__':\n"
           "    main()\n")
    _write(tmp_path, "util.py", "def helper():\n    return 42\n")
    return tmp_path


@pytest.fixture()
def secret_proj(tmp_path):
    _write(tmp_path, "main.py",
           f'KEY = "{SECRET}"\n\n\ndef main():\n    return KEY\n')
    return tmp_path


def _status(payload, check_id):
    return next(c["status"] for c in payload["checks"]
                if c["id"] == check_id)


def _snapshot(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return out


# -- the clean run ---------------------------------------------------

def test_clean_project_all_pass_with_budget(clean):
    payload = run_ci(clean, budget=100000)
    assert [c["id"] for c in payload["checks"]] == list(CHECK_IDS)
    assert all(c["status"] == "pass" for c in payload["checks"])
    assert payload["exit_code"] == 0 and payload["ok"]
    assert payload["totals"]["original_tokens"] > \
        payload["totals"]["sliced_tokens"] > 0


def test_no_budget_anywhere_skips_budget_and_fit(clean):
    payload = run_ci(clean)
    assert _status(payload, "budget") == "skipped"
    assert _status(payload, "fit") == "skipped"
    assert "no budget configured" in next(
        c["evidence"] for c in payload["checks"] if c["id"] == "budget")
    # Skips never fail a run.
    assert payload["exit_code"] == 0


def test_budget_boundary_is_exact(clean):
    sliced = run_ci(clean)["totals"]["sliced_tokens"]
    at = run_ci(clean, budget=sliced)
    assert _status(at, "budget") == "pass"
    assert _status(at, "fit") == "pass"
    assert at["exit_code"] == 0
    below = run_ci(clean, budget=sliced - 1)
    assert _status(below, "budget") == "fail"
    assert _status(below, "fit") == "pass"
    assert below["exit_code"] == 1


def test_profile_budget_is_honoured(tmp_path):
    _write(tmp_path, "main.py", BODY30)
    _write(tmp_path, ".ghostslice.json",
           json.dumps({"budget_tokens": 10}))
    payload = run_ci(tmp_path)
    assert _status(payload, "budget") == "fail"
    budget_check = next(c for c in payload["checks"]
                         if c["id"] == "budget")
    assert budget_check["details"]["budget_tokens"] == 10


# -- one fixture per check -------------------------------------------

def test_over_budget_fails_budget_but_fit_can_reach(clean):
    payload = run_ci(clean, budget=10)
    assert _status(payload, "budget") == "fail"
    assert _status(payload, "fit") == "pass"
    assert payload["exit_code"] == 1


def test_unfittable_fails_fit(tmp_path):
    _write(tmp_path, "main.py", BODY30)
    _write(tmp_path, ".ghostslice.json",
           json.dumps({"modes": {"*.py": "full"}}))
    payload = run_ci(tmp_path, budget=30)
    assert _status(payload, "fit") == "fail"
    fit = next(c for c in payload["checks"] if c["id"] == "fit")
    assert fit["details"]["fitted"] is False
    # Logical dependency, pinned on purpose: fit starts from the
    # default selection, so an unreachable budget is always also an
    # exceeded one.
    assert _status(payload, "budget") == "fail"
    assert payload["exit_code"] == 1


def test_lint_error_fails_lint_only(tmp_path):
    _write(tmp_path, "main.py", BODY30)
    _write(tmp_path, ".ghostslice.json", json.dumps({
        "modes": {"*.py": "full"},
        "lint": {"L001": {"severity": "error",
                          "threshold_tokens": 50}}}))
    payload = run_ci(tmp_path, budget=100000)
    assert _status(payload, "lint") == "fail"
    assert _status(payload, "secrets") == "pass"
    assert _status(payload, "budget") == "pass"
    assert payload["exit_code"] == 1


def test_lint_warning_warns_and_strict_promotes(tmp_path):
    _write(tmp_path, "main.py", "X = '" + "a" * 600 + "'\n")
    payload = run_ci(tmp_path, budget=100000)
    assert _status(payload, "lint") == "warn"
    assert payload["exit_code"] == 0
    strict = run_ci(tmp_path, budget=100000, strict=True)
    assert _status(strict, "lint") == "fail"
    assert strict["exit_code"] == 1


def test_secret_fails_by_default(secret_proj):
    payload = run_ci(secret_proj, budget=100000)
    assert _status(payload, "secrets") == "fail"
    check = next(c for c in payload["checks"] if c["id"] == "secrets")
    assert check["details"]["count"] == 1
    # Evidence carries the redacted form only, never the literal.
    assert SECRET not in check["evidence"]
    assert payload["exit_code"] == 1


def test_secret_allow_secrets_downgrades_whole_run(secret_proj):
    payload = run_ci(secret_proj, budget=100000, allow_secrets=True)
    assert _status(payload, "secrets") == "warn"
    # Lint's L005 is the same findings: the flag turns it off for
    # the lint check too, so the run can actually pass.
    assert _status(payload, "lint") == "pass"
    lint = next(c for c in payload["checks"] if c["id"] == "lint")
    assert lint["details"]["l005_disabled_by_allow_secrets"] is True
    assert payload["exit_code"] == 0


def test_secret_fail_on_secrets_flag_matches_default(secret_proj,
                                                     capsys):
    code = cli_main(["ci", str(secret_proj), "--budget", "100000",
                     "--fail-on-secrets"])
    assert code == 1
    assert "[FAIL] secrets" in capsys.readouterr().out


def test_duplicates_group_above_floor_warns(tmp_path):
    _write(tmp_path, "a.py", BIG_BODY)
    _write(tmp_path, "b.py", BIG_BODY)
    _write(tmp_path, "main.py",
           "import a\nimport b\n\n\ndef main():\n"
           "    return a.g0(1) + b.g0(2)\n")
    payload = run_ci(tmp_path, budget=100000)
    assert _status(payload, "duplicates") == "warn"
    dup = next(c for c in payload["checks"] if c["id"] == "duplicates")
    assert dup["details"]["groups"][0]["files"] == ["a.py", "b.py"]
    assert dup["details"]["groups"][0]["potential_savings"] >= \
        ci_mod.DUP_FLOOR_TOKENS
    assert payload["exit_code"] == 0  # warnings never fail the run


def test_duplicates_below_floor_passes(clean):
    payload = run_ci(clean, budget=100000)
    assert _status(payload, "duplicates") == "pass"


# -- isolation + exit-code agreement ---------------------------------

def test_crashing_check_fails_alone(clean, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(ci_mod, "lint_project", boom)
    payload = run_ci(clean, budget=100000)
    assert [c["id"] for c in payload["checks"]] == list(CHECK_IDS)
    assert _status(payload, "lint") == "fail"
    lint = next(c for c in payload["checks"] if c["id"] == "lint")
    assert "check errored: RuntimeError: boom" in lint["evidence"]
    assert _status(payload, "secrets") == "pass"
    assert payload["exit_code"] == 1


@pytest.mark.parametrize("extra,expect", [
    ([], 0),
    (["--budget", "100000"], 0),
    (["--budget", "10"], 1),
    (["--strict"], 0),
])
def test_cli_exit_codes(clean, extra, expect):
    assert cli_main(["ci", str(clean), *extra]) == expect


def test_exit_code_agreement_battery(clean, secret_proj, capsys):
    scenarios = [
        (clean, []), (clean, ["--budget", "10"]),
        (clean, ["--budget", "100000"]),
        (secret_proj, ["--budget", "100000"]),
        (secret_proj, ["--budget", "100000", "--allow-secrets"]),
    ]
    for root, extra in scenarios:
        code = cli_main(["ci", str(root), "--json", *extra])
        payload = json.loads(capsys.readouterr().out)
        assert payload["exit_code"] == code
        assert payload["ok"] == (code == 0)
        assert [c["id"] for c in payload["checks"]] == list(CHECK_IDS)
        assert all(c["status"] in STATUSES for c in payload["checks"])
        any_fail = any(c["status"] == "fail" for c in payload["checks"])
        assert any_fail == (code == 1)
        counts = {s: 0 for s in STATUSES}
        for c in payload["checks"]:
            counts[c["status"]] += 1
        assert payload["summary"] == counts


def test_usage_errors_exit_2(clean, tmp_path):
    assert cli_main(["ci", str(clean), "--budget", "0"]) == 2
    assert cli_main(["ci", str(clean), "--budget", "-5"]) == 2
    assert cli_main(["ci", str(tmp_path / "missing")]) == 2
    bad = tmp_path / "bad"
    bad.mkdir()
    _write(bad, "main.py", "x = 1\n")
    _write(bad, ".ghostslice.json", '{"budget_tokens": "lots"}')
    assert cli_main(["ci", str(bad)]) == 2


def test_json_and_pr_comment_are_mutually_exclusive(clean):
    with pytest.raises(SystemExit) as exc:
        cli_main(["ci", str(clean), "--json", "--pr-comment"])
    assert exc.value.code == 2


def test_totals_crash_fails_budget_check_alone(clean, monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("totals boom")
    monkeypatch.setattr(ci_mod, "_selection_totals", boom)
    payload = run_ci(clean, budget=100)
    assert _status(payload, "budget") == "fail"
    budget = next(c for c in payload["checks"] if c["id"] == "budget")
    assert "totals boom" in budget["evidence"]
    assert payload["totals"] is None
    assert _status(payload, "secrets") == "pass"
    assert payload["exit_code"] == 1


def test_gitignored_report_is_not_rescanned(clean, tmp_path):
    # Audit F2: an --out report inside the tree is scanned by later
    # runs UNLESS gitignored (the scanner honours .gitignore; the
    # samples advise ignoring the artifact names).
    report = clean / "ghostslice-report.html"
    report.write_text("<html>" + "x" * 5000 + "</html>",
                      encoding="utf-8")
    grown = run_ci(clean, budget=100000)
    _write(clean, ".gitignore", "ghostslice-report.html\n")
    clean_totals = run_ci(clean, budget=100000)
    assert clean_totals["totals"]["original_tokens"] < \
        grown["totals"]["original_tokens"]


# -- output shapes -----------------------------------------------------

def test_text_output_shape(clean, capsys):
    assert cli_main(["ci", str(clean), "--budget", "100000"]) == 0
    out = capsys.readouterr().out
    for check_id in CHECK_IDS:
        assert check_id in out
    assert "Result: PASS (exit 0)" in out
    assert "estimated tokens" in out


def test_pr_comment_markdown(clean, capsys):
    assert cli_main(["ci", str(clean), "--budget", "100000",
                     "--pr-comment"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("## GhostSlice CI")
    assert "| Check | Status | Evidence |" in out
    for check_id in CHECK_IDS:
        assert f"| {check_id} |" in out
    assert "**Context:**" in out and "estimated tokens" in out
    assert "**Result:** PASS" in out


def test_out_writes_html_report(clean, tmp_path, capsys):
    report = tmp_path / "report.html"
    assert cli_main(["ci", str(clean), "--budget", "100000",
                     "--out", str(report)]) == 0
    text = report.read_text(encoding="utf-8")
    assert "GhostSlice" in text and "<" in text
    assert f"Report: {report}" in capsys.readouterr().out


def test_out_unwritable_exits_2_with_payload_note(clean, tmp_path,
                                                  capsys):
    blocker = _write(tmp_path, "blocker", "not a dir")
    code = cli_main(["ci", str(clean), "--budget", "100000", "--json",
                     "--out", str(blocker / "report.html")])
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"]["written"] is False
    assert payload["exit_code"] == 0  # the checks themselves passed


# -- read-only discipline ----------------------------------------------

def test_ci_writes_nothing(clean):
    _write(clean, ".ghostslice-history.jsonl",
           '{"kind": "export", "before_tokens": 1, '
           '"after_tokens": 1}\n')
    before = _snapshot(clean)
    payload = run_ci(clean, budget=100000)
    assert payload["exit_code"] == 0
    assert _snapshot(clean) == before
    assert cli_main(["ci", str(clean), "--budget", "100000"]) == 0
    assert _snapshot(clean) == before


# -- dogfood: this repo -------------------------------------------------

def test_self_run_on_this_repo_exits_0():
    payload = run_ci(REPO)
    assert _status(payload, "budget") == "skipped"
    assert _status(payload, "fit") == "skipped"
    assert _status(payload, "secrets") == "pass"
    assert payload["exit_code"] == 0


def test_dogfood_budget_passes_on_this_repo():
    # The budget value is the dogfood workflow's (180,000 through
    # v1.0.4; re-measured and bumped to 230,000 in v1.0.5 when the
    # sliced total reached 99.9% of it — see the workflow comment).
    payload = run_ci(REPO, budget=230000)
    assert _status(payload, "budget") == "pass"
    assert _status(payload, "fit") == "pass"
    assert payload["exit_code"] == 0


# -- workflow samples ----------------------------------------------------

def test_sample_workflow_structure():
    text = SAMPLE.read_text(encoding="utf-8")
    assert "\t" not in text  # YAML forbids tabs
    for needle in ("actions/checkout@v4", "actions/setup-python@v5",
                   "actions/upload-artifact@v4",
                   "actions/github-script@v7",
                   "git+https://github.com/littlestjames82-sys/ghostslice",
                   "ghostslice ci", "--json", "--pr-comment", "--out",
                   "GHOSTSLICE_BUDGET", "GITHUB_TOKEN",
                   "GITHUB_OUTPUT", "outputs.exit_code"):
        assert needle in text, needle
    # The install honesty note: GhostSlice is not on PyPI.
    assert "not on PyPI" in text
    # The verdict is enforced from the captured exit code, never by
    # masking it: no continue-on-error anywhere in the sample.
    assert "continue-on-error" not in text


def test_dogfood_workflow_structure():
    text = DOGFOOD.read_text(encoding="utf-8")
    assert "\t" not in text
    assert "ghostslice ci" in text
    assert "--budget 230000" in text
    assert "PYTHONPATH=src" in text
    assert "actions/checkout@v4" in text
