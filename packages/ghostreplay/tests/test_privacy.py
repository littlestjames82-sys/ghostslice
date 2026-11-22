"""Privacy contract test (PLAN verification bar).

The planted secret-shaped string lives in the secret_* fixture INPUTS.
It must appear in ZERO files produced by analyse or propose: reports,
proposals, and any ledger written into the project/out dirs. Findings
may name path + line + type only; the string itself is never quoted.
"""
from pathlib import Path

from conftest import (BUNDLE, PLANTED_SECRET, SESSIONS, run_cli)


def _all_output_bytes(roots):
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                yield path, path.read_bytes()


def test_planted_secret_appears_in_zero_outputs(tmp_path, require_core, project_copy):
    out_a = tmp_path / "out_analyse"
    res = run_cli(
        ["analyse", project_copy, SESSIONS / "secret_1.jsonl",
         "--bundle", BUNDLE, "--out", out_a],
        cwd=tmp_path,
    )
    assert res.returncode == 0, f"analyse failed: {res.stdout}\n{res.stderr}"

    out_p = tmp_path / "out_propose"
    res = run_cli(
        ["propose", project_copy,
         SESSIONS / "secret_1.jsonl", SESSIONS / "secret_2.jsonl",
         SESSIONS / "secret_3.jsonl",
         "--bundle", BUNDLE, "--out", out_p],
        cwd=tmp_path,
    )
    assert res.returncode == 0, f"propose failed: {res.stdout}\n{res.stderr}"

    needle = PLANTED_SECRET.encode()
    scanned = 0
    # Roots cover the report/proposal dirs AND the project copy, whose
    # .ghostreplay-history.jsonl ledger is also a tool output.
    for path, data in _all_output_bytes([out_a, out_p, project_copy]):
        # The fixture inputs live outside tmp_path, so everything scanned
        # here is tool output (reports, proposals, ledgers, caches).
        if path.suffix in (".jsonl",) and "sessions" in str(path):
            continue
        scanned += 1
        assert needle not in data, f"planted secret leaked into output file {path}"
    assert scanned > 0, "no output files were produced to scan"
    # Stdout/stderr of an analysis must not echo the secret either.
    # (Checked on a fresh analyse run.)
    res = run_cli(
        ["analyse", project_copy, SESSIONS / "secret_1.jsonl",
         "--bundle", BUNDLE, "--out", tmp_path / "out_again"],
        cwd=tmp_path,
    )
    assert PLANTED_SECRET not in res.stdout
    assert PLANTED_SECRET not in res.stderr
